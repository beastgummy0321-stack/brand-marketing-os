"""app/ads/triage.py — F18-I02: classify every imported ad of a campaign by program against its
own previous window. Pure reads: no LLM call, no platform write (ARCHITECTURE.md §0 "程式整理，
LLM 判斷"). Platform-neutral (ARCHITECTURE.md §6.14/§6.15, F18 feature Decisions): no platform
literal in this file, no adapter import, no `attribution_key` parsing -- window resolution reuses
`app/ads/external_sync.py::account_reader`, metrics reuse `app/ads/review_evidence.py::aggregate`,
never a second, divergent definition of "known".
"""

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ads import external_sync, repository, review_evidence, targets
from app.ads.adapters.external import SourceReadError
from app.core.db import now_utc
from app.core.settings import today_for_org

# F18 discovery §2.3 (2026-09-21 user-confirmed numeric defaults, feature Decisions).
MIN_RESULT_EVENTS = 10
OBSERVATION_WINDOW_DAYS = 28
FLAT_BAND = 0.20
STOP_LOSS_SPEND_MULTIPLE = 3
WINDOW_STEPS = (7, 14, 28)

LABELS = {
    "stop_loss": "停損",
    "worse": "變差",
    "better": "變好",
    "flat": "持平",
    "insufficient": "資料不足",
    "no_target": "尚未設定目標",
}


def classify(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    target = targets.resolve(conn, org_id, brand_id, campaign)
    cutoff = _account_cutoff(conn, org_id, brand_id, campaign_id)
    ads = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind='ad' ORDER BY name,id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    items = [_classify_ad(conn, org_id, brand_id, campaign_id, dict(ad), target, cutoff)
             for ad in ads]
    return {"window_days": WINDOW_STEPS[-1], "items": items}


def _account_cutoff(conn, org_id, brand_id, campaign_id):
    """Last COMPLETE day in the AD ACCOUNT's own timezone (issue Done #4) -- same guard
    `review_evidence.py::snapshot()` applies for "today is not a complete day", resolved for
    whichever connected account this campaign's entities belong to (`external_sync.account_reader`,
    same seam F18-I01's `external_sync.py::run_sync` uses). Unknown/unreachable account timezone
    falls back to `today_for_org - 1 day`."""
    today = today_for_org(conn, org_id=org_id)
    entity = conn.execute(
        "SELECT platform,source_account FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s LIMIT 1",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if entity is None:
        return today - timedelta(days=1)
    try:
        _, account = external_sync.account_reader(
            conn, org_id, brand_id, entity["platform"], entity["source_account"]
        )
        zone = ZoneInfo(account.get("timezone_name") or "")
    except (SourceReadError, ValueError, ZoneInfoNotFoundError):
        return today - timedelta(days=1)
    return (now_utc().astimezone(zone) - timedelta(days=1)).date()


def _previous_range(start, days):
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return previous_start, previous_end


def _window_view(start, end, days, extended_from):
    previous_start, previous_end = _previous_range(start, days)
    return {
        "start": start, "end": end, "days": days,
        "previous_start": previous_start, "previous_end": previous_end,
        "extended_from": extended_from,
    }


def _ad_spend(aggregated):
    """This ad's own known spend, summed across every `attribution_key` subgroup of its 'ad'
    scope -- reuses `aggregate()`'s own per-subgroup `metrics["spend"]` (already NULL-aware,
    F16-I06's completeness rule) rather than a second, divergent "known" predicate over the raw
    rows. Any unknown subgroup makes the whole window's spend unknown, matching the same
    completeness bar `review_evidence._result_view` uses for its own `reason`."""
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None
    return sum(s["metrics"]["spend"] for s in entries)


def _ad_window(conn, org_id, brand_id, campaign_id, entity_id, start, end):
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND entity_id=%s AND metric_scope='ad' AND day BETWEEN %s AND %s",
        (org_id, brand_id, campaign_id, entity_id, start, end),
    ).fetchall()
    aggregated = review_evidence.aggregate([dict(r) for r in rows], start, end)
    ad_views = [v for v in aggregated["result_views"] if v["metric_scope"] == "ad"]
    # More than one currency in the window has no single unambiguous view (same defensive shape
    # `targets._trailing_30` uses) -- treated as unknown, never an arbitrary pick.
    view = ad_views[0] if len(ad_views) == 1 else None
    return view, _ad_spend(aggregated)


def _metrics_view(view, spend):
    if view is None:
        return {
            "spend": spend, "result_count": None, "cost_per_result": None,
            "result_kind": None, "derived_zero_days": 0, "reason": "result_unknown_days",
        }
    return {
        "spend": spend, "result_count": view["result_count"],
        "cost_per_result": view["cost_per_result"], "result_kind": view["result_kind"],
        "derived_zero_days": view["derived_zero_days"], "reason": view["reason"],
    }


def _sample_gate(spend, view, target_value, days):
    if spend is not None and target_value is not None \
            and spend >= STOP_LOSS_SPEND_MULTIPLE * target_value:
        return True
    result_count = view["result_count"] if view else None
    return days >= WINDOW_STEPS[0] and result_count is not None \
        and result_count >= MIN_RESULT_EVENTS


def _stop_loss_hit(view, spend, target_value):
    # A KNOWN zero only -- an unknown/mixed window (`view["reason"] is not None`) or unknown
    # spend must never read as a stop-loss (design caution, review-arbitrated).
    if spend is None or target_value is None or view is None or view["reason"] is not None:
        return False
    return spend >= STOP_LOSS_SPEND_MULTIPLE * target_value and view["result_count"] == 0


def _sample_view(spend, view, target_value, days, gate):
    spend_multiple = spend / target_value if spend is not None and target_value else None
    return {
        "gate": gate, "spend_multiple": spend_multiple,
        "days_with_events": view["days_known"] if view else 0,
    }


def _classify_ad(conn, org_id, brand_id, campaign_id, entity, target, cutoff):
    base = {
        "entity_id": entity["id"], "native_id": entity["native_id"], "name": entity.get("name"),
        "campaign_id": campaign_id,
    }

    def finish(cls, reason_code, start, end, days, extended_from, view, spend, change_pct=None,
               previous=None):
        if previous is None:
            previous_start, previous_end = _previous_range(start, days)
            previous = _ad_window(
                conn, org_id, brand_id, campaign_id, entity["id"], previous_start, previous_end,
            )
        prev_view, prev_spend = previous
        gate = _sample_gate(spend, view, target["value"], days)
        return {
            **base, "class": cls, "label": LABELS[cls], "reason_code": reason_code,
            "window": _window_view(start, end, days, extended_from), "target": target,
            "current": _metrics_view(view, spend), "previous": _metrics_view(prev_view, prev_spend),
            "change_pct": change_pct,
            "sample": _sample_view(spend, view, target["value"], days, gate),
        }

    first_days = WINDOW_STEPS[0]
    first_end = cutoff
    first_start = first_end - timedelta(days=first_days - 1)
    first_view, first_spend = _ad_window(
        conn, org_id, brand_id, campaign_id, entity["id"], first_start, first_end,
    )

    if target["value"] is None:
        return finish("no_target", "target_unresolved", first_start, first_end, first_days, None,
                      first_view, first_spend)
    if target["result_kind"] is None and (first_view is None or first_view["result_kind"] is None):
        return finish("no_target", "result_kind_unknown", first_start, first_end, first_days, None,
                      first_view, first_spend)

    days, start, end, view, spend = first_days, first_start, first_end, first_view, first_spend
    extended_from = None
    gate_pass = False
    for step_idx, step_days in enumerate(WINDOW_STEPS):
        if step_idx > 0:
            days = step_days
            end = cutoff
            start = end - timedelta(days=days - 1)
            view, spend = _ad_window(conn, org_id, brand_id, campaign_id, entity["id"], start, end)
        if _stop_loss_hit(view, spend, target["value"]):
            return finish("stop_loss", "spend_over_target_no_result", start, end, days,
                          extended_from, view, spend)
        gate_pass = _sample_gate(spend, view, target["value"], days)
        if gate_pass or step_idx == len(WINDOW_STEPS) - 1:
            break
        extended_from = days

    if not gate_pass:
        return finish("insufficient", "below_sample_gate", start, end, days, extended_from,
                      view, spend)
    if view is None or view["reason"] is not None:
        reason = view["reason"] if view is not None else "result_unknown_days"
        return finish("insufficient", reason, start, end, days, extended_from, view, spend)

    previous_start, previous_end = _previous_range(start, days)
    prev_view, prev_spend = _ad_window(
        conn, org_id, brand_id, campaign_id, entity["id"], previous_start, previous_end,
    )
    previous = (prev_view, prev_spend)
    # A previous cost_per_result of 0 or None (no previous result known, or known zero results)
    # is never a divisor -- `no_previous_window`, never a ZeroDivisionError.
    if prev_view is None or prev_view["reason"] is not None or not prev_view["cost_per_result"]:
        return finish("insufficient", "no_previous_window", start, end, days, extended_from,
                      view, spend, previous=previous)

    change_pct = (
        (view["cost_per_result"] - prev_view["cost_per_result"]) / prev_view["cost_per_result"]
    )
    if change_pct > FLAT_BAND:
        cls, reason_code = "worse", "cost_per_result_up"
    elif change_pct < -FLAT_BAND:
        cls, reason_code = "better", "cost_per_result_down"
    else:
        cls, reason_code = "flat", "cost_per_result_flat"
    return finish(cls, reason_code, start, end, days, extended_from, view, spend,
                  change_pct=change_pct, previous=previous)
