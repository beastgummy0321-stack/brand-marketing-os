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

from app.ads import external_sync, repository, result_kinds, review_evidence, targets
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


def classify(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
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
    entity_ids = [ad["id"] for ad in ads]
    rows_by_entity = defaultdict(list)
    if entity_ids:
        # One read for the whole campaign (review fix: was one query per ad per window step) --
        # every window any ad ever needs (current + its equal-length previous window, up to 28
        # days each) fits inside `[cutoff - _MAX_LOOKBACK_DAYS, cutoff]`.
        range_start = cutoff - timedelta(days=_MAX_LOOKBACK_DAYS)
        rows = conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND metric_scope='ad' AND entity_id = ANY(%s) AND day BETWEEN %s AND %s",
            (org_id, brand_id, campaign_id, entity_ids, range_start, cutoff),
        ).fetchall()
        for row in rows:
            rows_by_entity[row["entity_id"]].append(dict(row))
    items = [
        _classify_ad(dict(ad), campaign["name"], target, cutoff, coverage,
                      rows_by_entity.get(ad["id"], []))
        for ad in ads
    ]
    return {"window_days": WINDOW_STEPS[-1], "items": items}


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
    # `targets._trailing_30` uses) -- treated as unknown, never an arbitrary pick.
    view = ad_views[0] if len(ad_views) == 1 else None
    return view, _ad_spend(aggregated)


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


def _thumbnail_url(entity):
    """This ad's own creative thumbnail, read from the already-loaded `ads_external_entity
    .creative` jsonb -- `creative.fields.thumbnail_url` first, else `.image_url`, else `None`
    (issue Done #1). Same field set `adapters/meta_read.py::creative_summary` writes; no new
    query, no platform branch."""
    fields = (entity.get("creative") or {}).get("fields") or {}
    return fields.get("thumbnail_url") or fields.get("image_url") or None


def _classify_ad(entity, campaign_name, target, cutoff, coverage, entity_rows):
    base = {
        "entity_id": entity["id"], "native_id": entity["native_id"], "name": entity.get("name"),
        "campaign_id": entity["campaign_id"], "campaign_name": campaign_name,
        "thumbnail_url": _thumbnail_url(entity),
    }

    def finish(cls, reason_code, start, end, days, extended_from, view, spend, change_pct=None,
               previous=None):
        if previous is None:
            previous_start, previous_end = _previous_range(start, days)
            previous = _ad_window(entity_rows, previous_start, previous_end)
        prev_view, prev_spend = previous
        gate = _sample_gate(spend, view, target["value"], days)
        return {
            **base, "class": cls, "label": LABELS[cls], "reason_code": reason_code,
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
        return finish("no_target", "target_unresolved", first_start, first_end, first_days, None,
                      first_view, first_spend)

    days = start = end = view = spend = None
    extended_from = None
    gate_pass = False
    for step_idx, step_days in enumerate(WINDOW_STEPS):
        days = step_days
        end = cutoff
        start = end - timedelta(days=days - 1)
        if not _window_covered(coverage, start, end):
            # Review blocker: an unsynced part of the window must never read as a proven
            # anything. Stop here -- a longer window is covered even less, so extending past a
            # coverage gap can only make the evidence worse, never better.
            view, spend = _ad_window(entity_rows, start, end)
            return finish("insufficient", "needs_resync", start, end, days, extended_from,
                          view, spend)
        view, spend = _ad_window(entity_rows, start, end)
        if step_idx == 0 and target["result_kind"] is None \
                and (view is None or view["result_kind"] is None):
            return finish("no_target", "result_kind_unknown", start, end, days, extended_from,
                          view, spend)
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
    if not _window_covered(coverage, previous_start, previous_end):
        return finish("insufficient", "no_previous_window", start, end, days, extended_from,
                      view, spend)
    prev_view, prev_spend = _ad_window(entity_rows, previous_start, previous_end)
    previous = (prev_view, prev_spend)
    # A previous cost_per_result of 0 or None (no previous result known, or known zero results)
    # is never a divisor -- `no_previous_window`, never a ZeroDivisionError.
    if prev_view is None or prev_view["reason"] is not None or not prev_view["cost_per_result"]:
        return finish("insufficient", "no_previous_window", start, end, days, extended_from,
                      view, spend, previous=previous)

    cls, reason_code, change_pct = _compare(view["cost_per_result"], prev_view["cost_per_result"])
    return finish(cls, reason_code, start, end, days, extended_from, view, spend,
                  change_pct=change_pct, previous=previous)


# ---------------------------------------------------------------------------
# F18-I03: brand decision queue over program triage, through the existing `interrupts` inbox.
# ---------------------------------------------------------------------------

# One category per class this batch actually surfaces (feature Decisions: "scale_budget" and
# "refresh_creative" are reported as pending, never queued -- no interrupts.py entry for them).
QUEUE_CATEGORY = {"stop_loss": "ads_triage_stop_loss", "worse": "ads_triage_worse"}
ALL_CLASSES = ("stop_loss", "worse", "better", "flat", "insufficient", "no_target")
KINDS_AVAILABLE = ["stop_loss", "worse"]
KINDS_PENDING = ["scale_budget", "refresh_creative"]
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


def _dedupe_key(cls, entity_id, window_end):
    # Window end in the key (feature Decisions #3): a resolved decision stays resolved until the
    # window moves on to a new `window_end`, which is a new dedupe key and a fresh open row --
    # `interrupts.enqueue`'s own dedupe check finds the OLD row by key and status, resolved or
    # not, and never reopens or duplicates it (see `interrupts.py::enqueue`, no change needed
    # there beyond the two registered categories above).
    return f"ads-triage:{cls}:{entity_id}:{window_end.isoformat()}"


def _live_keys(items) -> set:
    return {
        _dedupe_key(item["class"], item["entity_id"], item["window"]["end"])
        for item in items if item["class"] in QUEUE_CATEGORY
    }


def _supersede_stale_open_rows(conn, org_id, brand_id, live_keys) -> None:
    """Lead review arbitration (2026-09-21, F18-I03 REQUEST_CHANGES): the same `interrupt` table
    feeds the brand home and `/api/inbox`, and auto-archive only covers `informational` severity
    -- a stale open `stop_loss`/`worse` row (superseded by a newer window, or the ad moved off
    both classes) would otherwise sit open forever and keep inflating `brand_health`. Close every
    OPEN row of this brand in the two triage categories whose `dedupe_key` is no longer live,
    through the existing public `interrupts.resolve()` -- never a direct UPDATE from `app/ads`
    (architecture boundary). `"system"` actor precedent: `app/llm/methodology.py`. Result: at
    most one open row per (class, entity) at any time; a user-resolved key is already not
    'open', so this loop never touches it and never re-raises it."""
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
    interrupt per `stop_loss`/`worse` ad. One transaction -- every enqueue below, then a single
    commit. Afterward, supersede every open row this brand's two triage categories no longer
    match (`_supersede_stale_open_rows`) -- each call its own `resolve()`, not part of the enqueue
    transaction. The returned payload is read back afterward, same shape as `get_queue()`."""
    items = _classify_brand(conn, org_id, brand_id)
    for item in items:
        cls = item["class"]
        if cls not in QUEUE_CATEGORY:
            continue
        interrupts.enqueue(
            conn, org_id=org_id, brand_id=brand_id, category=QUEUE_CATEGORY[cls],
            dedupe_key=_dedupe_key(cls, item["entity_id"], item["window"]["end"]),
            message=_queue_message(cls, item["name"]),
            action_url=f"/brands/{brand_id}/ads/campaigns/{item['campaign_id']}/detail"
                       f"?ad={item['entity_id']}",
        )
    conn.commit()
    _supersede_stale_open_rows(conn, org_id, brand_id, _live_keys(items))
    return _queue_payload(conn, org_id, brand_id, items)


def get_queue(conn, org_id, brand_id) -> dict:
    """`GET .../queue` (Done #4): read-only, no `resolve()` call here -- `refresh_queue()` is the
    only place that supersedes stale rows (it may not have run yet since the ad's classification
    last changed). Current classification decides which open interrupt rows are still live: an
    older window's open row whose ad has since moved off `stop_loss`/`worse` (e.g. now flat) is
    filtered out of this payload the same way, without writing anything. Each listed row carries
    the current triage item that produced it (F19-I01, `_queue_payload`)."""
    items = _classify_brand(conn, org_id, brand_id)
    return _queue_payload(conn, org_id, brand_id, items)


# ---------------------------------------------------------------------------
# F22-I01/F23-I01: each queue row's own `proposal`, per the "Queue row state" rule (feature
# Decisions) -- on a `stop_loss` row, the change set (if any) that currently answers its ad
# (F22-I01); on a `worse` row, the matching `ads_review_round` (if any), plus its own copy change
# set when one exists (F23-I01). Read-only, brand-wide (one query for every non-superseded change
# set, one for every `ads_action` verification_state, one for every review round, one for the
# handful of entities whose matching pause item reads back `confirmed`) -- never per row.
# ---------------------------------------------------------------------------


def _brand_change_sets_by_campaign(conn, org_id, brand_id) -> dict:
    """Every non-superseded change set of this brand, newest (`created_at`) first -- one query
    for the whole brand. Grouped by `campaign_id` in Python; the SQL-level `ORDER BY created_at
    DESC` is preserved inside each campaign's own sublist (stable grouping), so "the newest
    change set of the row's campaign" is just "the first match found while walking that list"."""
    rows = conn.execute(
        "SELECT id,campaign_id,status,plan_json,decision_reason,revisit_at,created_at "
        "FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND status != 'superseded' "
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
    it for (only a `confirmed` pause proposal ever reads it -- see `_row_proposal`) -- one bounded
    query, never per row."""
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


def _matching_pause_set(sets_by_campaign, campaign_id, entity_id):
    """The newest non-superseded change set of `campaign_id` whose items include a `pause` item
    targeting `entity_id`, and that item itself -- `None, None` when there isn't one. A set with
    an item for a different entity, or living in a different campaign, is never a match."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        item = next(
            (i for i in change_set["plan_json"].get("items", ())
             if i.get("kind") == "pause" and i.get("target_id") == entity_id),
            None,
        )
        if item is not None:
            return change_set, item
    return None, None


def _row_proposal(sets_by_campaign, action_states, native_status_by_entity, triage_item):
    """The `proposal` for one `stop_loss` row (feature Decisions "Queue row state", pre-dispatch
    challenge corrections folded in) -- `None` when there is no matching set, or the matching set
    doesn't currently "count": a `deferred` set past its own `revisit_at`, a `rejected` set whose
    `created_at` day has fallen outside this row's current triage window, or an `approved` set
    whose matching item reads back `confirmed` while the entity's own `native_status` is no
    longer paused (triage never reads `native_status` itself -- see `triage.py:228-307` -- so a
    re-enabled ad must get a fresh proposal rather than reusing a stale `confirmed` one)."""
    change_set, matched_item = _matching_pause_set(
        sets_by_campaign, triage_item["campaign_id"], triage_item["entity_id"],
    )
    if change_set is None or matched_item is None:
        return None
    verification_state = action_states.get(matched_item["id"], "pending")
    if change_set["status"] == "deferred":
        revisit_at = change_set["revisit_at"]
        if revisit_at is not None and revisit_at <= now_utc():
            return None
    elif change_set["status"] == "rejected":
        window = triage_item["window"]
        created_day = change_set["created_at"].date()
        if not (window["start"] <= created_day <= window["end"]):
            return None
    elif verification_state == "confirmed":
        if native_status_by_entity.get(triage_item["entity_id"]) != "PAUSED":
            return None
    return {
        "change_set_id": change_set["id"], "campaign_id": change_set["campaign_id"],
        "kind": matched_item["kind"], "status": change_set["status"],
        "verification_state": verification_state, "reason": change_set["decision_reason"],
        "revisit_at": change_set["revisit_at"],
        "multi": len(change_set["plan_json"].get("items", ())) > 1,
    }


def _queue_payload(conn, org_id, brand_id, items) -> dict:
    # F19-I01: each open row's own triage item, keyed by the same dedupe key the enqueue used --
    # the frontend never parses `dedupe_key` strings itself. Only `stop_loss`/`worse` items ever
    # produce a key (see `_live_keys`), so this doubles as the "still live" filter below.
    items_by_key = {
        _dedupe_key(item["class"], item["entity_id"], item["window"]["end"]): item
        for item in items if item["class"] in QUEUE_CATEGORY
    }
    queue_categories = set(QUEUE_CATEGORY.values())
    # archive_stale=False: this is a read inside a read-only path too (`get_queue`), and
    # `refresh_queue` already committed its own writes above -- neither call should also trigger
    # the unrelated informational-archival side effect of `list_open(archive_stale=True)`.
    rows = [
        row
        for row in interrupts.list_open(conn, brand_id=brand_id, archive_stale=False)
        if row["category"] in queue_categories and row["dedupe_key"] in items_by_key
    ]
    # F22-I01: only `stop_loss` rows' own entities need the native_status lookup (only a
    # `confirmed` pause proposal ever reads it).
    stop_loss_entity_ids = {
        items_by_key[row["dedupe_key"]]["entity_id"]
        for row in rows
        if items_by_key[row["dedupe_key"]]["class"] == "stop_loss"
    }
    sets_by_campaign = _brand_change_sets_by_campaign(conn, org_id, brand_id)
    action_states = _brand_action_verification_states(conn, org_id, brand_id)
    native_status_by_entity = _brand_entity_native_status(
        conn, org_id, brand_id, stop_loss_entity_ids
    )
    # F23-I01: `worse` rows' own proposal -- the matching review round (if any), brand-wide.
    rounds_by_entity = _brand_review_rounds(conn, org_id, brand_id)
    open_rows = []
    for row in rows:
        triage_item = items_by_key[row["dedupe_key"]]
        cls = triage_item["class"]
        if cls == "stop_loss":
            proposal = _row_proposal(
                sets_by_campaign, action_states, native_status_by_entity, triage_item
            )
        elif cls == "worse":
            proposal = _row_review_proposal(
                rounds_by_entity, sets_by_campaign, action_states, triage_item
            )
        else:
            proposal = None
        open_rows.append({**row, "triage": triage_item, "proposal": proposal})
    counts = dict.fromkeys(ALL_CLASSES, 0)
    for item in items:
        counts[item["class"]] += 1
    return {
        "items": open_rows, "counts": counts, "total_ads": len(items),
        "kinds_available": KINDS_AVAILABLE, "kinds_pending": KINDS_PENDING,
    }
