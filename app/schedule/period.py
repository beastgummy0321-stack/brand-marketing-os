"""app/schedule/period.py — 票 T2b（ADR 0053）：檔期的狀態、日子擁有權、結算金額。

跟 `plan.py`／`tree.py`／`creative.py` 同一個角色：這裡是純函數＋唯讀查詢，`routes.py`
只管驗證與 HTTP 邊界（要不要拋 `web.ApiError`、拋哪個 code），這裡的函數一律回
`(結果, 失敗說明)` 或直接回結果，不 import `app.shared.web`、不自己拋 `ApiError`——
跟 `plan.build_plans()`／`tree.build_tree()` 同一個既有慣例。落地（INSERT／UPDATE）留在
`schedule_repo`；本檔只讀（`schedule_repo.get_latest_period()` 等）＋算。

Private to `app/schedule`（container contract §1）：只有 `routes.py` 呼叫這裡。
"""

from datetime import date, timedelta

from app.core import settings as coresettings
from app.core.audit import write_audit
from app.core.db import now_utc
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo
from app.orders import repository as orders_repo
from app.schedule import repository as schedule_repo
from app.schedule.plan import largest_remainder_allocation

DATES_REQUIRED_MESSAGE = "請填這期的開始日與結束日。"
END_BEFORE_START_MESSAGE = "結束日不能早於開始日。"
NOT_STARTED_MESSAGE = "這期還沒開始投放，沒有東西可以結算。"
# 幣別（ADR 0053 沒有回答這一格從哪來）：這個系統目前唯一算過錢的地方全部假設新台幣——
# 規則卡 schedule_budget.daily_budget 的 unit 寫死「NT$」（app/core/rule_cards.py），
# `order_record` 沒有幣別輸入時也是逐字寫死 "TWD"（app/orders/repository.py:168），前端
# `formatCurrency()` 也是逐字印 "NT$"（frontend/src/lib/format.ts）——沿用同一個假設，不是
# 新發明一個「品牌幣別」概念（brand 表、product_economics、meta_ad_account 三個地方的
# 幣別彼此不保證一致，這張票不解那題）。
CURRENCY = "TWD"


def validate_dates(start_date: str, end_date: str) -> tuple:
    """回傳 `(start, end, code, message)`——`code`／`message` 是 `None` 就是通過。"""
    if not start_date or not end_date:
        return None, None, "period_dates_required", DATES_REQUIRED_MESSAGE
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return None, None, "period_dates_required", DATES_REQUIRED_MESSAGE
    if end < start:
        return None, None, "period_end_before_start", END_BEFORE_START_MESSAGE
    return start, end, None, None


def _duration_days(period: dict) -> int:
    return (period["end_date"] - period["start_date"]).days


def _tied_shortest_owners(covering: list) -> list[dict]:
    """`covering`（哪些非草稿檔期蓋住這一天）裡天數並列最短的檔期——唯一最短時只有一個
    元素（全拿），並列時不只一個（見 `_day_ownership()` 怎麼處理並列）。"""
    shortest = min(_duration_days(p) for p in covering)
    return [p for p in covering if _duration_days(p) == shortest]


def _day_ownership(period: dict, competitors: list, day: date) -> tuple[bool, list[dict]]:
    """這一天，`period` 拿到什麼：`(整天全拿？, 並列平分的組——依 id 排序，不含自己代表
    這天跟 period 無關)`。唯一最短 → 全拿；並列 → 沒有整天全拿，回並列組讓呼叫端平分。"""
    covering = [p for p in competitors if p["start_date"] <= day <= p["end_date"]]
    if not covering:
        return False, []
    tied = _tied_shortest_owners(covering)
    if len(tied) == 1:
        return tied[0]["id"] == period["id"], []
    if any(p["id"] == period["id"] for p in tied):
        return False, sorted(tied, key=lambda p: p["id"])
    return False, []


def _owned_ranges_and_ties(period: dict, competitors: list) -> tuple[list[tuple], list[tuple]]:
    """ADR 0053 決策 4：走一次 `period` 自己的日期範圍，回傳
    `(全拿的連續日期區間, 並列平分的單日清單)`——`competitors` 是「結算當下存在」的非草稿
    檔期集合（含 `period` 自己）。

    全拿的日子照舊把連續的日子併成一段，餵給 `meta_repo.spend_summary()`／
    `orders_repo.channel_revenue_summary()` 那種吃單一區間的既有函式。並列的日子（兩個以上
    檔期天數一樣短）在檔期層沒有 `allocation_weight` 可讀（那是 T3 廣告組合層的欄位）——
    「並列 → 平分」在這裡就是 N 等分，回傳 `(day, 排序過的並列組)`，讓 `compute_money()`
    用 `largest_remainder_allocation()` 分那一天的總額，不必另開一條吃任意日期集合的查詢
    路徑，也不讓浮點誤差決定最後一分錢由誰拿。"""
    ranges: list[tuple] = []
    ties: list[tuple] = []
    run_start = None
    day = period["start_date"]
    while day <= period["end_date"]:
        owns, tied_group = _day_ownership(period, competitors, day)
        if owns and run_start is None:
            run_start = day
        elif not owns and run_start is not None:
            ranges.append((run_start, day - timedelta(days=1)))
            run_start = None
        if tied_group:
            ties.append((day, tied_group))
        day += timedelta(days=1)
    if run_start is not None:
        ranges.append((run_start, period["end_date"]))
    return ranges, ties


def settlement_advice_days() -> int:
    """ADR 0053 §3：7 天的建議值直接讀 Meta 自己的歸因窗常數
    （`app/meta/graph.py` `_ATTRIBUTION_WINDOWS` 的 `7d_click`），不另開一個
    `SETTLEMENT_WAIT_DAYS` 自己的數字——T4 的 `ad_channel.data_lag_days` 落地那天，這裡
    換成讀那一欄，這份 ADR 不必修訂。"""
    click_window = next(
        w for w in meta_graph._ATTRIBUTION_WINDOWS if w.endswith("d_click")
    )
    return int(click_window.removesuffix("d_click"))


def _split_evenly(total: float, n: int, my_index: int) -> float:
    """把 `total`（元，可能有分）N 等分，回傳第 `my_index` 份——用
    `largest_remainder_allocation()`（分錢已有的最大餘數法，不重寫第二套）在「分」的整數
    刻度上分，加總永遠精確等於 `total`；`n` 份浮點數各自 `/ n` 不保證加總精確等於
    `total`（IEEE-754），也不保證最後一分錢有人拿。"""
    total_cents = round(total * 100)
    shares = largest_remainder_allocation(total_cents, [1.0 / n] * n)
    return shares[my_index] / 100


def node_level_spend(period: dict, competitors: list, memberships: list, daily_rows: list) -> float:
    """票 T3e（ADR 0055 §11）：`period` 這一期在它自己 `[start_date, end_date]` 裡拿到
    多少花費——「已登記」＋「沒登記時落到它頭上的那份」。ADR 0053 §4 的規則本身不變
    （並列最短全拿、平手看權重／均分），改的只是套用的主詞：從「整個品牌那天的花費」
    換成「這個節點那天的花費」。純函數、無 I/O，跟旁邊的 `_owned_ranges_and_ties()`
    同一個形狀——連接資料庫的事留給呼叫端 `compute_money()`。

    - **已登記**：`daily_rows` 裡一筆（某實體、某天）的花費，只要那個實體那天至少有一筆
      `memberships` 蓋到，就照 ADR 0053 §4 在「蓋到那天的那些 membership 各自所屬的檔期」
      之間分——天數並列最短的檔期全拿；並列時照 `allocation_weight` 正規化分（跟品牌層
      的並列不同：品牌層沒有 `allocation_weight` 可讀，只能均分）。
      「蓋到」同時夾兩層：membership 自己的 `[from_date, to_date]`要蓋到那天，**而且**
      它掛的檔期（用 `campaign_period_id` 去 `competitors` 查）自己的 `[start_date,
      end_date]` 也要蓋到那天——ticket 矛盾檢查段的結論：membership 說蓋到不代表那期真的
      擁有那天，兩邊都要夾（ADR 0055 §11：「兩邊都夾在檔期自己的日期範圍裡」）。任一邊夾
      不住，這筆錢在這天就當沒登記，落進未登記那堆。
    - **未登記**：當天沒有（夾過範圍的）membership 蓋到的實體，花費照舊算給「那天歸誰」
      的品牌層擁有者——`_day_ownership()`，今天的規則原封不動套用在剩下的那些錢上
      （ADR 0055 §11：「這是今天的行為，不變，套用在剩下的東西上」）。
    - `period` 自己範圍外的天，兩邊都不算——外層只走 `period` 自己的
      `[start_date, end_date]`，不會有機會替範圍外的一天分錢。

    金額一律用「分」的整數刻度切（`largest_remainder_allocation()`，跟 `_split_evenly()`
    同一套工具），不是浮點數各自相除——並列組的加總永遠精確等於那筆錢，最後一分錢一定有
    人拿。"""
    periods_by_id = {p["id"]: p for p in competitors}
    rows_by_day: dict = {}
    for row in daily_rows:
        rows_by_day.setdefault(row["spend_date"], []).append(row)

    total = 0.0
    day = period["start_date"]
    while day <= period["end_date"]:
        unregistered = 0.0
        for row in rows_by_day.get(day, []):
            covering = [
                m for m in memberships
                if m["entity_id"] == row["entity_id"]
                and m["from_date"] <= day
                and (m["to_date"] is None or day <= m["to_date"])
                and (mp := periods_by_id.get(m["campaign_period_id"])) is not None
                and mp["start_date"] <= day <= mp["end_date"]
            ]
            if not covering:
                unregistered += row["spend"]
                continue
            by_period: dict = {}
            for m in covering:
                by_period.setdefault(m["campaign_period_id"], []).append(m)
            shortest = min(_duration_days(periods_by_id[pid]) for pid in by_period)
            tied_pids = [
                pid for pid in by_period if _duration_days(periods_by_id[pid]) == shortest
            ]
            if len(tied_pids) == 1:
                if tied_pids[0] == period["id"]:
                    total += row["spend"]
                continue
            if period["id"] not in tied_pids:
                continue
            weights = {
                pid: sum(m["allocation_weight"] for m in by_period[pid]) for pid in tied_pids
            }
            total_weight = sum(weights.values())
            shares = [weights[pid] / total_weight for pid in tied_pids]
            cents = largest_remainder_allocation(round(row["spend"] * 100), shares)
            total += cents[tied_pids.index(period["id"])] / 100
        owns, tied_group = _day_ownership(period, competitors, day)
        if owns:
            total += unregistered
        elif tied_group:
            n = len(tied_group)
            my_index = next(i for i, p in enumerate(tied_group) if p["id"] == period["id"])
            total += _split_evenly(unregistered, n, my_index)
        day += timedelta(days=1)
    return total


def compute_money(conn, org_id: str, brand_id: str, period: dict, competitors: list) -> tuple:
    """回傳 (spend, revenue)。

    花費（票 T3e，ADR 0055 §11）走 `node_level_spend()`：讀這個檔期自己
    `[start_date, end_date]` 那段的逐日逐實體花費（`meta_repo.daily_entity_spend(...,
    level="adset")`——**這裡從 `level="campaign"` 換成 `level="adset"`，因為
    membership 認的是廣告組合，用不同層算剩下的錢會兜不起來，見 ticket §5**；
    `tree_approval._approval_overspend()` 是另一條獨立的呼叫路徑，不經過這裡，沒有被這個
    改動動到）＋這個品牌的 `period_node_membership`（JOIN 過 `channel_entity_map` 換出
    entity_id，`schedule_repo.period_node_memberships_for_brand()`），純函數自己決定
    每一筆錢算誰的。

    營收走 `orders_repo.channel_revenue_summary()`，範圍是 `_owned_ranges_and_ties()`
    算出來、這個檔期在品牌層擁有／分到的那些日子——這是這期間全通路營收，不是這期廣告
    帶來的營收（ticket 明講：歸因是 T5／T6 的事），也不按節點拆（ADR 0053／0055 §11：
    營收不分節點，這一段完全不動）。並列的日子（ADR 0053 決策 4）逐日單獨查一次再
    `_split_evenly()`，不是整段一起查——並列組每天的成員可能不一樣。"""
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    daily_rows = meta_repo.daily_entity_spend(
        conn, org_id, account_ids, period["start_date"],
        period["end_date"] + timedelta(days=1), level="adset",
    )
    memberships = schedule_repo.period_node_memberships_for_brand(conn, org_id, brand_id)
    spend = node_level_spend(period, competitors, memberships, daily_rows)

    owned, tied_days = _owned_ranges_and_ties(period, competitors)
    revenue = 0.0
    for start, end in owned:
        revenue_summary = orders_repo.channel_revenue_summary(
            conn, brand_id, since=start.isoformat(), until=end.isoformat(),
        )
        revenue += revenue_summary["revenue"] or 0.0
    for day, tied_group in tied_days:
        n = len(tied_group)
        my_index = next(i for i, p in enumerate(tied_group) if p["id"] == period["id"])
        day_revenue = orders_repo.channel_revenue_summary(
            conn, brand_id, since=day.isoformat(), until=day.isoformat(),
        )["revenue"] or 0.0
        revenue += _split_evenly(day_revenue, n, my_index)
    return round(spend, 2), round(revenue, 2)


def _advance_if_ended(conn, org_id: str, period: dict) -> dict:
    """ADR 0053 決策 2：`running` 過了 `end_date` 自動變 `awaiting_data`——讀的時候順手算，
    不是背景工作。落地（一次 UPDATE，冪等）而不是每次現算：結算端點檢查的是存起來的值。"""
    if period["status"] != "running":
        return period
    today = coresettings.today_for_org(conn, org_id=org_id)
    if today <= period["end_date"]:
        return period
    schedule_repo.advance_period_to_awaiting_data(conn, org_id, period["id"])
    period = dict(period)
    period["status"] = "awaiting_data"
    return period


def brand_period_response(conn, org_id: str, brand_id: str) -> dict | None:
    """`routes._brand_response()` 的 `period` 鍵——這個品牌目前顯示的那一個檔期（最新
    一列，見 `schedule_repo.get_latest_period()` 的說明），`None` 代表這個品牌從沒出過
    方案。"""
    period = schedule_repo.get_latest_period(conn, org_id, brand_id)
    if period is None:
        return None
    period = _advance_if_ended(conn, org_id, period)
    advice_date = period["end_date"] + timedelta(days=settlement_advice_days())

    settled = None
    if period["settled_at"] is not None:
        # late_*_since 是「現在」跟凍結快照的差——用「現在存在」的檔期集合重算一次，不是
        # 結算當下那份（那份沒有存，也不該存：凍結的只有 settled_spend／settled_revenue／
        # settled_at 這三個數字，見 ADR 0053 §3 與 ticket 的矛盾檢查段）。
        competitors = schedule_repo.list_non_draft_periods(conn, org_id, brand_id)
        current_spend, current_revenue = compute_money(conn, org_id, brand_id, period, competitors)
        settled = {
            "spend": float(period["settled_spend"]),
            "revenue": float(period["settled_revenue"]),
            "settled_at": period["settled_at"].isoformat(),
            "late_spend_since": round(current_spend - float(period["settled_spend"]), 2),
            "late_revenue_since": round(current_revenue - float(period["settled_revenue"]), 2),
        }

    return {
        "id": period["id"],
        "name": period["name"],
        "status": period["status"],
        "start_date": period["start_date"].isoformat(),
        "end_date": period["end_date"].isoformat(),
        "daily_budget": (
            float(period["daily_budget"]) if period["daily_budget"] is not None else None
        ),
        "currency": period["currency"],
        "settle_advice_date": advice_date.isoformat(),
        "settled": settled,
    }


def settle(conn, *, org_id: str, brand_id: str, period_id: str, actor: str) -> str | None:
    """票 T2b（ADR 0053 §3／§4）：結算——凍結這個檔期在它擁有的日子裡花了多少、賺了
    多少。回傳失敗代碼（`"not_found"`／`"not_started"`）或 `None`（成功）——`routes.py`
    負責把代碼翻成 HTTP 錯誤（跟這個模組一樣不 import `app.shared.web`）。

    租戶界線在 `schedule_repo.get_period()` 的 WHERE 裡（`org_id`／`brand_id` 都要對得上，
    `period_id` 是使用者給的，不能只信主鍵）——`brand_id` 對了不代表 `period_id` 也是這個
    組織的（ticket 矛盾檢查段第三點）。"""
    period = schedule_repo.get_period(conn, org_id, brand_id, period_id)
    if period is None:
        return "not_found"
    if period["status"] == "planning":
        return "not_started"

    competitors = schedule_repo.list_non_draft_periods(conn, org_id, brand_id)
    spend, revenue = compute_money(conn, org_id, brand_id, period, competitors)
    settled_at = now_utc()
    today = coresettings.today_for_org(conn, org_id=org_id)
    advice_date = period["end_date"] + timedelta(days=settlement_advice_days())
    is_early = today < advice_date

    if period["settled_at"] is not None:
        # 重新結算：舊的三個數字先進 audit_log 再覆寫（ADR 0053 §3：快照可以被換掉，
        # 不能悄悄換掉）。
        write_audit(
            conn, org_id=org_id, brand_id=brand_id, entity_type="campaign_period",
            entity_id=period_id, action="resettle", actor=actor,
            before={
                "settled_spend": float(period["settled_spend"]),
                "settled_revenue": float(period["settled_revenue"]),
                "settled_at": period["settled_at"].isoformat(),
            },
            after={"settled_spend": spend, "settled_revenue": revenue,
                   "settled_at": settled_at.isoformat()},
        )

    schedule_repo.write_settlement(
        conn, org_id=org_id, period_id=period_id, spend=spend, revenue=revenue,
        settled_at=settled_at, force_early=is_early,
    )
    return None
