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

Coverage (Contract P/Q): `coverage` names the campaign-window days the platform read has not
covered (`triage.coverage_gap`) over `start_date … min(end_date, org yesterday)` -- today is
never a complete day -- and says `never_synced` instead of a wall of dates when nothing was read.
"""

from datetime import date, timedelta

from app.core import settings as coresettings
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy


def sample_bucket(purchases: int, days: int) -> str:
    """低（< 10 purchases 或 < 3 天）／中（10–49）／高（>= 50）——分級死規則（F03 決策 3），
    never a percentage. 之後給建議（F04）跟學習分級（F03-I12）共用同一個定義。"""
    if purchases < 10 or days < 3:
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


def _coverage(conn: _AnyConn, org_id: str, campaign: dict) -> dict:
    """Contract P's `coverage`: the campaign window `start_date … min(end_date, org yesterday)`
    checked against the recorded platform-read coverage by `triage.coverage_gap` (the rule
    triage/closeout/review share). No window (no start date, or it starts today or later) ⇒
    `expected` 0 and nothing missing; `never_synced` still says whether anything was ever read."""
    from app.ads import triage  # 延遲 import 避免循環

    start = campaign.get("start_date")
    yesterday = coresettings.today_for_org(conn, org_id=org_id) - timedelta(days=1)
    end = campaign.get("end_date")
    end = min(end, yesterday) if end is not None else yesterday
    has_window = start is not None and end >= start
    gap = triage.coverage_gap(campaign, start, end) if has_window else {
        **triage.coverage_gap(campaign, end, end), "missing_days": [],
    }
    return {
        "start": start.isoformat() if has_window else None,
        "end": end.isoformat() if has_window else None,
        "expected": (end - start).days + 1 if has_window else 0,
        "missing": len(gap["missing_days"]),
        "missing_days": gap["missing_days"],
        "never_synced": gap["never_synced"],
    }


def summary(conn: _AnyConn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """成效分頁的整包 payload：campaign 層總計（只算投放組粒度的列，§0「Money totals
    belong to the group level」）、每日序列、每投放組／每廣告一列（含花費占比）、資料覆蓋率
    跟最後更新時間。"""
    from app.ads import repository as ads_repo

    detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("campaign_unknown")

    group_rows = rows(conn, org_id, brand_id, campaign_id, "group")
    ad_rows = rows(conn, org_id, brand_id, campaign_id, "ad")

    totals = _bucket(group_rows)
    daily = _daily_series(group_rows)

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
        "coverage": _coverage(conn, org_id, detail),
        "last_data_at": last_data_at,
    }
