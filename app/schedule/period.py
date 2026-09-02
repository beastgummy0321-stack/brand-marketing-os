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


def compute_money(conn, org_id: str, brand_id: str, period: dict, competitors: list) -> tuple:
    """回傳 (spend, revenue)——範圍是這個檔期依 `_owned_ranges_and_ties()` 擁有／分到的
    那些日子。花費走 `routes._approval_overspend()` 已經在用的同一條路
    (`bound_account_ids_for_brand` + `spend_summary(..., level="campaign")`，`level`
    沒得省，見該函式的說明)；營收走 `orders_repo.channel_revenue_summary()`——這是這期間
    全通路營收，不是這期廣告帶來的營收（ticket 明講：歸因是 T5／T6 的事）。

    並列的日子（ADR 0053 決策 4：天數並列最短時平分）逐日單獨查一次那一天的總額再
    `_split_evenly()`，不是整段一起查——並列組每天的成員可能不一樣（另一個並列檔期的
    日期範圍不必跟這個檔期完全重疊）。"""
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    owned, tied_days = _owned_ranges_and_ties(period, competitors)
    spend = 0.0
    revenue = 0.0
    for start, end in owned:
        spend_summary = meta_repo.spend_summary(
            conn, org_id, account_ids, start, end + timedelta(days=1), level="campaign",
        )
        spend += spend_summary["total"]["spend"]
        revenue_summary = orders_repo.channel_revenue_summary(
            conn, brand_id, since=start.isoformat(), until=end.isoformat(),
        )
        revenue += revenue_summary["revenue"] or 0.0
    for day, tied_group in tied_days:
        n = len(tied_group)
        my_index = next(i for i, p in enumerate(tied_group) if p["id"] == period["id"])
        day_spend = meta_repo.spend_summary(
            conn, org_id, account_ids, day, day + timedelta(days=1), level="campaign",
        )["total"]["spend"]
        spend += _split_evenly(day_spend, n, my_index)
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
