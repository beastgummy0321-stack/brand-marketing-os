"""app/ads/triage.py — F18-I02: classify every imported ad of a campaign by program against its
own previous window. Pure reads: no LLM call, no platform write (ARCHITECTURE.md §0 "程式整理，
LLM 判斷"). Platform-neutral (ARCHITECTURE.md §6.14/§6.15, F18 feature Decisions): no platform
literal in this file, no adapter import, no `attribution_key` parsing -- window resolution reuses
`app/ads/external_sync.py::account_reader`, metrics reuse `app/ads/review_evidence.py::aggregate`,
never a second, divergent definition of "known".
"""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ads import (
    ad_status,
    external_sync,
    month_budget,
    repository,
    result_kinds,
    review_evidence,
    runtime_events,
    targets,
    triage_capacity,
    triage_ladder,
    triage_scale,
)
from app.ads.adapters.external import SourceReadError
from app.core import interrupts
from app.core.db import now_utc
from app.core.settings import today_for_org

# F18 discovery §2.3 (2026-09-21 user-confirmed numeric defaults, feature Decisions).
MIN_RESULT_EVENTS = 10
FLAT_BAND = 0.20
STOP_LOSS_SPEND_MULTIPLE = 3
WINDOW_STEPS = (7, 14, 28)
# The widest span any window pair (current + its equal-length previous window) can ever need,
# counting back from `cutoff` -- feeds the single per-campaign read (review fix: N+1 -> one read).
_MAX_LOOKBACK_DAYS = 2 * WINDOW_STEPS[-1] - 1

LABELS = {
    "stop_loss": "停損",
    "worse": "變差",
    "better": "變好",
    "flat": "持平",
    "insufficient": "資料不足",
    "no_target": "尚未設定目標",
}

# F28-I02 (ads.md §6.32), F29-I01 (§6.33 v10 words): every active ad is graded against the
# campaign's one cap T -- 划算 <= T, 偏貴 <= 1.2T, 太貴 > 1.2T, 沒賣出 = spend >= 3T with a known
# zero result, below the sample gate = 剛開始、數字還不夠. `grade_window` below is the one ruler
# (triage and `period_grades.grade_period` both call it); `class` above stays the trend note
# against the previous window and no decision reads it (§6.33 "One ruler").
WATCH_BAND = 1.2
GRADE_LABELS = {
    "on_target": "划算", "watch": "偏貴", "over": "太貴", "wasted": "沒賣出", "no_target": "未判斷",
}
TOO_NEW_LABEL = "剛開始、數字還不夠"
NO_DATA_LABEL = "資料不足"
_TOO_NEW = ("insufficient", TOO_NEW_LABEL)
_NO_DATA = ("insufficient", NO_DATA_LABEL)
_NOT_JUDGED = ("no_target", GRADE_LABELS["no_target"])


def classify(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """F26-I01: judges only ACTIVE ads (`ad_status.is_closed` false, including an unknown/null
    `native_status` -- unknown is never closed) -- a closed ad (paused/deleted/archived/its own
    adset or campaign paused on the platform) is kept and reported through the `closed` block
    below, never judged, never silently dropped (measured cause, feature Decisions "I01": the
    home strip used to read most of its 「資料不足」 count from closed ads)."""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    target = targets.resolve(conn, org_id, brand_id, campaign)
    coverage = _coverage(campaign)
    cutoff = _account_cutoff(conn, org_id, brand_id, campaign_id)
    ads = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind='ad' ORDER BY name,id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    active_ads = [ad for ad in ads if not ad_status.is_closed(ad["native_status"])]
    closed_ads = [ad for ad in ads if ad_status.is_closed(ad["native_status"])]
    entity_ids = [ad["id"] for ad in ads]
    rows_by_entity = defaultdict(list)
    if entity_ids:
        # One read for the whole campaign (review fix: was one query per ad per window step) --
        # every window any ad ever needs (current + its equal-length previous window, up to 28
        # days each) fits inside `[cutoff - _MAX_LOOKBACK_DAYS, cutoff]`. Still reads every ad's
        # rows, closed ones included -- the `closed` block's own numbers (below) reuse this same
        # read, never a second query.
        range_start = cutoff - timedelta(days=_MAX_LOOKBACK_DAYS)
        rows = conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND metric_scope='ad' AND entity_id = ANY(%s) AND day BETWEEN %s AND %s",
            (org_id, brand_id, campaign_id, entity_ids, range_start, cutoff),
        ).fetchall()
        for row in rows:
            rows_by_entity[row["entity_id"]].append(dict(row))
    # F27-I09 Done #7: one campaign_objective lookup for the whole campaign (never per ad) --
    # every ACTIVE ad's own triage item carries the same `campaign_objective` its campaign card
    # would (`repository.campaign_objective_family`, the one function that tells a system-built
    # campaign's Chinese label apart from an imported campaign's own platform objective).
    campaign_objective = repository.campaign_objective_family(conn, org_id, brand_id, campaign)
    items = [
        _classify_ad(dict(ad), campaign["name"], campaign_objective, target, cutoff, coverage,
                      rows_by_entity.get(ad["id"], []))
        for ad in active_ads
    ]
    # F27-I01 Contract A: ladder/history attaches to ACTIVE items only, never `_closed_block`.
    triage_ladder.attach(conn, org_id, brand_id, campaign_id, items)
    # F27-I06 Contract F: capacity is read over the SAME active-ads-only `items` list above --
    # never a second, divergent "active ad" query.
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    capacity = triage_capacity.capacity_view(items, target["value"], owner_by_entity)
    return {
        "window_days": WINDOW_STEPS[-1], "items": items,
        "closed": _closed_block(closed_ads, rows_by_entity, cutoff),
        "data": _data_view(conn, org_id, brand_id, campaign, cutoff, coverage, capacity),
    }


_CLOSED_ITEMS_CAP = 50


def _closed_item(entity, entity_rows, cutoff):
    """One closed ad's own last-window numbers (feature Decisions "I01") -- the SAME widest
    (`WINDOW_STEPS[-1]`-day) window `classify()` reports as its own `window_days`, sliced from the
    campaign-level read `classify()` already fetched (never a second query)."""
    days = WINDOW_STEPS[-1]
    end = cutoff
    start = end - timedelta(days=days - 1)
    view, spend = _ad_window(entity_rows, start, end)
    return {
        "entity_id": entity["id"], "name": entity.get("name"),
        "native_status": entity.get("native_status"), "thumbnail_url": _thumbnail_url(entity),
        "spend": spend, "cost_per_result": view["cost_per_result"] if view else None,
        "result_label": result_kinds.label(view["result_kind"] if view else None),
    }


def _closed_block(closed_ads, rows_by_entity, cutoff):
    """The `closed` block of `classify()`'s result (feature Decisions "I01") -- `paused`/
    `archived` count the two statuses the frontend groups the strip by; every other closed status
    (`DELETED`/`ADSET_PAUSED`/`CAMPAIGN_PAUSED`) falls into `other`, so `paused + archived + other
    == total` always. `items` is capped at `_CLOSED_ITEMS_CAP`, in the same (name, id) order the
    campaign's own ad query already returned; `truncated` tells the frontend there's more than the
    cap without it having to compare lengths itself."""
    paused = archived = other = 0
    for ad in closed_ads:
        status = ad["native_status"]
        if status == "PAUSED":
            paused += 1
        elif status == "ARCHIVED":
            archived += 1
        else:
            other += 1
    items = [
        _closed_item(dict(ad), rows_by_entity.get(ad["id"], []), cutoff)
        for ad in closed_ads[:_CLOSED_ITEMS_CAP]
    ]
    return {
        "paused": paused, "archived": archived, "other": other, "total": len(closed_ads),
        "items": items, "truncated": len(closed_ads) > _CLOSED_ITEMS_CAP,
    }


def _data_view(conn, org_id, brand_id, campaign, cutoff, coverage, capacity):
    """The read-only `data` enrichment (F24-I01, feature Decisions) -- `sync` reuses
    `repository.campaign_sync_state` (same DB-only bound-accounts check `external_repository
    .external_view`'s own `connections` list makes); `coverage`/`missing_days` reuse this same
    call's own `cutoff`/`coverage` (never re-derived), so they can never disagree with what
    `classify()` above actually judged every ad against. `capacity` (F27-I06 Contract F) is passed
    in already computed -- `classify()`'s own `items`/`target` are the source, never re-derived
    here."""
    window_start = cutoff - timedelta(days=WINDOW_STEPS[-1] - 1)
    return {
        "sync": repository.campaign_sync_state(conn, org_id, brand_id, campaign),
        "coverage": (
            {"start": coverage[0].isoformat(), "end": coverage[1].isoformat()}
            if coverage else None
        ),
        "missing_days": _missing_days(coverage, window_start, cutoff),
        "capacity": capacity,
    }


def _missing_days(coverage, start, end):
    """The days of `[start, end]` outside the recorded `coverage` range, oldest first, capped at
    31 (F24-I01, feature Decisions) -- empty when `coverage` is `None` (never synced), since a
    campaign that has never synced says so through `sync.state == "never"`, not a wall of missing
    dates."""
    if coverage is None:
        return []
    coverage_start, coverage_end = coverage
    days = []
    day = start
    while day <= end:
        if day < coverage_start or day > coverage_end:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days[:31]


def _coverage(campaign):
    """This campaign's own recorded `observations` sync coverage (`external_repository
    .record_sync`, written by `external_sync.py::run_sync` when the observations section
    completes cleanly) -- `ads_campaign.context_json->'external_sync'->'observations'->'coverage'`,
    read once per campaign, never a per-ad query. `None` when never synced."""
    sync = (campaign.get("context_json") or {}).get("external_sync") or {}
    coverage = (sync.get("observations") or {}).get("coverage") or {}
    start, end = coverage.get("start"), coverage.get("end")
    if not start or not end:
        return None
    return date.fromisoformat(start), date.fromisoformat(end)


def _window_covered(coverage, start, end):
    """A user can request any <=31-day sync range, so a 28-day judgement window may rest on far
    fewer actually-synced days -- `_result_view` only ever judges rows that exist, so an unsynced
    day would silently read as "no row, so it doesn't count against known days", never surfacing
    as the missing evidence it is (review-arbitrated blocker). `[start, end]` must sit entirely
    inside the recorded coverage range, or this window can't be trusted at all."""
    if coverage is None:
        return False
    coverage_start, coverage_end = coverage
    return start >= coverage_start and end <= coverage_end


def _account_cutoff(conn, org_id, brand_id, campaign_id):
    """Last COMPLETE day in the AD ACCOUNT's own timezone (issue Done #4) -- same guard
    `review_evidence.py::snapshot()` applies for "today is not a complete day", resolved for
    whichever connected account this campaign's entities belong to (`external_sync.account_reader`,
    same seam F18-I01's `external_sync.py::run_sync` uses). Unknown/unreachable account timezone
    fails closed to `today_for_org - 2 days` (review fix: the real-world timezone spread is up to
    ~26h, so "yesterday" alone is not always guaranteed complete)."""
    today = today_for_org(conn, org_id=org_id)
    fallback = today - timedelta(days=2)
    entity = conn.execute(
        "SELECT platform,source_account FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s LIMIT 1",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if entity is None:
        return fallback
    try:
        _, account = external_sync.account_reader(
            conn, org_id, brand_id, entity["platform"], entity["source_account"]
        )
        zone = ZoneInfo(account.get("timezone_name") or "")
    except (SourceReadError, ValueError, ZoneInfoNotFoundError):
        return fallback
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
    rows. Any unknown subgroup, or more than one currency among them, makes the whole window's
    spend unknown -- never an arbitrary pick, never a sum across currencies."""
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None
    if len({s["currency"] for s in entries}) > 1:
        return None
    return sum(s["metrics"]["spend"] for s in entries)


def _ad_window(entity_rows, start, end):
    """`entity_rows` is this ad's own pre-fetched rows for the whole campaign-level lookback
    (`classify()`'s single read) -- sliced here per window, never re-queried."""
    rows = [row for row in entity_rows if start <= row["day"] <= end]
    aggregated = review_evidence.aggregate(rows, start, end)
    ad_views = [v for v in aggregated["result_views"] if v["metric_scope"] == "ad"]
    # More than one currency in the window has no single unambiguous view (same defensive shape
    # `targets._trailing_30` uses) -- treated as unknown, never an arbitrary pick. F29-I01: it is
    # reported as its own `mixed_currency` reason so `grade_window` reads it as 資料不足, never as
    # a thin (剛開始) window or a 0.
    if len(ad_views) > 1:
        return _MIXED_CURRENCY_VIEW, _ad_spend(aggregated)
    view = ad_views[0] if ad_views else None
    return view, _ad_spend(aggregated)


_MIXED_CURRENCY_VIEW = {
    "metric_scope": "ad", "currency": None, "result_kind": None, "result_count": None,
    "cost_per_result": None, "days_present": 0, "days_known": 0, "derived_zero_days": 0,
    "reason": "mixed_currency",
}


def _metrics_view(view, spend):
    if view is None:
        return {
            "spend": spend, "result_count": None, "cost_per_result": None,
            "result_kind": None, "result_label": result_kinds.label(None),
            "derived_zero_days": 0, "reason": "result_unknown_days",
        }
    return {
        "spend": spend, "result_count": view["result_count"],
        "cost_per_result": view["cost_per_result"], "result_kind": view["result_kind"],
        "result_label": result_kinds.label(view["result_kind"]),
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
    days_with_events = (view["days_known"] - view["derived_zero_days"]) if view else 0
    return {"gate": gate, "spend_multiple": spend_multiple, "days_with_events": days_with_events}


def _compare(current_cost, previous_cost):
    """The guarded current-vs-previous comparison (review fix): a falsy current
    `cost_per_result` (0 or, in practice, `None`) is `insufficient`/`below_sample_gate`, never a
    division -- unreachable through `_classify_ad` today only because `STOP_LOSS_SPEND_MULTIPLE`
    and the sample gate's spend clause share the same constant (a known-zero result that passed
    the gate via spend would already have fired stop-loss first, see `_stop_loss_hit`), so this
    guard is kept explicit rather than relying on that coincidence never changing."""
    if not current_cost:
        return "insufficient", "below_sample_gate", None
    change_pct = (current_cost - previous_cost) / previous_cost
    if change_pct > FLAT_BAND:
        return "worse", "cost_per_result_up", change_pct
    if change_pct < -FLAT_BAND:
        return "better", "cost_per_result_down", change_pct
    return "flat", "cost_per_result_flat", change_pct


def _cost_grade(cost, target_value):
    """The grade of a gate-passing, fully known window: 划算 <= T, 偏貴 <= 1.2T, else 太貴. An
    unknown cost (never reached through `_classify_ad` today, kept explicit like `_compare`) is
    資料不足, never a guess."""
    if cost is None:
        return _NO_DATA
    if cost <= target_value:
        grade = "on_target"
    elif cost <= target_value * WATCH_BAND:
        grade = "watch"
    else:
        grade = "over"
    return grade, GRADE_LABELS[grade]


# The graded (ranked) grades -- every other grade key is "not graded" (剛開始／資料不足／未判斷).
GRADED = ("on_target", "watch", "over", "wasted")


def grade_window(view, spend, target_value, days):
    """F29-I01 (ads.md §6.33 "One ruler"): the one cap grade of one window, `(grade, grade_label,
    reason_code)`. Triage (`_classify_ad`, current and previous window) and
    `period_grades.grade_period` both call this -- never a second copy. `reason_code` is `None`
    for a graded cost, `"spend_over_target_no_result"` for 沒賣出, `"below_sample_gate"` for
    剛開始, else the unknown window's own reason (資料不足). No cap is 未判斷.

    Order is the F28 rule: a known zero past 3 × cap first, then the sample gate (spend >= 3 × cap,
    or >= 10 results over >= 7 days), then an unknown window. A window across two currencies has
    no single number to gate on, so it reads 資料不足 before the gate."""
    if target_value is None:
        return (*_NOT_JUDGED, "target_unresolved")
    if view is not None and view["reason"] == "mixed_currency":
        return (*_NO_DATA, "mixed_currency")
    if _stop_loss_hit(view, spend, target_value):
        return "wasted", GRADE_LABELS["wasted"], "spend_over_target_no_result"
    if not _sample_gate(spend, view, target_value, days):
        return (*_TOO_NEW, "below_sample_gate")
    if view is None or view["reason"] is not None:
        return (*_NO_DATA, view["reason"] if view is not None else "result_unknown_days")
    return (*_cost_grade(view["cost_per_result"], target_value), None)


def _grade_move(previous_grade, grade):
    """`{from, to}` only when both windows are graded and the grade changed (Contract A)."""
    if previous_grade in GRADED and grade in GRADED and previous_grade != grade:
        return {"from": previous_grade, "to": grade}
    return None


def _thumbnail_url(entity):
    """This ad's own creative thumbnail, read from the already-loaded `ads_external_entity
    .creative` jsonb -- `creative.fields.thumbnail_url` first, else `.image_url`, else `None`
    (issue Done #1). Same field set `adapters/meta_read.py::creative_summary` writes; no new
    query, no platform branch."""
    fields = (entity.get("creative") or {}).get("fields") or {}
    return fields.get("thumbnail_url") or fields.get("image_url") or None


def _classify_ad(entity, campaign_name, campaign_objective, target, cutoff, coverage, entity_rows):
    base = {
        "entity_id": entity["id"], "native_id": entity["native_id"], "name": entity.get("name"),
        "campaign_id": entity["campaign_id"], "campaign_name": campaign_name,
        "campaign_objective": campaign_objective,
        "thumbnail_url": _thumbnail_url(entity),
    }

    def finish(cls, reason_code, grade, start, end, days, extended_from, view, spend,
               change_pct=None, previous=None):
        previous_start, previous_end = _previous_range(start, days)
        if previous is None:
            previous = _ad_window(entity_rows, previous_start, previous_end)
        prev_view, prev_spend = previous
        gate = _sample_gate(spend, view, target["value"], days)
        # F29-I01 Contract A: the previous equal-length window graded by the same ruler -- null
        # when it isn't fully synced, below the gate or unknown, or when this ad isn't judged.
        previous_grade = None
        if grade[0] != "no_target" and _window_covered(coverage, previous_start, previous_end):
            prev_grade = grade_window(prev_view, prev_spend, target["value"], days)[0]
            previous_grade = prev_grade if prev_grade in GRADED else None
        return {
            **base, "class": cls, "label": LABELS[cls], "reason_code": reason_code,
            "grade": grade[0], "grade_label": grade[1],
            "previous_grade": previous_grade, "grade_move": _grade_move(previous_grade, grade[0]),
            "window": _window_view(start, end, days, extended_from),
            "target": {**target, "result_label": result_kinds.label(target["result_kind"])},
            "current": _metrics_view(view, spend), "previous": _metrics_view(prev_view, prev_spend),
            "change_pct": change_pct,
            "sample": _sample_view(spend, view, target["value"], days, gate),
        }

    if target["value"] is None:
        first_days = WINDOW_STEPS[0]
        first_end = cutoff
        first_start = first_end - timedelta(days=first_days - 1)
        first_view, first_spend = _ad_window(entity_rows, first_start, first_end)
        return finish("no_target", "target_unresolved", _NOT_JUDGED, first_start, first_end,
                      first_days, None, first_view, first_spend)

    days = start = end = view = spend = None
    extended_from = None
    graded = None
    for step_idx, step_days in enumerate(WINDOW_STEPS):
        days = step_days
        end = cutoff
        start = end - timedelta(days=days - 1)
        if not _window_covered(coverage, start, end):
            # Review blocker: an unsynced part of the window must never read as a proven
            # anything. Stop here -- a longer window is covered even less, so extending past a
            # coverage gap can only make the evidence worse, never better.
            view, spend = _ad_window(entity_rows, start, end)
            return finish("insufficient", "needs_resync", _NO_DATA, start, end, days,
                          extended_from, view, spend)
        view, spend = _ad_window(entity_rows, start, end)
        if step_idx == 0 and target["result_kind"] is None                 and (view is None or view["result_kind"] is None):
            return finish("no_target", "result_kind_unknown", _NOT_JUDGED, start, end, days,
                          extended_from, view, spend)
        graded = grade_window(view, spend, target["value"], days)
        if graded[0] == "wasted":
            return finish("stop_loss", graded[2], graded[:2], start, end, days, extended_from,
                          view, spend)
        if graded[2] != "below_sample_gate" or step_idx == len(WINDOW_STEPS) - 1:
            break
        extended_from = days

    if graded[0] not in GRADED:
        return finish("insufficient", graded[2] or "result_unknown_days", graded[:2], start, end,
                      days, extended_from, view, spend)

    # F28-I02: the grade stands on this window alone -- a missing previous window only leaves the
    # trend note (`class`) insufficient, it never blocks the grade.
    grade = graded[:2]
    previous_start, previous_end = _previous_range(start, days)
    if not _window_covered(coverage, previous_start, previous_end):
        return finish("insufficient", "no_previous_window", grade, start, end, days,
                      extended_from, view, spend)
    prev_view, prev_spend = _ad_window(entity_rows, previous_start, previous_end)
    previous = (prev_view, prev_spend)
    # A previous cost_per_result of 0 or None (no previous result known, or known zero results)
    # is never a divisor -- `no_previous_window`, never a ZeroDivisionError.
    if prev_view is None or prev_view["reason"] is not None or not prev_view["cost_per_result"]:
        return finish("insufficient", "no_previous_window", grade, start, end, days,
                      extended_from, view, spend, previous=previous)

    cls, reason_code, change_pct = _compare(view["cost_per_result"], prev_view["cost_per_result"])
    return finish(cls, reason_code, grade, start, end, days, extended_from, view, spend,
                  change_pct=change_pct, previous=previous)


# ---------------------------------------------------------------------------
# F18-I03: brand decision queue over program triage, through the existing `interrupts` inbox.
# ---------------------------------------------------------------------------

# One interrupt category per queue kind (F27-I06: six kinds). F28-I02: `stop_loss` is no longer
# raised -- a 沒賣出 ad closes through its campaign's `cleanup` row -- but its category stays here so
# `_supersede_stale_open_rows` resolves every row still open from before.
QUEUE_CATEGORY = {
    "stop_loss": "ads_triage_stop_loss", "worse": "ads_triage_worse",
    "scale_budget": "ads_triage_scale_budget", "refresh_creative": "ads_triage_refresh_creative",
    "insufficient_data": "ads_triage_insufficient_data", "cleanup": "ads_triage_cleanup",
}
ALL_CLASSES = ("stop_loss", "worse", "better", "flat", "insufficient", "no_target")
KINDS_AVAILABLE = ["worse", "scale_budget", "refresh_creative", "insufficient_data", "cleanup"]
KINDS_PENDING = []
_NAME_BUDGET = 20  # keeps every queue message <= interrupts.MAX_MESSAGE_LEN (10 fixed chars).


def _non_closed_campaign_ids(conn, org_id, brand_id):
    rows = conn.execute(
        "SELECT id FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND status != 'closed'",
        (org_id, brand_id),
    ).fetchall()
    return [row["id"] for row in rows]


def _classify_brand(conn, org_id, brand_id):
    """Every imported ad of every non-closed campaign of this brand, own program triage
    (`classify()`) -- a campaign with no imported ad entities contributes no items on its own."""
    items = []
    for campaign_id in _non_closed_campaign_ids(conn, org_id, brand_id):
        items.extend(classify(conn, org_id, brand_id, campaign_id)["items"])
    return items


def _safe_name(name):
    name = name or "(未命名廣告)"
    return name if len(name) <= _NAME_BUDGET else name[:_NAME_BUDGET - 1] + "…"


def _queue_message(cls, name):
    return f"廣告「{_safe_name(name)}」{LABELS[cls]}，待決定"


def _scale_message(owner_name):
    return f"「{_safe_name(owner_name)}」可加預算，待決定"


def _refresh_message(campaign_name):
    return f"「{_safe_name(campaign_name)}」素材待補，待決定"


def _insufficient_message(campaign_name):
    return f"「{_safe_name(campaign_name)}」資料不足，待處理"


def _cleanup_message(campaign_name):
    # F28-I02: a cleanup now also carries a 沒賣出 ad on a campaign within capacity, so the message
    # names what the row decides (the v9 decision card's own 花錢沒效), not "too many ads".
    return f"「{_safe_name(campaign_name)}」花錢沒效，待決定"


def _dedupe_key(kind, identity_id, window_end):
    # Window end in the key (feature Decisions #3): a resolved decision stays resolved until the
    # window moves on to a new `window_end` -- a fresh dedupe key `interrupts.enqueue` never
    # confuses with the old, resolved-or-not, row. `identity_id`: the ad's `entity_id` for
    # `worse` (and the retired `stop_loss`), the budget owner's `id` for `scale_budget`, the
    # campaign's `id` for `refresh_creative`/`insufficient_data`/`cleanup`.
    return f"ads-triage:{kind}:{identity_id}:{window_end.isoformat()}"


def _classified_items_by_campaign(items):
    by_campaign = defaultdict(list)
    for item in items:
        by_campaign[item["campaign_id"]].append(item)
    return by_campaign


def _month_view_fn(conn, org_id, brand_id):
    """`additional_items -> budget dict`, bound to this brand's current month -- the SAME
    `month_budget.view` seam `preflight()` uses at approve, so a raised row and its own approval
    can never disagree. A callable so tests can stub it without a real month-budget fixture."""
    month = today_for_org(conn, org_id=org_id).strftime("%Y-%m")
    return lambda additional: month_budget.view(
        conn, org_id, brand_id, month, additional=additional
    )


def _campaign_insufficiency(conn, org_id, brand_id, campaign_id):
    """This one campaign's own `data` block plus its name (F26-I01, feature Decisions "I01") --
    reuses `classify()`'s own `_coverage`/`_account_cutoff`/`_data_view` seam, which never touches
    `ads_external_daily` (only the campaign's own `context_json` and its bound account), so this
    stays cheap alongside the per-campaign `classify()` call `_classify_brand` already makes.
    `None` when the campaign no longer exists (defensive -- `_non_closed_campaign_ids` only just
    listed live ids, but nothing here holds that row locked in between)."""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        return None
    coverage = _coverage(campaign)
    cutoff = _account_cutoff(conn, org_id, brand_id, campaign_id)
    # `capacity=None`: this helper only ever reads `missing_days`/`sync`/`coverage` back off
    # `data` (never serialised to a caller as `TriageData` itself) -- computing a real capacity
    # here would need `items`/`target`/an owner lookup this lightweight helper doesn't have.
    data = _data_view(conn, org_id, brand_id, campaign, cutoff, coverage, capacity=None)
    return {"campaign_name": campaign["name"], "data": data, "cutoff": cutoff, "coverage": coverage}


# F27-I09 correction 2: `auth_expired` is a failing-to-sync state exactly like `failed`/
# `disconnected` (a campaign stuck there needs a human to re-authorize before it can ever sync
# again) -- same 「資料不足」 queue row either way.
_SYNC_STATES_RAISING_INSUFFICIENT = {"failed", "disconnected", "auth_expired"}


def _insufficient_candidates(conn, org_id, brand_id, by_campaign) -> list:
    """The campaign-level 「資料不足」 queue row (F26-I01, feature Decisions "I01") -- one
    candidate per non-closed campaign that has at least one ACTIVE ad (`by_campaign` only ever
    carries a campaign whose triage items are active ads, `classify()` no longer judges closed
    ones) whose own `data` block shows `missing_days` non-empty OR `sync.state` failed/
    disconnected. `window_end` is the campaign's own account cutoff (the same date every other
    row's window would extend to on this campaign) -- it moves forward daily, so a resolved row
    stays resolved only until the NEXT day's refresh, same "window moves on" rule every other kind
    already follows. `triage` is the first active ad's own item (`by_campaign`'s own (name, id)
    order, same as `classify()`'s query) -- always present, since the >=1-active-ad gate above
    guarantees a non-empty list."""
    candidates = []
    for campaign_id, campaign_items in by_campaign.items():
        if not campaign_items:
            continue
        info = _campaign_insufficiency(conn, org_id, brand_id, campaign_id)
        if info is None:
            continue
        data = info["data"]
        if not (data["missing_days"] or data["sync"]["state"] in _SYNC_STATES_RAISING_INSUFFICIENT):
            continue
        window_end = info["cutoff"]
        triage_item = campaign_items[0]
        candidates.append({
            "kind": "insufficient_data", "identity_id": campaign_id,
            "window_start": window_end, "window_end": window_end,
            "message": _insufficient_message(info["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}/wait",
            "payload": {
                "triage": triage_item,
                "insufficient": {
                    "campaign_id": campaign_id, "campaign_name": info["campaign_name"],
                    "missing_days": data["missing_days"], "sync_state": data["sync"]["state"],
                    "coverage": data["coverage"],
                },
            },
        })
    return candidates


def _campaign_recent_rows_by_entity(conn, org_id, brand_id, campaign_id, entity_ids, start, end):
    """This campaign's own ad-scope daily rows over `[start, end]`, sliced per entity -- used only
    by `_cleanup_candidates` below (Contract F's own 7-day spend, never `classify()`'s wider
    lookback -- that window belongs to `classify()`'s own per-ad judgement, never re-borrowed
    here)."""
    rows_by_entity = defaultdict(list)
    if not entity_ids:
        return rows_by_entity
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND metric_scope='ad' AND entity_id = ANY(%s) AND day BETWEEN %s AND %s",
        (org_id, brand_id, campaign_id, list(entity_ids), start, end),
    ).fetchall()
    for row in rows:
        rows_by_entity[row["entity_id"]].append(dict(row))
    return rows_by_entity


def _cleanup_candidates(conn, org_id, brand_id, by_campaign, scale_owner_by_campaign) -> list:
    """The cleanup queue row (Contract F, F28-I02 grades) -- one candidate per campaign that has a
    沒賣出 ad, or is over its own capacity (`triage_capacity.capacity_view`) with a 太貴／偏貴 ad to
    close (`triage_capacity.cleanup_candidates`). `owner_lookup` is one brand-wide read shared by
    every campaign here (never per campaign). A campaign whose own trailing 7-day window isn't
    fully synced never raises this row at all. `scale_owner_by_campaign` names the campaign's
    qualifying `scale_budget` owner, echoed while ads stay over capacity after the cut."""
    if not by_campaign:
        return []
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    memory = decision_memory(conn, org_id, brand_id)
    candidates = []
    for campaign_id, campaign_items in by_campaign.items():
        if not campaign_items:
            continue
        info = _campaign_insufficiency(conn, org_id, brand_id, campaign_id)
        if info is None:
            continue
        cutoff, coverage = info["cutoff"], info["coverage"]
        window_start = cutoff - timedelta(days=6)
        if not _window_covered(coverage, window_start, cutoff):
            continue
        target_value = campaign_items[0]["target"].get("value")
        capacity = triage_capacity.capacity_view(campaign_items, target_value, owner_by_entity)
        rows_by_entity = _campaign_recent_rows_by_entity(
            conn, org_id, brand_id, campaign_id,
            {item["entity_id"] for item in campaign_items}, window_start, cutoff,
        )
        cleanup = triage_capacity.cleanup_candidates(
            conn, org_id, brand_id, campaign_id, info["campaign_name"], campaign_items,
            rows_by_entity, cutoff, capacity,
            scale_owner_id=scale_owner_by_campaign.get(campaign_id), memory=memory,
        )
        if cleanup is None:
            continue
        candidates.append({
            "kind": "cleanup", "identity_id": campaign_id,
            "window_start": window_start, "window_end": cutoff,
            "message": _cleanup_message(info["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}"
                          f"/propose/cleanup/{campaign_id}",
            "payload": {"triage": campaign_items[0], "cleanup": cleanup},
        })
    return candidates


def _became_costly(item) -> bool:
    move = item.get("grade_move")
    return move is not None and move["from"] == "on_target" and move["to"] in {"watch", "over"}


def decision_memory(conn, org_id, brand_id) -> dict:
    """F29-I01 Contract B: `triage_capacity.decision_memory` (newest memory per ad) with each
    entry's `grade_label` -- one brand-wide read shared by the cleanup rows and the month review."""
    return {
        entity_id: {**entry, "grade_label": GRADE_LABELS.get(entry["grade"], entry["grade"])}
        for entity_id, entry in triage_capacity.decision_memory(conn, org_id, brand_id).items()
    }


def campaign_cleanup(conn, org_id, brand_id, campaign_id) -> dict | None:
    """The cleanup proposal this campaign's queue row carries right now (`cleanup` payload), or
    `None` -- the same `_cleanup_candidates` path the brand queue uses, over this one campaign
    (`change_control.create` checks `declined_ids` against it)."""
    items = classify(conn, org_id, brand_id, campaign_id)["items"]
    candidates = _cleanup_candidates(conn, org_id, brand_id, {campaign_id: items}, {})
    return candidates[0]["payload"]["cleanup"] if candidates else None


def _queue_candidates(conn, org_id, brand_id, items) -> list:
    """Every row this brand's queue could raise -- qualifying `scale_budget` owners, `cleanup`
    campaigns, one `worse` row per ad whose grade moved from 划算 to 偏貴／太貴 (F29-I01; never
    for an ad already inside its
    campaign's cleanup `ads`, F28-I02), `refresh_creative` campaigns and `insufficient_data`
    campaigns (`triage_scale.py`/`triage_capacity.py`). `stop_loss` rows are no longer raised
    (F28-I02): a 沒賣出 ad closes through its campaign's cleanup row. Each candidate carries its
    `kind`, dedupe identity, window and queue message/action_url, plus the extra payload
    `_queue_payload` attaches to its row."""
    by_campaign = _classified_items_by_campaign(items)
    native_status = _brand_entity_native_status(
        conn, org_id, brand_id, {item["entity_id"] for item in items}
    )
    candidates = []
    scale_owner_by_campaign = {}
    month_view = _month_view_fn(conn, org_id, brand_id)
    for scale in triage_scale.scale_candidates(
        conn, org_id, brand_id, by_campaign, native_status, month_view
    ):
        owner_id = scale["owner_id"]
        scale_owner_by_campaign.setdefault(scale["campaign_id"], owner_id)
        candidates.append({
            "kind": "scale_budget", "identity_id": owner_id,
            "window_start": scale["window_start"], "window_end": scale["window_end"],
            "message": _scale_message(scale["scale"]["owner"]["name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{scale['campaign_id']}/detail"
                          f"?owner={owner_id}",
            "payload": {"triage": scale["triage"], "scale": scale["scale"]},
        })
    cleanup_candidates = _cleanup_candidates(
        conn, org_id, brand_id, by_campaign, scale_owner_by_campaign,
    )
    # An ad inside its campaign's cleanup proposal is decided there -- no second `worse` row.
    in_cleanup = {
        ad["entity_id"] for c in cleanup_candidates for ad in c["payload"]["cleanup"]["ads"]
    }
    for item in items:
        # F29-I01 (ads.md §6.33 "One ruler"): 變貴 is a grade move from 划算 to 偏貴／太貴 -- the
        # trend note (`class`) never raises a row.
        if not _became_costly(item) or item["entity_id"] in in_cleanup:
            continue
        candidates.append({
            "kind": "worse", "identity_id": item["entity_id"],
            "window_start": item["window"]["start"], "window_end": item["window"]["end"],
            "message": _queue_message("worse", item["name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{item['campaign_id']}/detail"
                          f"?ad={item['entity_id']}",
            "payload": {"triage": item},
        })
    # Correction 4: while a campaign has an open cleanup row, its refresh_creative row is not
    # raised (cleanup first) -- `identity_id` is the campaign id for both kinds.
    cleanup_campaign_ids = {c["identity_id"] for c in cleanup_candidates}
    candidates.extend(cleanup_candidates)
    for refresh in triage_scale.refresh_candidates(by_campaign, native_status):
        campaign_id = refresh["campaign_id"]
        if campaign_id in cleanup_campaign_ids:
            continue
        candidates.append({
            "kind": "refresh_creative", "identity_id": campaign_id,
            "window_start": refresh["window_start"], "window_end": refresh["window_end"],
            "message": _refresh_message(refresh["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}"
                          f"?tab=assets&material_new=1",
            "payload": {"triage": refresh["triage"], "refresh": refresh["refresh"]},
        })
    candidates.extend(_insufficient_candidates(conn, org_id, brand_id, by_campaign))
    return candidates


def _supersede_stale_open_rows(conn, org_id, brand_id, live_keys) -> None:
    """Lead review arbitration (2026-09-21, F18-I03 REQUEST_CHANGES): the same `interrupt` table
    feeds the brand home and `/api/inbox`, and auto-archive only covers `informational` severity
    -- a stale open row (superseded by a newer window, or its kind no longer qualifying) would
    otherwise sit open forever and keep inflating `brand_health`. Close every OPEN row of this
    brand in every triage category (`QUEUE_CATEGORY.values()`, six as of F27-I06) whose
    `dedupe_key` is no longer live, through the
    existing public `interrupts.resolve()` -- never a direct UPDATE from `app/ads` (architecture
    boundary). `"system"` actor precedent: `app/llm/methodology.py`. Result: at most one open row
    per (kind, identity) at any time; a user-resolved key is already not 'open', so this loop
    never touches it and never re-raises it."""
    for category in QUEUE_CATEGORY.values():
        stale = [
            row for row in interrupts.list_open(conn, brand_id=brand_id, category=category,
                                                 archive_stale=False)
            if row["dedupe_key"] not in live_keys
        ]
        for row in stale:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org_id)


def refresh_queue(conn, org_id, brand_id) -> dict:
    """`POST .../queue/refresh` (Done #3): classify every non-closed campaign, raise one
    interrupt per queue-worthy row across all four kinds (`_queue_candidates`). One transaction
    -- every enqueue below, then a single commit. Afterward, supersede every open row this
    brand's four triage categories no longer match (`_supersede_stale_open_rows`) -- each call
    its own `resolve()`, not part of the enqueue transaction. The returned payload is read back
    afterward, same shape as `get_queue()`.

    F27-I00 Contract J: also records one `queue_refresh` runtime event for this brand (Contract K's
    recovery step 4, a later F27 issue, reads it back) -- same transaction as the enqueue loop."""
    items = _classify_brand(conn, org_id, brand_id)
    candidates = _queue_candidates(conn, org_id, brand_id, items)
    for candidate in candidates:
        interrupts.enqueue(
            conn, org_id=org_id, brand_id=brand_id, category=QUEUE_CATEGORY[candidate["kind"]],
            dedupe_key=_dedupe_key(candidate["kind"], candidate["identity_id"],
                                    candidate["window_end"]),
            message=candidate["message"], action_url=candidate["action_url"],
        )
    runtime_events.record(conn, "queue_refresh", org_id=org_id, brand_id=brand_id)
    conn.commit()
    live_keys = {
        _dedupe_key(c["kind"], c["identity_id"], c["window_end"]) for c in candidates
    }
    _supersede_stale_open_rows(conn, org_id, brand_id, live_keys)
    return _queue_payload(conn, org_id, brand_id, items, candidates)


def brand_items(conn, org_id, brand_id) -> list:
    """Every active ad's triage item across this brand's non-closed campaigns (`classify()`)."""
    return _classify_brand(conn, org_id, brand_id)


def get_queue(conn, org_id, brand_id, items=None) -> dict:
    """`GET .../queue` (Done #4): read-only, no `resolve()` call here -- `refresh_queue()` is the
    only place that supersedes stale rows (it may not have run yet since the last classification
    change). Current classification decides which open interrupt rows are still live: an older
    window's open row whose kind no longer qualifies (e.g. an ad now flat, or an owner's ads no
    longer all stable) is filtered out of this payload the same way, without writing anything.
    Each listed row carries the current triage item that produced it (F19-I01, `_queue_payload`).
    `items` lets a caller that already classified the brand (`month_summary`) skip a second pass."""
    items = _classify_brand(conn, org_id, brand_id) if items is None else items
    candidates = _queue_candidates(conn, org_id, brand_id, items)
    return _queue_payload(conn, org_id, brand_id, items, candidates)


# ---------------------------------------------------------------------------
# F23-I01/F25-I01/F27-I06: each queue row's own `proposal`, per the "Queue row state" rule
# (feature Decisions) -- on a `worse` row, the matching `ads_review_round` (if any), plus its own
# copy change set when one exists; on a `scale_budget`/`cleanup` row, the matching change set.
# F28-I02 removed the `stop_loss` row's pause proposal together with the row itself. Read-only,
# brand-wide (one query for every non-superseded change set, one for every `ads_action`
# verification_state, one for every review round) -- never per row.
# ---------------------------------------------------------------------------


def _brand_change_sets_by_campaign(conn, org_id, brand_id) -> dict:
    """Every non-superseded change set of this brand, newest (`created_at`) first -- one query
    for the whole brand. Grouped by `campaign_id` in Python; the SQL-level `ORDER BY created_at
    DESC` is preserved inside each campaign's own sublist (stable grouping), so "the newest
    change set of the row's campaign" is just "the first match found while walking that list"."""
    rows = conn.execute(
        "SELECT id,campaign_id,status,plan_json,decision_reason,revisit_at,created_at,"
        "decision_grades FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND status != 'superseded' "
        "ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    by_campaign = defaultdict(list)
    for row in rows:
        by_campaign[row["campaign_id"]].append(dict(row))
    return by_campaign


def _brand_action_verification_states(conn, org_id, brand_id) -> dict:
    """`ads_action.id -> verification_state` for this whole brand -- one query. A change-set
    item with no matching row here has never been approved, so it reads back `data.get()`'s own
    default of `"pending"` at the call site, not here."""
    rows = conn.execute(
        "SELECT id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s",
        (org_id, brand_id),
    ).fetchall()
    return {row["id"]: row["verification_state"] for row in rows}


def _brand_entity_native_status(conn, org_id, brand_id, entity_ids) -> dict:
    """`ads_external_entity.id -> native_status` for exactly the entities this refresh might need
    it for (`triage_scale`'s active-ad filter) -- one bounded query, never per row."""
    if not entity_ids:
        return {}
    rows = conn.execute(
        "SELECT id,native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND id = ANY(%s)",
        (org_id, brand_id, list(entity_ids)),
    ).fetchall()
    return {row["id"]: row["native_status"] for row in rows}


def _brand_review_rounds(conn, org_id, brand_id) -> dict:
    """Every `ads_review_round` of this brand, newest (`created_at`) first -- one query for the
    whole brand (F23-I01 Done #1, same shape as `_brand_change_sets_by_campaign`). Grouped by
    `(campaign_id, entity_id)` in Python; the SQL-level `ORDER BY created_at DESC` is preserved
    inside each group, so "the newest round of this entity" is the first match while walking it."""
    rows = conn.execute(
        "SELECT id,campaign_id,entity_id,window_end,status,decision,reason,revisit_at,result_json "
        "FROM ads_review_round WHERE org_id=%s AND brand_id=%s ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    by_entity = defaultdict(list)
    for row in rows:
        by_entity[(row["campaign_id"], row["entity_id"])].append(dict(row))
    return by_entity


def _matching_review_round(rounds_by_entity, campaign_id, entity_id, window):
    """The newest round of this entity whose own `window_end` still lies inside the row's
    CURRENT triage window (feature Decisions "Queue row state") -- the window's own `end` moves
    forward every day (`triage.py:120,264`), so an exact `window_end == window["end"]` match would
    lose the round the very next morning; `None` when no round's `window_end` falls in range."""
    for round_ in rounds_by_entity.get((campaign_id, entity_id), ()):
        if window["start"] <= round_["window_end"] <= window["end"]:
            return round_
    return None


def _matching_review_change_set(sets_by_campaign, campaign_id, review_id):
    """The newest non-superseded change set of `campaign_id` whose own `plan_json.review_id`
    matches this round (`change_control.py::create` stores it flat, never nested -- see
    `plan_json->>'review_id'` reused the same way by `review_evidence.py:276`) -- `None` when
    there isn't one."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        if change_set["plan_json"].get("review_id") == review_id:
            return change_set
    return None


def _first_adjust_recommendation_id(result_json):
    for recommendation in (result_json or {}).get("recommendations", ()):
        if recommendation.get("recommendation") == "adjust":
            return recommendation.get("id")
    return None


def _row_review_proposal(rounds_by_entity, sets_by_campaign, action_states, triage_item):
    """The `proposal` for one `worse` row (F23-I01, feature Decisions "Queue row state") -- the
    newest `ads_review_round` of this entity whose `window_end` lies inside the row's current
    triage window, or `None` when there is none. The optional copy change set is the newest
    non-superseded set whose `plan_json.review_id` names this round; its `verification_state`
    reads back the matching `copy` item targeting this same entity (reusing the F22 brand-wide
    `sets_by_campaign`/`action_states` maps, never a fresh query per row)."""
    campaign_id, entity_id = triage_item["campaign_id"], triage_item["entity_id"]
    round_ = _matching_review_round(rounds_by_entity, campaign_id, entity_id, triage_item["window"])
    if round_ is None:
        return None
    change_set = _matching_review_change_set(sets_by_campaign, campaign_id, round_["id"])
    change_set_id = change_set_status = verification_state = None
    multi = False
    if change_set is not None:
        items = change_set["plan_json"].get("items", ())
        item = next(
            (i for i in items if i.get("kind") == "copy" and i.get("target_id") == entity_id),
            None,
        )
        change_set_id = change_set["id"]
        change_set_status = change_set["status"]
        verification_state = action_states.get(item["id"], "pending") if item else "pending"
        multi = len(items) > 1
    return {
        "kind": "review",
        "review_id": round_["id"],
        "status": round_["status"],
        "decision": round_["decision"],
        "reason": round_["reason"],
        "revisit_at": round_["revisit_at"],
        "recommendation_id": _first_adjust_recommendation_id(round_["result_json"]),
        "change_set_id": change_set_id,
        "change_set_status": change_set_status,
        "verification_state": verification_state,
        "multi": multi,
    }


def _matching_change_item(sets_by_campaign, campaign_id, target_id, kind):
    """The newest non-superseded change set of `campaign_id` whose items include a `kind` item
    targeting `target_id`, and that item itself -- `None, None` when there isn't one. Generalised
    by `kind` (F25-I01); since F28-I02 only the `scale_budget` row's budget match
    (`kind="budget"`, the budget owner's `id`) walks it."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        item = next(
            (i for i in change_set["plan_json"].get("items", ())
             if i.get("kind") == kind and i.get("target_id") == target_id),
            None,
        )
        if item is not None:
            return change_set, item
    return None, None


def _row_scale_proposal(sets_by_campaign, action_states, candidate):
    """The `proposal` for one `scale_budget` row (feature Decisions "Queue payload") -- the
    newest non-superseded change set whose items include a `budget` item targeting this owner,
    (reuses `_matching_change_item`); `None` when there is no matching set, or a `deferred` set
    past its own `revisit_at`, or a `rejected` set whose `created_at` day has fallen outside this
    row's current window."""
    triage_item = candidate["payload"]["triage"]
    change_set, matched_item = _matching_change_item(
        sets_by_campaign, triage_item["campaign_id"], candidate["identity_id"], kind="budget",
    )
    if change_set is None or matched_item is None:
        return None
    verification_state = action_states.get(matched_item["id"], "pending")
    if change_set["status"] == "deferred":
        revisit_at = change_set["revisit_at"]
        if revisit_at is not None and revisit_at <= now_utc():
            return None
    elif change_set["status"] == "rejected":
        created_day = change_set["created_at"].date()
        if not (candidate["window_start"] <= created_day <= candidate["window_end"]):
            return None
    return {
        "change_set_id": change_set["id"], "campaign_id": change_set["campaign_id"],
        "kind": matched_item["kind"], "status": change_set["status"],
        "verification_state": verification_state, "reason": change_set["decision_reason"],
        "revisit_at": change_set["revisit_at"],
        "multi": len(change_set["plan_json"].get("items", ())) > 1,
    }


def _matching_cleanup_set(sets_by_campaign, campaign_id):
    """The newest non-superseded change set of `campaign_id` whose `plan_json.source == "cleanup"`
    and that carries at least one `pause` item -- Contract F's own proposal match, never generalised
    through `_matching_change_item` (that helper matches by a single `target_id`; a cleanup set's
    own identity is the campaign, not one ad)."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        if change_set["plan_json"].get("source") != "cleanup":
            continue
        pause_items = [
            i for i in change_set["plan_json"].get("items", ()) if i.get("kind") == "pause"
        ]
        if pause_items:
            return change_set, pause_items
    return None, None


def _row_cleanup_proposal(sets_by_campaign, action_states, candidate):
    """The `proposal` for one `cleanup` row (Contract F) -- same shape `_row_scale_proposal`
    reports, `kind` always `"cleanup"` and `multi` always `True`
    (a cleanup set is inherently the multi-item kind, never computed from item count). A cleanup
    set carries several `pause` items (one per proposed ad); `verification_state` reads
    `"confirmed"` only once every one of them does, else the first item's own state that isn't
    (same "worst state wins" aggregate `handoff_check.py::_finish` uses for one action's own
    multi-handoff readback)."""
    change_set, pause_items = _matching_cleanup_set(sets_by_campaign, candidate["identity_id"])
    if change_set is None or pause_items is None:
        return None
    states = [action_states.get(item["id"], "pending") for item in pause_items]
    verification_state = (
        "confirmed" if all(s == "confirmed" for s in states)
        else next((s for s in states if s != "confirmed"), "pending")
    )
    if change_set["status"] == "deferred":
        revisit_at = change_set["revisit_at"]
        if revisit_at is not None and revisit_at <= now_utc():
            return None
    elif change_set["status"] == "rejected":
        # F29-I01 Contract B: a rejection that left a memory is owned by that memory -- a row
        # raised again (an ad got worse, or a different ad is now proposed) is a fresh proposal.
        # A legacy rejection (no memory) keeps the window rule.
        if change_set.get("decision_grades") is not None:
            return None
        created_day = change_set["created_at"].date()
        if not (candidate["window_start"] <= created_day <= candidate["window_end"]):
            return None
    elif verification_state == "confirmed":
        # F28-I02: carried over from the retired stop-loss proposal -- a confirmed pause whose ad
        # is active again (it is back in this row's close list, and `classify()` only judges
        # active ads) needs a fresh proposal, never the old "done" one. F29-I01: same for an ad
        # the user unticked in that set that has since got worse (it re-entered the close list).
        closing = {ad["entity_id"] for ad in candidate["payload"]["cleanup"]["ads"]}
        declined = set(change_set["plan_json"].get("declined_ids") or ())
        if any(item.get("target_id") in closing for item in pause_items) or closing & declined:
            return None
    return {
        "change_set_id": change_set["id"], "campaign_id": change_set["campaign_id"],
        "kind": "cleanup", "status": change_set["status"],
        "verification_state": verification_state, "reason": change_set["decision_reason"],
        "revisit_at": change_set["revisit_at"], "multi": True,
    }


def _trend_counts(items) -> dict:
    """The trend-note tally (`counts`, one per `class`) -- the only reader of `class` outside the
    note builder `_classify_ad`, display only; no decision reads it (ads.md §6.33, enforced by
    `app/tests/test_ads_one_ruler.py`)."""
    counts = dict.fromkeys(ALL_CLASSES, 0)
    for item in items:
        counts[item["class"]] += 1
    return counts


def _queue_payload(conn, org_id, brand_id, items, candidates) -> dict:
    # F19-I01/F25-I01: each open row's own triage item (and, for `scale_budget`/`refresh_creative`
    # rows, their own extra `scale`/`refresh` payload), keyed by the same dedupe key the enqueue
    # used -- the frontend never parses `dedupe_key` strings itself. Every candidate produces a
    # key (see `_queue_candidates`), so this doubles as the "still live" filter below.
    candidates_by_key = {
        _dedupe_key(c["kind"], c["identity_id"], c["window_end"]): c for c in candidates
    }
    queue_categories = set(QUEUE_CATEGORY.values())
    # archive_stale=False: this is a read inside a read-only path too (`get_queue`), and
    # `refresh_queue` already committed its own writes above -- neither call should also trigger
    # the unrelated informational-archival side effect of `list_open(archive_stale=True)`.
    rows = [
        row
        for row in interrupts.list_open(conn, brand_id=brand_id, archive_stale=False)
        if row["category"] in queue_categories and row["dedupe_key"] in candidates_by_key
    ]
    sets_by_campaign = _brand_change_sets_by_campaign(conn, org_id, brand_id)
    action_states = _brand_action_verification_states(conn, org_id, brand_id)
    # F23-I01: `worse` rows' own proposal -- the matching review round (if any), brand-wide.
    rounds_by_entity = _brand_review_rounds(conn, org_id, brand_id)
    open_rows = []
    for row in rows:
        candidate = candidates_by_key[row["dedupe_key"]]
        kind = candidate["kind"]
        triage_item = candidate["payload"]["triage"]
        if kind == "worse":
            proposal = _row_review_proposal(
                rounds_by_entity, sets_by_campaign, action_states, triage_item
            )
        elif kind == "scale_budget":
            proposal = _row_scale_proposal(sets_by_campaign, action_states, candidate)
        elif kind == "cleanup":
            proposal = _row_cleanup_proposal(sets_by_campaign, action_states, candidate)
        else:
            # refresh_creative/insufficient_data: no change set -- the row's own button goes
            # elsewhere (the workbench / the F24 wait page) instead.
            proposal = None
        extra = {k: v for k, v in candidate["payload"].items() if k != "triage"}
        open_rows.append({
            **row, "kind_key": kind, "triage": triage_item, **extra, "proposal": proposal,
        })
    return {
        "items": open_rows, "counts": _trend_counts(items), "total_ads": len(items),
        "kinds_available": KINDS_AVAILABLE, "kinds_pending": KINDS_PENDING,
    }
