# -*- coding: utf-8 -*-
"""把既有判讀與下期建議收斂成最多三張週提案卡。"""

import json

from app.ads import nextcycle
from app.ads import reading as ads_reading
from app.ads import reading_assets as ads_reading_assets
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core import orchestrator as core_orchestrator
from app.core import rule_cards
from app.core.audit import write_audit
from app.core.db import new_id, now_iso


RECOMMENDATION_TYPE = "weekly_proposal"

GRADE_BY_ACTION = {
    "停掉": "save",
    "加碼": "spend",
    "換素材": "asset",
}


def _instruction(action: str, target: str) -> str:
    verb = {"停掉": "暫停投放", "加碼": "提高預算", "換素材": "替換素材"}[action]
    return f"前往 Meta 廣告後台，找到「{target}」並{verb}。"


def _copy(card: dict) -> str:
    return f"{card['reason']}——建議{card['action']}「{card['target']}」。"


def _action_card(card: dict) -> str | None:
    if card["status"] not in ("ACCEPTED", "APPLIED"):
        return None
    grade = GRADE_BY_ACTION[card["action"]]
    if grade == "asset":
        return f"前往素材工作檯，為「{card['target']}」準備新素材。"
    instruction = card.get("instruction") or _instruction(card["action"], card["target"])
    if grade == "spend":
        amount = card.get("confirmed_amount")
        if amount is None:
            return None
        return f"{instruction} 已確認金額為 NT${amount:,.0f}。"
    return instruction


def present(card: dict, brand_id: str) -> dict:
    """把既有週提案補成 T1 行動卡 API 形狀，不新增資料表。"""
    grade = GRADE_BY_ACTION[card["action"]]
    spend_confirmation = None
    if grade == "spend":
        spend_confirmation = {
            "required": True,
            "suggested_amount": card.get("suggested_amount"),
            "currency": "TWD",
        }
    action_card = _action_card(card)
    return {
        **card,
        "grade": grade,
        "copy": _copy(card),
        "spend_confirmation": spend_confirmation,
        "action_card": action_card,
        "action_url": f"/app/brands/{brand_id}/workbench" if action_card and grade == "asset" else None,
    }


def current_cycle(conn, brand_id: str) -> dict | None:
    """駕駛艙週作戰使用最新一個投放中或等判讀的未封存檔期。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            return cycle
    return None


def _budget_impact(action: str, budget: dict) -> str:
    current = budget.get("current_budget") or 0
    proposed = budget.get("proposed_budget") or 0
    if action == "加碼" and proposed > current:
        return f"下期總預算增加 NT${proposed - current:,.0f}，且不超過既有增幅上限"
    if action == "停掉" and proposed < current:
        return f"下期總預算減少 NT${current - proposed:,.0f}，先守住停損線"
    return {
        "停掉": "避免低於停損門檻的項目繼續消耗預算",
        "加碼": "把下期預算優先移向已達加碼門檻的產品",
    }[action]


def _tired_reason(cell: dict) -> str:
    """換素材卡的理由照 `cell_trust_flags()` 標的路徑寫。零成交跟「有成交但沒回本」是兩件
    不同的事，共用同一句就會對著 12 筆成交的切角說「沒有帶來成交」（驗收 A 第 4 節 6c）。
    路徑②寫出實際投報率與停損線（＝打平線 × `reading.PAUSE_MARGIN`，沿用既有那條線）。"""
    if cell.get("underperforming_reason") != "roas_below_stop_loss":
        return "花了一半預算還是零成交"
    spend = cell.get("spend") or 0
    breakeven = cell.get("breakeven_roas")
    if not spend or not breakeven:
        return "有成交，但投報率低於停損線"
    return (f"有成交但每花 1 元只回 {(cell.get('revenue') or 0) / spend:.2f} 元，"
            f"低於停損線 {breakeven * ads_reading.PAUSE_MARGIN:.2f}")


FATIGUE_AUDIENCE_TYPE = "cold"


def _fatigue_reason(frequency: float) -> str:
    return f"頻率 {frequency:.1f}，同一群人平均看了 {int(frequency)} 次以上，素材疲勞"


def fatigue_asset(conn, brand_id: str, cycle_id: str) -> dict | None:
    """疲勞燈紅的時候，點名本期頻率最高的那支廣告（沒紅、或點不到名就回 None）。

    紅不紅走 `rule_cards.classify_ad_frequency()` 的既有冷受眾危險門檻，跟健康燈
    （app/ads/health_lights.py:96）同一張規則卡、同一個判定，不在這裡另立第二套數字；
    差別只在燈看整期最大頻率、這裡逐支取 max 才知道要換哪一支。"""
    worst = ads_reading_assets.max_frequency_by_asset(conn, brand_id, cycle_id)
    if worst is None:
        return None
    status = rule_cards.classify_ad_frequency(
        conn, brand_id, FATIGUE_AUDIENCE_TYPE, worst["frequency"])
    return worst if status == "danger" else None


def _bleeding_reason(asset: dict, breakeven) -> str:
    """廣告層停掉卡的理由句（ADR 0025 決定 12）。

    `judge()` 的 pause_candidate 理由寫的是「這些產品要投報 X 倍才回本」，主詞是產品，
    套到單支廣告上是錯的；改那句會波及檔期層與產品層兩個既有呼叫端，所以這裡另寫一句。
    形狀比照 `_tired_reason()` 路徑②——使用者要能自己驗算為什麼這支該停、其他支不用。
    分兩條，對應 `judge()` 的兩條停損路徑：零成交、有成交但低於停損線。
    """
    spend = asset.get("spend") or 0
    if not asset.get("conversions"):
        return f"花了 {spend:,.0f} 元還是一筆都沒成交"
    roas = (asset.get("kpis") or {}).get("roas")
    if roas is None or not breakeven:
        return "有成交，但投報率低於停損線"
    return (f"有成交但每花 1 元只回 {roas:.2f} 元，"
            f"低於停損線 {breakeven * ads_reading.PAUSE_MARGIN:.2f}")


def bleeding_asset(conn, brand_id: str, cycle_id: str, loaded: dict, budget: dict) -> dict | None:
    """本期逐支廣告裡「該停」的那一支，點名到廣告（＝ADR 0008 的主題層），沒有就回 None。

    ADR 0025：
    - 決定 3（資料窗）：讀本期，不讀歷史。數字直接取 `reading.load()` 已經算好的
      `asset_breakdown` 與 `breakeven`，不新開查詢、不重算打平線。
    - 決定 5（門檻）：走 `reading.judge()` 同一套判定，`plan_budget` 用「檔期預算 ÷ 本期
      廣告支數」均分（先例：`nextcycle.historical_cell_performance()` 對切角也是均分）。
      不用 `nextcycle.cell_trust_flags()`——那條路沒有 `MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL`
      這道護欄，換素材可以繞過它（便宜、可逆），叫人關掉一支廣告不行。
    - 決定 6：只點名最差的一支（投報率最低）。算不出投報率的是零成交那條路踩到的，
      比任何算得出來的都糟，排最前面。
    - 決定 9：歸屬對不準的廣告（`attributable` 為 0）不參加，也不代它說話。
    """
    result = (loaded.get("cycle") or {}).get("result") or {}
    breakdown = [row for row in (result.get("asset_breakdown") or []) if row.get("attributable")]
    if not breakdown:
        return None
    breakeven = result.get("breakeven")
    plan_budget = (budget.get("current_budget") or 0) / len(breakdown)
    losing = [row for row in breakdown
              if ads_reading.judge(row, plan_budget=plan_budget, breakeven=breakeven,
                                   brand_id=brand_id, conn=conn)["status"] == "pause_candidate"]
    if not losing:
        return None
    worst = min(losing, key=lambda row: ((row.get("kpis") or {}).get("roas") is not None,
                                         (row.get("kpis") or {}).get("roas") or 0))
    return {
        "action": "停掉",
        "target": worst["asset_name"],
        "reason": _bleeding_reason(worst, breakeven),
        # 決定 13：停一支廣告跟下期總預算增減沒有因果，不走 `_budget_impact()`——照套會說出
        # 「停掉這支 → 下期總預算增加」（整檔還在賺的時候下期預算是加的）這種自相矛盾的話。
        "impact": "先止住這支的花費，另外幾支照跑",
        # 決定 11：廣告層沒有 product_id（交接包掛在切角上，切角的 product_id 常是 NULL），
        # 填 None 不編造歸屬；判讀列指向檔期層那筆——這張卡的數字來源 asset_breakdown 就存在
        # 它的 rule_result_json 裡，日後回答「當時憑什麼叫我停」查得回當時的逐支數字。
        "product_id": None,
        "performance_reading_id": (loaded.get("cycle") or {}).get("id"),
        "pkg_id": worst.get("pkg_id"),
    }


def select_cards(product_readings: list, budget: dict, historical_cells: list,
                 fatigue: dict | None = None, bleeding: dict | None = None) -> list:
    """只挑已有規則訊號的停掉、加碼、換素材；沒有訊號就不硬湊。

    append 順序即優先序，因為最後 `cards[:3]` 是照順序砍尾巴。ADR 0025 決定 7 定的順序是
    「止血 → 花錢 → 備料」：廣告層停掉 → 產品層停掉 → 加碼 → 疲勞換素材 → 歷史切角換素材。
    """
    cards = []
    product_pause = next(
        (row for row in product_readings if row.get("status") == "pause_candidate"), None)
    # 決定 4：產品層已經要停時，廣告層那張不出——上位動作已經涵蓋下位，兩張並存會叫使用者
    # 把同一件事做兩次。反過來（產品沒事、底下有一支在漏血）才是這張卡要補的洞。
    if bleeding is not None and product_pause is None:
        cards.append(bleeding)
    for status, action in (
        ("pause_candidate", "停掉"),
        ("scale_candidate", "加碼"),
    ):
        reading = next((row for row in product_readings if row.get("status") == status), None)
        if reading is None:
            continue
        reasons = (reading.get("result") or {}).get("reasons") or []
        cards.append({
            "action": action,
            "target": reading.get("product_name") or "未命名產品",
            "reason": reasons[0] if reasons else "既有成效判讀已達行動門檻",
            "impact": _budget_impact(action, budget),
            "product_id": reading.get("product_id"),
            "performance_reading_id": reading.get("id"),
            "suggested_amount": budget.get("proposed_budget") if action == "加碼" else None,
        })

    # 疲勞燈紅（頻率過冷受眾危險門檻）也要有卡跟進，但同一支廣告已經有停掉卡就不出：先做
    # 新素材再去停一支正在虧的廣告，順序是反的（決定 8）。認同一支要比 pkg_id 不能比 target
    # ——疲勞卡的目標可能是切角名，停掉卡一定是廣告名，兩個命名空間對不起來。
    if fatigue is not None and not any(
            card.get("pkg_id") == fatigue.get("pkg_id") for card in cards):
        cards.append({
            "action": "換素材",
            "target": fatigue["target"],
            "reason": _fatigue_reason(fatigue["frequency"]),
            "impact": "同一批人已經看到膩，換一批素材才拉得回成效",
            "product_id": None,
            "performance_reading_id": None,
            "pkg_id": fatigue.get("pkg_id"),
        })

    tired_cell = next((cell for cell in historical_cells if cell.get("underperforming")), None)
    if tired_cell is not None:
        angle = tired_cell.get("creative_angle") or "未命名切角"
        # 歷史切角這張仍走切角命名空間，只跟同樣是換素材的卡比目標字串（既有行為不動）。
        if not any(card["action"] == "換素材" and card["target"] == angle for card in cards):
            cards.append({
                "action": "換素材",
                "target": angle,
                "reason": _tired_reason(tired_cell),
                "impact": "先換一批素材再測，不直接放大目前的低效花費",
                "product_id": None,
                "performance_reading_id": None,
            })
    return cards[:3]


def _card_from_row(row) -> dict:
    content = json.loads(row["content_json"] or "{}")
    return {"id": row["id"], **content, "status": row["status"]}


def list_cards(conn, brand_id: str, cycle_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ? ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    return [_card_from_row(row) for row in rows]


def generate(conn, brand_id: str, cycle_id: str, *, enqueue_ready: bool = True) -> list:
    """依最新判讀建卡；保留已產生卡，並略過已核可／已執行的同動作同目標。"""
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    existing = list_cards(conn, brand_id, cycle_id)
    if any(card["status"] == "GENERATED" for card in existing):
        return existing

    loaded = ads_reading.load(conn, brand_id, cycle_id)
    budget = nextcycle.propose_budget(conn, brand_id, cycle_id)
    historical_cells = nextcycle.historical_cell_performance(
        conn, brand_id, exclude_cycle_id=cycle_id)
    cards = select_cards(loaded["products"], budget, historical_cells,
                         fatigue_asset(conn, brand_id, cycle_id),
                         bleeding_asset(conn, brand_id, cycle_id, loaded, budget))
    handled = {
        (card.get("action"), card.get("target"))
        for card in existing if card["status"] in ("ACCEPTED", "APPLIED", "REJECTED")
    }
    cards = [card for card in cards if (card["action"], card["target"]) not in handled]
    ts = now_iso()
    for card in cards:
        content = {key: card[key] for key in ("action", "target", "reason", "impact")}
        if card.get("suggested_amount") is not None:
            content["suggested_amount"] = card["suggested_amount"]
        content["instruction"] = _instruction(card["action"], card["target"])
        conn.execute(
            "INSERT INTO recommendation (id, brand_id, campaign_cycle_id, product_id,"
            " performance_reading_id, recommendation_type, content_json, status, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'GENERATED', ?, ?)",
            (new_id("rec"), brand_id, cycle_id, card["product_id"],
             card["performance_reading_id"], RECOMMENDATION_TYPE,
             json.dumps(content, ensure_ascii=False), ts, ts),
        )
    if cards and enqueue_ready:
        core_interrupts.enqueue(
            conn, category="weekly_proposal_ready",
            dedupe_key=f"weekly_proposal_ready:{cycle_id}",
            message=f"{len(cards)} 張提案等你核可",
            brand_id=brand_id, campaign_cycle_id=cycle_id,
        action_url=f"/app/brands/{brand_id}",
        )
    conn.commit()
    return list_cards(conn, brand_id, cycle_id)


def view(conn, brand_id: str, cycle_id: str) -> dict:
    cards = list_cards(conn, brand_id, cycle_id)
    return {
        "proposals": [
            present(card, brand_id) for card in cards if card["status"] == "GENERATED"
        ],
        "execution_checklist": [
            present(card, brand_id)
            for card in cards if card["status"] in ("ACCEPTED", "APPLIED")
        ],
    }


def _resolve_ready_interrupt_if_finished(conn, brand_id: str, cycle_id: str, actor: str) -> None:
    pending = conn.execute(
        "SELECT 1 FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ? AND status = 'GENERATED' LIMIT 1",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if pending:
        return
    for interrupt in core_interrupts.list_open(
            conn, brand_id=brand_id, category="weekly_proposal_ready", archive_stale=False):
        if interrupt["campaign_cycle_id"] == cycle_id:
            core_interrupts.resolve(conn, interrupt["id"], actor=actor)


def approve_card(conn, brand_id: str, cycle_id: str, recommendation_id: str, *,
                 actor: str, confirmed_amount=None) -> dict:
    """核可單張卡；花錢卡沒有正數確認金額就拒絕。"""
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = ? AND brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ?",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    card = _card_from_row(row)
    if card["status"] in ("ACCEPTED", "APPLIED"):
        return present(card, brand_id)
    if card["status"] != "GENERATED":
        raise ValueError("這張週提案卡已經略過")

    grade = GRADE_BY_ACTION[card["action"]]
    if grade == "spend":
        if (isinstance(confirmed_amount, bool)
                or not isinstance(confirmed_amount, (int, float))
                or confirmed_amount <= 0):
            raise ValueError("花錢提案要先確認金額")
        card["confirmed_amount"] = float(confirmed_amount)

    ts = now_iso()
    content = {key: value for key, value in card.items() if key not in ("id", "status")}
    conn.execute(
        "UPDATE recommendation SET content_json = ?, status = 'ACCEPTED', updated_at = ?"
        " WHERE id = ?",
        (json.dumps(content, ensure_ascii=False), ts, recommendation_id),
    )
    write_audit(
        conn, brand_id=brand_id, entity_type="recommendation", entity_id=recommendation_id,
        action="accept_weekly_proposal", actor=actor,
        before={"status": row["status"]}, after={"status": "ACCEPTED"},
    )
    _resolve_ready_interrupt_if_finished(conn, brand_id, cycle_id, actor)
    conn.commit()
    card["status"] = "ACCEPTED"
    return present(card, brand_id)


def skip(conn, brand_id: str, cycle_id: str, recommendation_id: str, *, actor: str) -> dict:
    """略過單張卡；重送同一張維持略過。"""
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = ? AND brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ?",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    if row["status"] == "REJECTED":
        return present(_card_from_row(row), brand_id)
    if row["status"] != "GENERATED":
        raise ValueError("這張週提案卡已經核可")
    conn.execute(
        "UPDATE recommendation SET status = 'REJECTED', updated_at = ? WHERE id = ?",
        (now_iso(), recommendation_id),
    )
    write_audit(
        conn, brand_id=brand_id, entity_type="recommendation", entity_id=recommendation_id,
        action="skip_weekly_proposal", actor=actor,
        before={"status": row["status"]}, after={"status": "REJECTED"},
    )
    _resolve_ready_interrupt_if_finished(conn, brand_id, cycle_id, actor)
    conn.commit()
    card = _card_from_row(row)
    card["status"] = "REJECTED"
    return present(card, brand_id)


def approve(conn, brand_id: str, cycle_id: str, *, actor: str) -> dict:
    """一鍵核可省錢與產素材卡；花錢卡保留給逐張確認金額。"""
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ? AND status = 'GENERATED' ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    ts = now_iso()
    approved = []
    pending_confirmation = []
    for row in rows:
        card = _card_from_row(row)
        if GRADE_BY_ACTION[card["action"]] == "spend":
            pending_confirmation.append(present(card, brand_id))
            continue
        conn.execute(
            "UPDATE recommendation SET status = 'ACCEPTED', updated_at = ? WHERE id = ?",
            (ts, row["id"]),
        )
        write_audit(
            conn, brand_id=brand_id, entity_type="recommendation", entity_id=row["id"],
            action="accept_weekly_proposal", actor=actor,
            before={"status": row["status"]}, after={"status": "ACCEPTED"},
        )
        card["status"] = "ACCEPTED"
        approved.append(present(card, brand_id))
    _resolve_ready_interrupt_if_finished(conn, brand_id, cycle_id, actor)
    conn.commit()
    result = view(conn, brand_id, cycle_id)
    result["approved"] = approved
    result["pending_confirmation"] = pending_confirmation
    return result


def complete(conn, brand_id: str, cycle_id: str, recommendation_id: str, *, actor: str) -> dict:
    """把一張已核可卡標成完成；重送已完成的卡不重寫、不重複稽核。"""
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = ? AND brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ?",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    if row["status"] == "APPLIED":
        return _card_from_row(row)
    if row["status"] != "ACCEPTED":
        raise ValueError("這張週提案卡還沒核可")

    ts = now_iso()
    conn.execute(
        "UPDATE recommendation SET status = 'APPLIED', updated_at = ? WHERE id = ?",
        (ts, recommendation_id),
    )
    write_audit(
        conn, brand_id=brand_id, entity_type="recommendation", entity_id=recommendation_id,
        action="apply_weekly_proposal", actor=actor,
        before={"status": "ACCEPTED"}, after={"status": "APPLIED"},
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM recommendation WHERE id = ?", (recommendation_id,)).fetchone()
    return _card_from_row(updated)


# ---------------------------------------------------------------------------
# 調度台『優化』模組門面（票 O1-01，ADR 0024）
# ---------------------------------------------------------------------------

def status(conn, brand_id: str) -> dict:
    """調度台 facts：`optimize.cards_open`（還有幾張未核可的週提案卡）、
    `optimize.cycle_id`（給其他規則知道要對哪個檔期動作，例如創意.add_theme，
    不必各自重找一次 current_cycle()）。"""
    cycle = current_cycle(conn, brand_id)
    if cycle is None:
        return {"optimize.cards_open": 0, "optimize.cycle_id": None}
    cards_open = sum(
        1 for card in list_cards(conn, brand_id, cycle["id"]) if card["status"] == "GENERATED")
    return {"optimize.cards_open": cards_open, "optimize.cycle_id": cycle["id"]}


def handle(conn, action: dict) -> dict:
    """優化模組目前沒有任何規則指派 op 給它——票 03-orchestrator-core.md 原本猜
    `add_theme` 該登記在這裡，經查實際生成入口是 `generate_preselected_batch()`
    （PLAN.md 模組表 #5「創意」的既有進入點），改登記在 `app/ads/theme_batch.py`
    （票 O1-01 回報說明）。收到不認得的 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    raise ValueError(f"優化模組不認得這個 op：{action['op']}")


core_orchestrator.register_module("optimize", status=status, handle=handle)
