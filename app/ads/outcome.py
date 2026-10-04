"""app/ads/outcome.py — the performance tab of an internal campaign (§0 the "outcome" link).
Private to app/ads (container contract §1).

F37 (one performance pipeline): an internal campaign's numbers are the platform sync's own
rows -- `ads_external_daily` read through `repository.performance_rows` (Contract P), the same
rows and the same recorded coverage the home, workspace, triage and review read. The manual
ingest path (`meta_entity_spend` → `POST …/ingest` → a second daily table) is gone; a simulated
campaign writes the same rows through `adapters/simulated.py` like a platform, so nothing here
branches on real/simulated. `rows()` is the one read every other ads reader of daily
performance calls (`experiments`, `ab_pairs`, `visual_learning`, `simulation_recovery`).

`purchases`/`revenue` are nullable: `NULL` means untracked, `0` a real, counted zero. Every
reader below (`_bucket`, `repository._outcome_totals`, `experiments.py`) sums only the
non-`NULL` rows and reports `None`/`NULL` when nothing in the set is tracked -- unknown is never
coerced into zero. `spend`/`impressions`/`clicks` of a platform row may also be unknown; `_bucket`
sums the known ones (a row with no known spend adds nothing, it is not invented).

Coverage (Contract P/Q, F49 Contract V): `coverage` names the campaign-window days nobody read
(`coverage.gap`: no row and no clean read range) over `start_date … min(end_date, org yesterday)`
-- today is never a complete day -- and says `never_synced` instead of a wall of dates when
nothing was read.
"""

from datetime import date, timedelta

from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy


SAMPLE_UNTRACKED = "未追蹤"


def sample_bucket(purchases: int | None, days: int) -> str:
    """低（< `triage.MIN_RESULT_EVENTS` purchases 或 < `triage.WINDOW_STEPS[0]` 天）／中（到 49）／
    高（>= 50）；`purchases is None`（沒追蹤到購買數）＝「未追蹤」，never 低 or 0. F48 Contract R:
    a shown label only -- no verdict reads it -- and its thresholds are the ruler's own
    (the same "too new" line as triage's `sample`), never a copy."""
    from app.ads import triage  # 延遲 import 避免循環

    if purchases is None:
        return SAMPLE_UNTRACKED
    if purchases < triage.MIN_RESULT_EVENTS or days < triage.WINDOW_STEPS[0]:
        return "低"
    if purchases < 50:
        return "中"
    return "高"


def rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str, kind: str) -> list:
    """F37 Contract P: this campaign's daily platform rows at `kind` in {"group", "ad"}, keyed by
    the LOCAL node id -- `repository.performance_rows`, the one mapping."""
    from app.ads import repository as ads_repo  # 延遲 import 避免循環

    return ads_repo.performance_rows(conn, org_id, brand_id, campaign_id, kind)


def _fetch_rows(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str,
                 entity_kind: str) -> list:
    return rows(conn, org_id, brand_id, campaign_id, entity_kind)


def _bucket(rows: list) -> dict:
    """跟 `app/schedule/performance.py::_bucket()` 同一套算法（再實作一份，不 import —
    container contract §5）：`roas`/optimistic 只算「有追蹤到營收」那一份花費當分母，
    `roas_conservative` 用**全部**花費當分母——兩個都是真的，只印一個是在說謊的另一半。
    購買數／營收是否追蹤直接看欄位是不是 `NULL`（平台列的 `purchases`／`revenue` 是 nullable，
    未追蹤就是 `NULL`，不用猜來源是哪個平台）；有追蹤到的列一起加總，完全沒有追蹤到的列讓整包
    回 `None`，未追蹤永遠不是 0。花費／曝光／點擊只加總已知的值。"""
    spend = round(sum(float(r["spend"]) for r in rows if r["spend"] is not None), 2)
    impressions = sum(int(r["impressions"]) for r in rows if r["impressions"] is not None)
    clicks = sum(int(r["clicks"]) for r in rows if r["clicks"] is not None)

    tracked_purchase_rows = [r for r in rows if r["purchases"] is not None]
    purchases = (
        sum(int(r["purchases"]) for r in tracked_purchase_rows) if tracked_purchase_rows
        else None
    )

    revenue_tracked_rows = [r for r in rows if r["revenue"] is not None]
    revenue = None
    roas = None
    roas_conservative = None
    if revenue_tracked_rows:
        revenue = round(sum(float(r["revenue"]) for r in revenue_tracked_rows), 2)
        spend_tracked = sum(
            float(r["spend"]) for r in revenue_tracked_rows if r["spend"] is not None
        )
        roas = (revenue / spend_tracked) if spend_tracked else None
        roas_conservative = (revenue / spend) if spend else None

    cpa = (spend / purchases) if purchases else None
    ctr = (clicks / impressions) if impressions else None

    return {
        "spend": spend, "impressions": impressions, "clicks": clicks,
        "purchases": purchases, "revenue": revenue, "cpa": cpa, "ctr": ctr,
        "roas": roas, "roas_conservative": roas_conservative,
    }


def _daily_series(rows: list) -> list:
    by_day: dict[date, list] = {}
    for row in rows:
        by_day.setdefault(row["day"], []).append(row)
    return [{"day": day, **_bucket(day_rows)} for day, day_rows in sorted(by_day.items())]


def _coverage(conn: _AnyConn, org_id: str, brand_id: str, campaign: dict, today: date) -> dict:
    """Contract P's `coverage`: the campaign window `start_date … min(end_date, org yesterday)`
    checked day by day by `coverage.gap` (F49 Contract V, the rule triage/closeout/review share).
    No window (no start date, or it starts today or later) ⇒ `expected` 0 and nothing missing;
    `never_synced` still says whether anything was ever read."""
    from app.ads import coverage  # 延遲 import 避免循環

    start = campaign.get("start_date")
    yesterday = today - timedelta(days=1)
    end = campaign.get("end_date")
    end = min(end, yesterday) if end is not None else yesterday
    if start is None or end < start:
        never_synced = coverage.gap(conn, org_id, brand_id, campaign, end, end)["never_synced"]
        return {"start": None, "end": None, "expected": 0, "missing": 0, "missing_days": [],
                "never_synced": never_synced}
    gap = coverage.gap(conn, org_id, brand_id, campaign, start, end)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected": (end - start).days + 1,
        "missing": len(gap["missing_days"]),
        "missing_days": gap["missing_days"],
        "never_synced": gap["never_synced"],
    }


def _window_days(campaign: dict, today: date, daily: list) -> int:
    """The period the status row grades: `start_date … min(end_date, today)` in calendar days
    (today included -- `totals` already sums today's rows). A campaign with no window yet (no
    start date, or one after its end) is graded over the days it actually has rows for."""
    start, end = campaign.get("start_date"), campaign.get("end_date")
    end = min(end, today) if end is not None else today
    if start is None or end < start:
        return len(daily)
    return (end - start).days + 1


def _period_view(totals: dict, group_rows: list, result_kind: str | None) -> dict | None:
    """The one result view `triage.grade_window` reads, cut from the SAME `_bucket` totals the
    tab prints (never a second aggregation): `result_count` = `totals.purchases`,
    `cost_per_result` = `totals.cpa`. Untracked everywhere (`purchases` `None`) is no view; a
    period with an untracked day or an unknown spend, or across two currencies, keeps its number
    but reads as unknown through `reason` -- the same signals `review_evidence.aggregate` and
    `triage._ad_window` give, so the period grade never outruns a per-ad grade."""
    if totals["purchases"] is None:
        return None
    currencies = {r["currency"] for r in group_rows}
    reason = None
    if len(currencies) > 1:
        reason = "mixed_currency"
    elif any(r["purchases"] is None or r["spend"] is None for r in group_rows):
        reason = "result_unknown_days"
    return {
        "metric_scope": "group", "currency": next(iter(currencies)) if len(currencies) == 1
        else None, "result_kind": result_kind, "result_count": totals["purchases"],
        "cost_per_result": totals["cpa"], "reason": reason,
    }


def _period_grade(campaign: dict, totals: dict, group_rows: list, daily: list, cap: dict,
                  today: date) -> dict:
    """F40-I01: `totals.grade` = the one cap ruler (`triage.grade_window`, ads.md §6.33) over the
    whole period -- `{grade, label}`, `grade` in on_target|watch|over|wasted|insufficient|
    no_target. No cap, or a cap with no result kind anywhere (the precondition `triage` and
    `period_grades._grade` share), is `no_target`."""
    from app.ads import triage  # 延遲 import 避免循環

    if cap["value"] is not None and cap["result_kind"] is None:
        return {"grade": "no_target", "label": triage.GRADE_LABELS["no_target"]}
    grade, label, _reason = triage.grade_window(
        _period_view(totals, group_rows, cap["result_kind"]), totals["spend"], cap["value"],
        _window_days(campaign, today, daily),
    )
    return {"grade": grade, "label": label}


def summary(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """成效分頁的整包 payload：campaign 層總計（只算投放組粒度的列，§0「Money totals
    belong to the group level」）、每日序列、每投放組／每廣告一列（含花費占比）、資料覆蓋率
    跟最後更新時間。F40-I01: `totals.grade` is the period's one-ruler grade the 成效分頁's
    「這期狀態列」 prints beside 整期合計 (`_period_grade`, the backend's answer -- never a
    frontend copy of the ruler)."""
    from app.ads import repository as ads_repo
    from app.ads import targets

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")
    today = coresettings.today_for_org(conn, org_id=org_id)

    group_rows = rows(conn, org_id, brand_id, campaign_id, "group")
    ad_rows = rows(conn, org_id, brand_id, campaign_id, "ad")

    totals = _bucket(group_rows)
    daily = _daily_series(group_rows)
    cap = targets.resolve(conn, org_id, brand_id, detail)
    totals["grade"] = _period_grade(detail, totals, group_rows, daily, cap, today)

    group_total_spend = sum(
        float(r["spend"]) for r in group_rows if r["spend"] is not None
    ) or 0.0
    by_group: dict[str, list] = {}
    for row in group_rows:
        by_group.setdefault(row["entity_id"], []).append(row)
    groups_table = []
    for group in detail["groups"]:
        node_rows = by_group.get(group["id"], [])
        bucket = _bucket(node_rows)
        bucket["group_id"] = group["id"]
        bucket["name"] = group["name"]
        bucket["spend_share"] = (bucket["spend"] / group_total_spend) if group_total_spend else None
        groups_table.append(bucket)

    ad_total_spend = sum(
        float(r["spend"]) for r in ad_rows if r["spend"] is not None
    ) or 0.0
    by_ad: dict[str, list] = {}
    for row in ad_rows:
        by_ad.setdefault(row["entity_id"], []).append(row)
    ads_table = []
    for group in detail["groups"]:
        for ad in group["ads"]:
            node_rows = by_ad.get(ad["id"], [])
            bucket = _bucket(node_rows)
            bucket["ad_id"] = ad["id"]
            bucket["name"] = ad["name"]
            bucket["spend_share"] = (bucket["spend"] / ad_total_spend) if ad_total_spend else None
            ads_table.append(bucket)

    all_rows = group_rows + ad_rows
    last_data_at = max((r["observed_at"] for r in all_rows), default=None)

    return {
        "totals": totals,
        "daily": daily,
        "groups": groups_table,
        "ads": ads_table,
        "coverage": _coverage(conn, org_id, brand_id, detail, today),
        "last_data_at": last_data_at,
    }
