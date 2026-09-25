"""app/ads/month_summary.py — F27-I07 Contract G: the monthly review summary and suggestion
dismissal. Read-only aggregation plus one small write (dismiss); no LLM call, no platform write
(ARCHITECTURE.md §0 "程式整理，LLM 判斷").

Scope: `campaigns` only ever lists `origin='imported'` campaigns -- Contract G's spend/result
grain is `ads_external_daily` (`metric_scope='ad'`), the same triage/existing-campaign data a
system-built (internal) campaign never writes (it is judged through `ads_outcome_daily` instead,
`repository.list_campaigns`'s own grain). Listing an internal campaign here would always read
`spend=None`/`verdict="unjudged"`, silently contradicting its real judged state elsewhere --
never a divergent, misleading second "judgment" for the same campaign.

Correction 6: month sums read only `metric_scope='ad'` rows -- the monthly-budget account rollup
rows (`external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY`) are always written under
`metric_scope='campaign'` (`adapters/meta_read.py::read_monthly`), so this filter alone already
excludes them; `review_evidence.aggregate()` also drops them defensively by attribution key
(belt-and-suspenders, never relied on twice for the same exclusion to matter).

`days_covered`/`days_elapsed` (correction 6): the SAME "elapsed days" pacing pair
`app/schedule/tree_approval.py::_approval_overspend` already uses for its own `days_elapsed`
(`today_for_org` clamped to the month) -- `days_covered` is the month's own full length,
`days_elapsed` the elapsed portion (0 for a future month, the full length once the month is
fully in the past). The orders comparison ("this month so far vs the same number of days of the
previous month") walks the same elapsed count backed into the previous month, capped at that
month's own length.

The write (`dismiss_suggestion`): `key` is `"<kind>:<campaign_id>"` -- brand-scoped route (no
campaign in the path, Contract G), so the campaign id has to come from the key itself. Stored in
`ads_campaign.context_json.month_dismissed[month]` via `jsonb_set`, same nested-merge shape
`external_repository.record_sync` already uses for `context_json.external_sync`.
"""

import calendar
import re
from datetime import date, datetime, time, timedelta

from app import orders
from app.ads import (
    ad_status,
    period_grades,
    repository,
    result_kinds,
    review_evidence,
    targets,
    triage,
    triage_capacity,
    triage_scale,
)
from app.core import settings as coresettings
from app.core.db import jsonb

_MONTH_RE = re.compile(r"\d{4}-\d{2}")
# The migration that first started recording `status_changed_at`
# (`supabase/migrations/20260922000001_ads_runtime_events.sql`) -- the honest fallback "since" for
# a brand that has never recorded a single status transition yet (never `None`, `closed_this_month`
# still has to know when "before tracking started" begins).
_TRACKING_FALLBACK = date(2026, 9, 22)
_SUGGESTION_KINDS = frozenset({"refresh", "cleanup", "no_target"})


def _require_month(month: str | None) -> str:
    if not isinstance(month, str) or not _MONTH_RE.fullmatch(month):
        raise ValueError("請提供 YYYY-MM 格式的月份。")
    return month


def _month_window(conn, org_id: str, month: str) -> tuple[date, date, int, int]:
    start = date.fromisoformat(month + "-01")
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    end = start.replace(day=days_in_month)
    today = coresettings.today_for_org(conn, org_id=org_id)
    if today < start:
        days_elapsed = 0
    elif today > end:
        days_elapsed = days_in_month
    else:
        days_elapsed = (today - start).days + 1
    return start, end, days_in_month, days_elapsed


def _ad_spend_and_currency(aggregated: dict) -> tuple[float | None, str | None]:
    """Same "one currency else null, any unknown day nulls the whole window" rule
    `triage.py::_ad_spend` already applies to one ad's own window -- reused here over however many
    ad-scope rows `aggregated` was built from (one ad, one campaign's every ad, or the whole
    brand's every ad -- this function never knows or cares which)."""
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None, None
    currencies = {s["currency"] for s in entries}
    if len(currencies) > 1:
        return None, None
    return sum(s["metrics"]["spend"] for s in entries), next(iter(currencies))


def _ad_result(aggregated: dict) -> tuple[float | None, float | None, str | None]:
    views = [v for v in aggregated["result_views"] if v["metric_scope"] == "ad"]
    view = views[0] if len(views) == 1 else None
    if view is None:
        return None, None, None
    return view["result_count"], view["cost_per_result"], view["result_kind"]


def _campaign_month_metrics(conn, org_id, brand_id, campaign_id, start, end) -> dict:
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND metric_scope='ad' AND day BETWEEN %s AND %s",
            (org_id, brand_id, campaign_id, start, end),
        ).fetchall()
    ]
    aggregated = review_evidence.aggregate(rows, start, end)
    spend, _currency = _ad_spend_and_currency(aggregated)
    result_count, cost_per_result, result_kind = _ad_result(aggregated)
    return {
        "spend": spend, "result_count": result_count, "cost_per_result": cost_per_result,
        "result_kind": result_kind,
    }


def _brand_month_total(conn, org_id, brand_id, start, end) -> tuple[float | None, str | None]:
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
            "AND metric_scope='ad' AND day BETWEEN %s AND %s",
            (org_id, brand_id, start, end),
        ).fetchall()
    ]
    return _ad_spend_and_currency(review_evidence.aggregate(rows, start, end))


def _verdict(cost_per_result, target_value) -> str:
    if cost_per_result is None or target_value is None:
        return "unjudged"
    return "met" if cost_per_result <= target_value else "missed"


def _campaign_rows(conn, org_id, brand_id) -> list[dict]:
    """Every `origin='imported'` campaign of this brand -- the only campaigns Contract G's own
    `ads_external_daily` grain can ever judge (module docstring). Full rows (not
    `repository.list_campaigns`'s narrowed entries): `targets.resolve` needs `context_json`/
    `target_basis`/`target_cost`/`result_kind`, and the suggestion/dismiss paths below need
    `context_json` back too."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND origin='imported' "
            "ORDER BY created_at DESC",
            (org_id, brand_id),
        ).fetchall()
    ]


def _has_active_ad(conn, org_id, brand_id, campaign_id) -> bool:
    rows = conn.execute(
        "SELECT native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND native_kind='ad'",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return any(not ad_status.is_closed(row["native_status"]) for row in rows)


def _orders_comparison(conn, org_id, brand_id, start, days_elapsed) -> dict | None:
    """Like-for-like: this month so far (the elapsed days of the requested month) vs the same
    number of days of the previous month, capped at the previous month's own length (correction
    6). `None` only when nothing has elapsed yet (a future month) -- there is no "so far" window
    to build at all, never a zero-day call into `orders.review_evidence`."""
    if days_elapsed <= 0:
        return None
    this_end = start + timedelta(days=days_elapsed - 1)
    this_evidence = orders.review_evidence(conn, org_id, brand_id, start=start, end=this_end)
    previous_end_anchor = start - timedelta(days=1)
    previous_start = previous_end_anchor.replace(day=1)
    previous_days_in_month = calendar.monthrange(previous_start.year, previous_start.month)[1]
    previous_span = min(days_elapsed, previous_days_in_month)
    previous_end = previous_start + timedelta(days=previous_span - 1)
    previous_evidence = orders.review_evidence(
        conn, org_id, brand_id, start=previous_start, end=previous_end,
    )
    this_summary = this_evidence["order_summary"]
    previous_summary = previous_evidence["order_summary"]
    this_net = this_summary["order_net_amount"]
    previous_net = previous_summary["order_net_amount"]
    change_pct = (
        (this_net - previous_net) / previous_net
        if this_net is not None and previous_net
        else None
    )
    return {
        "this_net": this_net, "this_count": this_summary["non_void_count"],
        "previous_net": previous_net, "previous_count": previous_summary["non_void_count"],
        "change_pct": change_pct,
    }


def _closed_tracking_since(conn, org_id, brand_id, zone) -> date:
    row = conn.execute(
        "SELECT MIN(status_changed_at) AS since FROM ads_external_entity "
        "WHERE org_id=%s AND brand_id=%s AND native_kind='ad' AND status_changed_at IS NOT NULL",
        (org_id, brand_id),
    ).fetchone()
    since = row["since"] if row else None
    return since.astimezone(zone).date() if since is not None else _TRACKING_FALLBACK


def _closed_this_month(conn, org_id, brand_id, start, end) -> tuple[int | None, date]:
    zone = coresettings.org_timezone(conn, org_id=org_id)
    tracking_since = _closed_tracking_since(conn, org_id, brand_id, zone)
    if start.strftime("%Y-%m") < tracking_since.strftime("%Y-%m"):
        return None, tracking_since
    range_start = datetime.combine(start, time.min, tzinfo=zone)
    range_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
    rows = conn.execute(
        "SELECT native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND native_kind='ad' AND status_changed_at >= %s AND status_changed_at < %s",
        (org_id, brand_id, range_start, range_end),
    ).fetchall()
    return sum(1 for row in rows if ad_status.is_closed(row["native_status"])), tracking_since


def _dismissed_keys(campaign: dict, month: str) -> list:
    return ((campaign.get("context_json") or {}).get("month_dismissed") or {}).get(month) or []


def _refresh_suggestions(campaigns_by_id: dict, queue_items: list, month: str) -> list:
    out = []
    for row in queue_items:
        if row["kind_key"] != "refresh_creative":
            continue
        refresh = row["refresh"]
        campaign = campaigns_by_id.get(refresh["campaign_id"])
        key = f"refresh:{refresh['campaign_id']}"
        if campaign is None or key in _dismissed_keys(campaign, month):
            continue
        needed = max(
            triage_scale.MIN_ACTIVE_ADS_FOR_REFRESH_GATE - refresh["readable_count"], 1
        )
        out.append({
            "key": key, "kind": "refresh", "campaign_id": refresh["campaign_id"],
            "campaign_name": refresh["campaign_name"], "objective": campaign["objective"],
            "campaign_objective": campaign["campaign_objective"],
            "title": f"補 {needed} 則新素材",
            "why": f"有效的方向只剩 {refresh['readable_count']} 則在投",
            "action_url": row["action_url"],
        })
    return out


def _cleanup_suggestions(campaigns_by_id: dict, queue_items: list, month: str) -> list:
    out = []
    for row in queue_items:
        if row["kind_key"] != "cleanup":
            continue
        cleanup = row["cleanup"]
        campaign = campaigns_by_id.get(cleanup["campaign_id"])
        key = f"cleanup:{cleanup['campaign_id']}"
        if campaign is None or key in _dismissed_keys(campaign, month):
            continue
        # F28-I02: the cut is chosen by grade (沒賣出 first, then the most expensive over the cap),
        # no longer the lowest-spend ads -- and a 沒賣出 ad alone raises it even when capacity is
        # unknown (`can_support` null), so the reason names whichever applies.
        can_support = cleanup["can_support"]
        over_capacity = can_support is not None and cleanup["active_ads"] > can_support
        wasted = sum(1 for ad in cleanup["ads"] if ad["grade"] == "wasted")
        out.append({
            "key": key, "kind": "cleanup", "campaign_id": cleanup["campaign_id"],
            "campaign_name": cleanup["campaign_name"], "objective": campaign["objective"],
            "campaign_objective": campaign["campaign_objective"],
            "title": f"關掉 {len(cleanup['ads'])} 則花錢沒效的廣告",
            "why": (
                f"同時 {cleanup['active_ads']} 則，預算約撐 {can_support} 則" if over_capacity
                else f"{wasted} 則花了上限 3 倍以上還沒有成果"
            ),
            "action_url": row["action_url"],
        })
    return out


def _no_target_suggestions(conn, org_id, brand_id, campaigns_rows, target_by_campaign,
                            month) -> list:
    out = []
    for campaign in campaigns_rows:
        if campaign["status"] == "closed":
            continue
        key = f"no_target:{campaign['id']}"
        if key in _dismissed_keys(campaign, month):
            continue
        if target_by_campaign.get(campaign["id"]) is not None:
            continue
        if not _has_active_ad(conn, org_id, brand_id, campaign["id"]):
            continue
        out.append({
            "key": key, "kind": "no_target", "campaign_id": campaign["id"],
            "campaign_name": campaign["name"], "objective": campaign["objective"],
            "campaign_objective": campaign["campaign_objective"],
            "title": f"替「{campaign['name']}」設目標", "why": "沒有目標，系統無法判斷好壞",
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign['id']}/target",
        })
    return out


def _grades_view(conn, org_id, brand_id, start, end) -> dict:
    """Contract C `grades`: every ad that spent this month graded by the one ruler
    (`period_grades.grade_period`, the same rows a settle of this month reads) -- 有效 is the
    `on_target` bucket only (ads.md §6.33)."""
    rows = period_grades.grade_period(conn, org_id, brand_id, start, end)
    return {
        **period_grades.summarize(rows), "rows": rows,
        "missing": period_grades.missing(conn, org_id, brand_id, start, end),
    }


def _dismissed_for(conn, org_id, brand_id, campaigns_by_id: dict, campaign_id: str,
                   month: str) -> list:
    """The month's dismissed keys of any campaign of this brand: `campaigns_by_id` holds the
    imported ones already; a system-built campaign's row is read here (dismissal is stored the
    same way for both, `dismiss_suggestion`)."""
    campaign = campaigns_by_id.get(campaign_id)
    if campaign is None:
        campaign = conn.execute(
            "SELECT context_json FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org_id, brand_id, campaign_id),
        ).fetchone()
    return _dismissed_keys(dict(campaign), month) if campaign is not None else []


def _rejected_view(conn, org_id, brand_id, items, campaigns_by_id: dict, month: str) -> dict:
    """Contract C `rejected`: every remembered decision (Contract B, newest per ad) grouped back by
    the change set it came from. A set with at least one still-active ad whose grade now ranks
    worse than when the user said no is listed in `worse` (those ads only); every other set with a
    still-active remembered ad only counts in `same_count` -- it is not raised again. F29-I15: a
    worse set whose campaign's `cleanup:<campaign_id>` is dismissed for this month (先不要 on the
    card, the same month dismissal the cleanup suggestion uses) is not listed either."""
    memory = triage.decision_memory(conn, org_id, brand_id)
    items_by_entity = {item["entity_id"]: item for item in items}
    by_set = {}
    for entity_id, entry in memory.items():
        item = items_by_entity.get(entity_id)
        if item is None:
            continue  # closed since (or its campaign closed) -- nothing left to decide
        group = by_set.setdefault(entry["change_set_id"], {"entry": entry, "ads": []})
        if triage_capacity.got_worse(entry, item["grade"]):
            group["ads"].append({
                "entity_id": entity_id, "name": item["name"],
                "thumbnail_url": item["thumbnail_url"], "was": entry["grade"], "now": item["grade"],
            })
    worse, same_count = [], 0
    for change_set_id, group in by_set.items():
        entry = group["entry"]
        if not group["ads"]:
            same_count += 1
            continue
        if f"cleanup:{entry['campaign_id']}" in _dismissed_for(
                conn, org_id, brand_id, campaigns_by_id, entry["campaign_id"], month):
            continue
        campaign = items_by_entity[group["ads"][0]["entity_id"]]
        worse.append({
            "change_set_id": change_set_id, "campaign_id": entry["campaign_id"],
            "campaign_name": campaign["campaign_name"], "title": entry["title"],
            "at": entry["at"], "reason": entry["reason"], "ads": group["ads"],
        })
    worse.sort(key=lambda card: card["at"], reverse=True)
    return {"worse": worse, "same_count": same_count}


def get_summary(conn, org_id: str, brand_id: str, month: str) -> dict:
    month = _require_month(month)
    start, end, days_covered, days_elapsed = _month_window(conn, org_id, month)
    campaigns_rows = _campaign_rows(conn, org_id, brand_id)

    campaigns = []
    target_by_campaign = {}
    for row in campaigns_rows:
        metrics = _campaign_month_metrics(conn, org_id, brand_id, row["id"], start, end)
        target_value = targets.resolve(conn, org_id, brand_id, row)["value"]
        target_by_campaign[row["id"]] = target_value
        # F27-I27: one objective-family rule, not two -- the same `repository`.
        # `campaign_objective_family` F27-I09 already added for `CampaignChip` on campaign
        # cards/triage items, reused here (and via `campaigns_by_id` below for the
        # suggestions) instead of the frontend re-guessing it from the raw objective string.
        row["campaign_objective"] = repository.campaign_objective_family(
            conn, org_id, brand_id, row,
        )
        campaigns.append({
            "campaign_id": row["id"], "name": row["name"], "objective": row["objective"],
            "campaign_objective": row["campaign_objective"],
            "spend": metrics["spend"], "result_count": metrics["result_count"],
            "result_label": result_kinds.label(metrics["result_kind"]),
            "cost_per_result": metrics["cost_per_result"], "target": target_value,
            "verdict": _verdict(metrics["cost_per_result"], target_value),
        })

    total_spend, currency = _brand_month_total(conn, org_id, brand_id, start, end)
    orders_view = _orders_comparison(conn, org_id, brand_id, start, days_elapsed)
    closed_this_month, closed_tracking_since = _closed_this_month(
        conn, org_id, brand_id, start, end,
    )

    campaigns_by_id = {row["id"]: row for row in campaigns_rows}
    # One brand classification serves the queue (whose cleanup rows already obey the rejection
    # memory, Contract B) and the `rejected` block.
    brand_items = triage.brand_items(conn, org_id, brand_id)
    queue_items = triage.get_queue(conn, org_id, brand_id, items=brand_items)["items"]
    suggestions = [
        *_refresh_suggestions(campaigns_by_id, queue_items, month),
        *_cleanup_suggestions(campaigns_by_id, queue_items, month),
        *_no_target_suggestions(conn, org_id, brand_id, campaigns_rows, target_by_campaign, month),
    ]

    return {
        "month": month, "currency": currency, "total_spend": total_spend,
        "campaigns": campaigns, "orders": orders_view,
        "closed_this_month": closed_this_month,
        "closed_tracking_since": closed_tracking_since.isoformat(),
        "suggestions": suggestions,
        "days_covered": days_covered, "days_elapsed": days_elapsed,
        "grades": _grades_view(conn, org_id, brand_id, start, end),
        "rejected": _rejected_view(
            conn, org_id, brand_id, brand_items, campaigns_by_id, month,
        ),
    }


def dismiss_suggestion(conn, org_id: str, brand_id: str, month: str, key: str) -> None:
    month = _require_month(month)
    kind, _sep, campaign_id = (key or "").partition(":")
    if kind not in _SUGGESTION_KINDS or not campaign_id:
        raise ValueError("建議代碼無法識別。")
    row = conn.execute(
        "SELECT context_json FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    existing = ((row["context_json"] or {}).get("month_dismissed") or {}).get(month) or []
    if key in existing:
        return
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{month_dismissed}',"
        "COALESCE(context_json->'month_dismissed','{}'::jsonb) || jsonb_build_object(%s::text,"
        "%s::jsonb)) WHERE org_id=%s AND brand_id=%s AND id=%s",
        (month, jsonb([*existing, key]), org_id, brand_id, campaign_id),
    )
    conn.commit()
