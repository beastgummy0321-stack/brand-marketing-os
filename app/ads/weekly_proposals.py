# -*- coding: utf-8 -*-
"""把既有判讀與下期建議收斂成最多三張週提案卡。"""

import json

from app.ads import nextcycle
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core import orchestrator as core_orchestrator
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


def select_cards(product_readings: list, budget: dict, historical_cells: list) -> list:
    """只挑已有規則訊號的停掉、加碼、換素材；沒有訊號就不硬湊。"""
    cards = []
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

    tired_cell = next((cell for cell in historical_cells if cell.get("underperforming")), None)
    if tired_cell is not None:
        cards.append({
            "action": "換素材",
            "target": tired_cell.get("creative_angle") or "未命名切角",
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
    cards = select_cards(loaded["products"], budget, historical_cells)
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
