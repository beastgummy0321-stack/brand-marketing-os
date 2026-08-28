"""把既有判讀與下期建議收斂成最多三張週提案卡。"""


from app.ads import nextcycle
from app.ads import plan as ads_plan
from app.ads import reading as ads_reading
from app.ads import reading_assets as ads_reading_assets
from app.ads import repository as ads_repo
from app.ads import settlement as ads_settlement
from app.brand_intelligence import repository as bi
from app.core import interrupts as core_interrupts
from app.core import orchestrator as core_orchestrator
from app.core import rule_cards
from app.core.audit import write_audit
from app.core.db import jsonb, new_id, now_utc

RECOMMENDATION_TYPE = "weekly_proposal"
# 票 F9：結案時還沒被使用者處理的 GENERATED 卡的終態——`recommendation.status` 沒有
# CHECK constraint（純文字欄，見 migrations/0001_tables.sql 該欄註解），新增這個值只是
# 新增程式碼認得的字串，不是改 schema（比照 app/brand_intelligence/repository.py:1278）。
ARCHIVED_ON_CLOSE = "ARCHIVED_ON_CLOSE"

GRADE_BY_ACTION = {
    "停掉": "save",
    "加碼": "spend",
    "換素材": "asset",
}


def _instruction(action: str, target: str, names: list | None = None) -> str:
    """票 F13：`names` 給了（產品層停掉卡點得出底下哪幾支廣告）就直接叫使用者去找那幾支，
    不再送使用者去 Meta 後台找一個不存在的「產品」物件（B0-43）。沒給就沿用今天的措辭。"""
    verb = {"停掉": "暫停投放", "加碼": "提高預算", "換素材": "替換素材"}[action]
    if names:
        quoted = "".join(f"「{name}」" for name in names)
        return f"前往 Meta 廣告後台，找到{quoted}並{verb}。"
    return f"前往 Meta 廣告後台，找到「{target}」並{verb}。"


def _copy(card: dict) -> str:
    if card.get("is_historical_angle"):
        return (f"{card['reason']}——建議別再用「{card['target']}」這個投放方向"
                f"（之前檔期用過的舊方向，不是這期的廣告）。")
    names = card.get("bleeding_asset_names")
    if names:
        return (f"{card['reason']}——建議{card['action']}「{card['target']}」"
                f"底下 {len(names)} 支：{'、'.join(names)}。")
    return f"{card['reason']}——建議{card['action']}「{card['target']}」。"


def _action_card(card: dict) -> str | None:
    if card["status"] not in ("ACCEPTED", "APPLIED"):
        return None
    grade = GRADE_BY_ACTION[card["action"]]
    if grade == "asset":
        if card.get("is_historical_angle"):
            return f"前往素材工作檯，準備取代「{card['target']}」這個舊方向的新素材。"
        return f"前往素材工作檯，為「{card['target']}」準備新素材。"
    instruction = card.get("instruction") or _instruction(
        card["action"], card["target"], card.get("bleeding_asset_names"))
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


def _newest_pending_card_ts(conn, brand_id: str, cycle_id: str) -> "str | None":
    row = conn.execute(
        "SELECT MAX(created_at) AS ts FROM recommendation WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND recommendation_type = %s AND status = 'GENERATED'",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    return row["ts"] if row else None


def current_cycle(conn, brand_id: str) -> dict | None:
    """駕駛艙週作戰用哪一期：優先挑還有 GENERATED（未核可）週提案卡候著使用者的那個
    投放中／等判讀檔期；同時有兩期在投放中時，光看「起始日最新」會讓使用者匯入資料的
    那期被更新但空手的另一期蓋掉，卡片永遠看不到（票 F1）。

    R2 審查抓到：兩期「都」候著卡時，原本的寫法還是照 start_date DESC 挑第一個候選，
    等於在這個子集合裡又退回「起始日最新」，複製了同一個症狀。改成比「候著的卡最後
    建出的時間」（`recommendation.created_at`）——剛匯入資料建出的卡，時間戳一定比
    先前就候著、沒人動過的舊卡新，這樣才真的認「剛匯入的那期」而不是「起始日」。
    都沒有候核可的卡才退回舊規則（起始日最新那個）。這是唯一進入點——六個顯示
    呼叫端都經由這裡，不逐一加特例。"""
    live_cycles = [c for c in ads_repo.list_cycles(conn, brand_id)
                  if c["status"] in ("LIVE", "EVALUATING")]
    if not live_cycles:
        return None
    pending = [(cycle, _newest_pending_card_ts(conn, brand_id, cycle["id"]))
              for cycle in live_cycles]
    pending = [(cycle, ts) for cycle, ts in pending if ts is not None]
    if pending:
        pending.sort(key=lambda pair: pair[1], reverse=True)
        return pending[0][0]
    return live_cycles[0]


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


def _losing_assets(conn, brand_id: str, loaded: dict, budget: dict) -> list:
    """本期 attributable 廣告裡，套 `reading.judge()` 同一套停損門檻篩出來的『該停』清單
    （ADR 0025 決定 5／9），照 `asset_breakdown` 原順序（revenue DESC）回傳全部，不只
    最差那支。從 `bleeding_asset()` 原地拆出來（票 F13）：`bleeding_asset()` 再從裡面挑
    最差的一支點名到廣告層；產品層停掉卡（`select_cards()`）點名底下每一支也吃這份同一
    份清單——同一套 `asset_breakdown`、同一個 `judge()` 呼叫、同一條 `plan_budget` 均分，
    不重算門檻、不另開查詢（決定 3／5）。"""
    result = (loaded.get("cycle") or {}).get("result") or {}
    breakdown = [row for row in (result.get("asset_breakdown") or []) if row.get("attributable")]
    if not breakdown:
        return []
    breakeven = result.get("breakeven")
    plan_budget = (budget.get("current_budget") or 0) / len(breakdown)
    return [row for row in breakdown
            if ads_reading.judge(row, plan_budget=plan_budget, breakeven=breakeven,
                                 brand_id=brand_id, conn=conn)["status"] == "pause_candidate"]


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
    losing = _losing_assets(conn, brand_id, loaded, budget)
    if not losing:
        return None
    breakeven = ((loaded.get("cycle") or {}).get("result") or {}).get("breakeven")
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
                 fatigue: dict | None = None, bleeding: dict | None = None, *,
                 losing_assets: list | None = None,
                 current_cycle_angles=None) -> list:
    """只挑已有規則訊號的停掉、加碼、換素材；沒有訊號就不硬湊。

    append 順序即優先序，因為最後 `cards[:3]` 是照順序砍尾巴。ADR 0025 決定 7 定的順序是
    「止血 → 花錢 → 備料」：廣告層停掉 → 產品層停掉 → 加碼 → 疲勞換素材 → 歷史切角換素材。

    `losing_assets`（票 F13，keyword-with-default，舊呼叫端不用管）：跟 `bleeding_asset()`
    同一份『這期該停的廣告』清單（`_losing_assets()`），拿來把產品層停掉卡點名到底下真的
    屬於這個產品（`product_id` 相等）的廣告；不給、或沒有任何一支屬於這個產品，卡就照今天
    的措辭只點名產品（B0-43）。
    `current_cycle_angles`（票 F13，同樣 keyword-with-default）：這期
    `experiment_cell.creative_angle` 的集合。歷史切角卡只在這個角度還活在這期時才出——
    不給（None）沿用今天行為，不擋任何卡（B0-42）。判準只看角度是否存在於這個集合，
    不對字串本身做任何「看起來像不像內部代號」的猜測。
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
        product_id = reading.get("product_id")
        card = {
            "action": action,
            "target": reading.get("product_name") or "未命名產品",
            "reason": reasons[0] if reasons else "既有成效判讀已達行動門檻",
            "impact": _budget_impact(action, budget),
            "product_id": product_id,
            "performance_reading_id": reading.get("id"),
            "suggested_amount": budget.get("proposed_budget") if action == "加碼" else None,
        }
        if status == "pause_candidate" and product_id is not None and losing_assets:
            names = [row["asset_name"] for row in losing_assets
                    if row.get("product_id") == product_id]
            if names:
                card["bleeding_asset_names"] = names
        cards.append(card)

    # 疲勞燈紅（頻率過冷受眾危險門檻）也要有卡跟進，但同一支廣告已經有停掉卡就不出：先做
    # 新素材再去停一支正在虧的廣告，順序是反的（決定 8）。認同一支要比 pkg_id 不能比 target
    # ——疲勞卡的目標可能是切角名，停掉卡一定是廣告名，兩個命名空間對不起來。
    fatigue_pkg = fatigue.get("pkg_id") if fatigue else None
    if fatigue is not None and not any(
            fatigue_pkg is not None and card.get("pkg_id") == fatigue_pkg for card in cards):
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
    # 票 F13（B0-42）：這張卡點名的角度要「這期還在跑」才有意義——是不是跟這期
    # experiment_cell.creative_angle 有交集，不是看字串長得像不像內部代號（鐵則 16）。
    if (tired_cell is not None and current_cycle_angles is not None
            and (tired_cell.get("creative_angle") or "未命名切角") not in current_cycle_angles):
        tired_cell = None
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
                # B0-11：這張卡點名的是切角（可能橫跨好幾支廣告、也可能是別期留下來的舊方向），
                # 不是這期的一支廣告——`_copy()`／`_action_card()` 靠這個旗標換一句誠實的講法，
                # 不把切角名冒充成廣告名（ADR 0025 決定 8：這裡本來就走切角命名空間，既有行為不動）。
                "is_historical_angle": True,
            })
    return cards[:3]


def _card_from_row(row) -> dict:
    content = row["content_json"] or {}
    return {"id": row["id"], **content, "status": row["status"]}


def list_cards(conn, brand_id: str, cycle_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    return [_card_from_row(row) for row in rows]


def _cards_summary(conn, brand_id: str, cycle_id: str, status: str) -> dict:
    rows = conn.execute(
        "SELECT content_json FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s AND status = %s ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE, status),
    ).fetchall()
    names = [(row["content_json"] or {}).get("target", "") for row in rows]
    return {"count": len(names), "names": names}


def unhandled_cards(conn, brand_id: str, cycle_id: str) -> dict:
    """票 F9：settle-now 按下前，這期還候著使用者處理的 GENERATED 卡——純讀取，settle-now
    GET 拿這個問「結案後會怎樣」，POST 前也拿它預告等一下 archive_on_close() 會歸檔幾張。"""
    return _cards_summary(conn, brand_id, cycle_id, "GENERATED")


def archived_on_close_cards(conn, brand_id: str, cycle_id: str) -> dict:
    """票 F9：settle-now POST 回應用——結案當下歸檔了哪些卡。can_settle() 擋掉了對已
    CLOSED 檔期重複呼叫這支路由，所以這裡讀到的一定是這次結案剛歸檔的那批，不會混到
    別次結案的舊資料。"""
    return _cards_summary(conn, brand_id, cycle_id, ARCHIVED_ON_CLOSE)


def archive_on_close(conn, brand_id: str, cycle_id: str, actor: str) -> dict:
    """票 F9 root cause：結案時把還候著使用者處理的 GENERATED 週提案卡收斂成明確終態，
    不再讓它們在 `reading.run()` 的重判清空邏輯裡被 DELETE 悄悄消失（本函式的呼叫端見
    `reading.py::run()`，settled_run 分支已經把 ARCHIVED_ON_CLOSE 併入 preserved_weekly，
    這裡才不會轉態完馬上被同一次呼叫的 DELETE 清掉）。

    順手在收件匣留一筆已結的痕跡——不然使用者只在結案當下的回應看過一次這個數字，
    事後想確認「這期結案時歸檔了幾張」就無處可查（契約第 4 點）。"""
    cards = unhandled_cards(conn, brand_id, cycle_id)
    if cards["count"] == 0:
        return cards
    conn.execute(
        "UPDATE recommendation SET status = %s, updated_at = %s WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND recommendation_type = %s AND status = 'GENERATED'",
        (ARCHIVED_ON_CLOSE, now_utc(), brand_id, cycle_id, RECOMMENDATION_TYPE),
    )
    _brand = bi.get_brand(conn, brand_id)
    assert _brand is not None, f"找不到品牌：{brand_id}"
    interrupt_id = core_interrupts.enqueue(
        conn, org_id=_brand["org_id"],
        category="weekly_proposal_archived_on_close",
        dedupe_key=f"weekly_proposal_archived_on_close:{cycle_id}",
        message=f"{cards['count']} 張建議卡因檔期結案歸檔",
        brand_id=brand_id, campaign_cycle_id=cycle_id,
    )
    if interrupt_id:  # None＝去重命中，理論上結案只會轉態一次，這裡只是不假設呼叫端不重複呼叫
        core_interrupts.resolve(conn, interrupt_id, actor=actor)
    return cards


def generate(conn, brand_id: str, cycle_id: str, *, enqueue_ready: bool = True) -> list:
    """依最新判讀建卡；保留已產生卡，並略過已核可／已執行的同動作同目標。"""
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    existing = list_cards(conn, brand_id, cycle_id)
    if any(card["status"] == "GENERATED" for card in existing):
        return existing

    loaded = ads_reading.load(conn, brand_id, cycle_id)
    budget = nextcycle.propose_budget(conn, brand_id, cycle_id)
    historical_cells = nextcycle.historical_cell_performance(
        conn, brand_id, exclude_cycle_id=cycle_id)
    # 票 F13：這期真的還在跑的切角——歷史切角卡（B0-42）跟產品層停掉卡的廣告點名（B0-43）
    # 都要靠這份「這期」的事實核對，不是猜字串。
    current_cycle_angles = {
        row["creative_angle"] for row in ads_plan.list_cell_angles(conn, brand_id, cycle_id)
        if row.get("creative_angle")
    }
    cards = select_cards(loaded["products"], budget, historical_cells,
                         fatigue_asset(conn, brand_id, cycle_id),
                         bleeding_asset(conn, brand_id, cycle_id, loaded, budget),
                         losing_assets=_losing_assets(conn, brand_id, loaded, budget),
                         current_cycle_angles=current_cycle_angles)
    handled = {
        (card.get("action"), card.get("target"))
        for card in existing if card["status"] in ("ACCEPTED", "APPLIED", "REJECTED")
    }
    cards = [card for card in cards if (card["action"], card["target"]) not in handled]
    ts = now_utc()
    for card in cards:
        content = {key: card[key] for key in ("action", "target", "reason", "impact")}
        if card.get("suggested_amount") is not None:
            content["suggested_amount"] = card["suggested_amount"]
        if card.get("is_historical_angle"):
            content["is_historical_angle"] = True
        if card.get("bleeding_asset_names"):
            content["bleeding_asset_names"] = card["bleeding_asset_names"]
        content["instruction"] = _instruction(
            card["action"], card["target"], card.get("bleeding_asset_names"))
        conn.execute(
            "INSERT INTO recommendation (id, org_id, brand_id, campaign_cycle_id, product_id,"
            " performance_reading_id, recommendation_type, content_json, status, created_at,"
            " updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'GENERATED', %s, %s)",
            (new_id("rec"), org_id, brand_id, cycle_id, card["product_id"],
             card["performance_reading_id"], RECOMMENDATION_TYPE,
             jsonb(content), ts, ts),
        )
    if cards and enqueue_ready:
        core_interrupts.enqueue(
            conn, org_id=org_id, category="weekly_proposal_ready",
            dedupe_key=f"weekly_proposal_ready:{cycle_id}",
            message=f"{len(cards)} 張提案等你核可",
            brand_id=brand_id, campaign_cycle_id=cycle_id,
        action_url=f"/app/brands/{brand_id}",
        )
    conn.commit()
    return list_cards(conn, brand_id, cycle_id)


def _rerun_result(conn, brand_id: str, cycle_id: str, rerun: str, base_message: str,
                  *, shift: "str | None" = None) -> dict:
    """票 F1 root cause 3：訊息不能先斬後奏——只有真的有 GENERATED 卡候著使用者核可，
    才能說「有新的建議卡」，不然畫面上一張卡都沒有卻說有，使用者會覺得系統在說謊。

    R2 審查抓到：`action_url` 以前指到 `/app/brands/{bid}/campaigns/{cid}`
    （WarroomRoute → WarroomPage，S8 檔期建置／管理畫面），那裡完全沒有週提案卡的
    UI。真正顯示週提案卡的是品牌層駕駛艙 `/app/brands/{bid}`（CockpitPage →
    WeeklyBattleSection，經 `current_cycle()` 自己解析要顯示哪一期，不需要 URL
    帶檔期）——跟這支檔案裡 `weekly_proposal_ready` interrupt（見下方 `enqueue`
    呼叫）、`routes_weekly_proposals_api.py` 的 `_queue_rejudge_notice` 用的是
    同一個已經在用、也是唯一有卡片 UI 的網址，不另立一條。"""
    cards = generate(conn, brand_id, cycle_id)
    pending = sum(1 for card in cards if card["status"] == "GENERATED")
    message = f"{base_message}「本週作戰」有 {pending} 張新的建議卡。" if pending else base_message
    return {
        "rerun": rerun,
        "rerun_message": message,
        "shift": shift,
        "weekly_cards": {"cycle_id": cycle_id, "generated": pending,
                         "action_url": f"/app/brands/{brand_id}"},
    }


def rerun_after_late_data(conn, brand_id: str, cycle_id: str, actor: str) -> dict:
    """ADR 0022 第 2／4 點：已經判讀過的檔期又動到數字（補匯或撤銷），自動重判一次並說哪裡變了。

    算不算「晚到」由 `ads_reading.rerun_for_late_data` 自己判（還在 LIVE、或根本沒判讀過都回
    None），跟拖檔口 `app/orders/dispatch.py` 走同一條路，不在這裡另立一套規則。

    它「重判了但數字沒變」跟「根本沒重判」都回 None，訊息因此會說謊（驗收 A 第 4 節第 7 題：
    明明算過了卻寫「沒有重新算過」）——這裡用結算版次有沒有進位自己分辨這兩件事。

    LIVE 檔期的第一次判讀，`rerun_for_late_data` 故意當作「不是補件」原樣略過（見它的
    docstring）——但這正是使用者投放中匯入成效後看不到逐支表／AI 白話／週提案卡的根因：
    沒有任何排程／按鈕會在匯入的當下幫 LIVE 檔期跑第一次判讀，只能乾等 day7 提醒、每週一
    背景排程，或使用者自己去駕駛艙按「現在就重新判讀」。這裡直接補上這一次。

    票 F1：這是所有「匯入／撤銷觸發重判」入口共用的唯一出處——CSV／手動填成效、批次刪除、
    拖檔口晚到資料都走這裡，不在各自呼叫端各自補一次 `generate()`；漏掉 `generate()` 的
    入口，卡片就被 `reading.run()` 清掉後沒人補（見 `reading.py` 的 `preserved_weekly`
    刪除範圍）。
    """
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is not None and cycle["status"] == "LIVE":
        ok, _err = ads_reading.run(conn, brand_id, cycle_id, actor)
        if not ok:
            return {"rerun": "skipped", "rerun_message": None}
        return _rerun_result(conn, brand_id, cycle_id, "live_reading", "已經判讀這期最新資料。")

    before = ads_settlement.load_snapshot(conn, brand_id, cycle_id)
    result = ads_reading.rerun_for_late_data(conn, brand_id, cycle_id, actor=actor)
    if result:
        base = result["explanation"] or "結論已經重新算過，數字有變動。"
        return _rerun_result(conn, brand_id, cycle_id, "late_data", base, shift=result["shift"])
    after = ads_settlement.load_snapshot(conn, brand_id, cycle_id)
    if before and after and after["settlement_version"] > before["settlement_version"]:
        return _rerun_result(conn, brand_id, cycle_id, "unchanged", "結論重新算過了，跟上次一樣。")
    return {"rerun": "skipped", "rerun_message": None}


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
        "SELECT 1 FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s AND status = 'GENERATED' LIMIT 1",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if pending:
        return
    for interrupt in core_interrupts.list_open(
            conn, brand_id=brand_id, category="weekly_proposal_ready", archive_stale=False):
        if interrupt["campaign_cycle_id"] == cycle_id:
            core_interrupts.resolve(conn, interrupt["id"], actor=actor)


def cycle_id_for_recommendation(conn, brand_id: str, recommendation_id: str) -> "str | None":
    """票 F1 R2：品牌層單卡核可／略過端點不能靠 `current_cycle()` 猜檔期——那是給
    「畫面現在該顯示哪期」用的推斷，會隨別期匯入資料而改變。使用者按的是畫面上
    看得到的這張卡，卡本身的 `campaign_cycle_id` 才是唯一該問的對象，直接查。"""
    row = conn.execute(
        "SELECT campaign_cycle_id FROM recommendation WHERE id = %s AND brand_id = %s"
        " AND recommendation_type = %s",
        (recommendation_id, brand_id, RECOMMENDATION_TYPE),
    ).fetchone()
    return row["campaign_cycle_id"] if row else None


def approve_card(conn, brand_id: str, cycle_id: str, recommendation_id: str, *,
                 actor: str, confirmed_amount=None) -> dict:
    """核可單張卡；花錢卡沒有正數確認金額就拒絕。"""
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = %s AND brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s",
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

    ts = now_utc()
    content = {key: value for key, value in card.items() if key not in ("id", "status")}
    conn.execute(
        "UPDATE recommendation SET content_json = %s, status = 'ACCEPTED', updated_at = %s"
        " WHERE id = %s",
        (jsonb(content), ts, recommendation_id),
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="recommendation",
        entity_id=recommendation_id,
        action="accept_weekly_proposal", actor=actor,
        before={"status": row["status"]}, after={"status": "ACCEPTED"},
    )
    _resolve_ready_interrupt_if_finished(conn, brand_id, cycle_id, actor)
    conn.commit()
    card["status"] = "ACCEPTED"
    return present(card, brand_id)


def skip(conn, brand_id: str, cycle_id: str, recommendation_id: str, *, actor: str) -> dict:
    """略過單張卡；重送同一張維持略過。"""
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = %s AND brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    if row["status"] == "REJECTED":
        return present(_card_from_row(row), brand_id)
    if row["status"] != "GENERATED":
        raise ValueError("這張週提案卡已經核可")
    conn.execute(
        "UPDATE recommendation SET status = 'REJECTED', updated_at = %s WHERE id = %s",
        (now_utc(), recommendation_id),
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="recommendation",
        entity_id=recommendation_id,
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
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s AND status = 'GENERATED' ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    ts = now_utc()
    approved = []
    pending_confirmation = []
    for row in rows:
        card = _card_from_row(row)
        if GRADE_BY_ACTION[card["action"]] == "spend":
            pending_confirmation.append(present(card, brand_id))
            continue
        conn.execute(
            "UPDATE recommendation SET status = 'ACCEPTED', updated_at = %s WHERE id = %s",
            (ts, row["id"]),
        )
        write_audit(
            conn, org_id=org_id, brand_id=brand_id, entity_type="recommendation", entity_id=row["id"],
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
        "SELECT * FROM recommendation WHERE id = %s AND brand_id = %s AND campaign_cycle_id = %s"
        " AND recommendation_type = %s",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    if row["status"] == "APPLIED":
        return _card_from_row(row)
    if row["status"] != "ACCEPTED":
        raise ValueError("這張週提案卡還沒核可")

    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    ts = now_utc()
    conn.execute(
        "UPDATE recommendation SET status = 'APPLIED', updated_at = %s WHERE id = %s",
        (ts, recommendation_id),
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="recommendation",
        entity_id=recommendation_id,
        action="apply_weekly_proposal", actor=actor,
        before={"status": "ACCEPTED"}, after={"status": "APPLIED"},
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM recommendation WHERE id = %s", (recommendation_id,)).fetchone()
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
