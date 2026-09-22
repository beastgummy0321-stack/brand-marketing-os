"""app/ads/triage_capacity.py — F27-I06: Contract F, per-campaign capacity and the cleanup
candidate ads for the brand queue. Read-only, no LLM call, no platform write
(ARCHITECTURE.md §0 "程式整理，LLM 判斷"). Reuses `triage_scale.owner_lookup` for the per-ad
daily budget owner (never a second, divergent definition of "daily budget owner", feature
Decisions "Gaps kept honest").

Cleanup never touches an ad in an "open replacement lineage" (pre-dispatch correction 4): a
replacement ad whose own `new_ad` item hasn't reached `confirmed` yet, or an old ad a confirmed
`new_ad` item has already replaced but whose own follow-up pause (Contract E) hasn't happened.
This walks the SAME `plan_json.replaces_entity_id` / `ads_handoff_item.entity_id` link
`triage_ladder.py` uses for lineage, but over every verification state (not confirmed-only --
`triage_ladder` only cares about confirmed history, this cares about "not yet settled").
"""

import math
from datetime import timedelta

from app.ads import review_evidence

_CLEANUP_WINDOW_DAYS = 7


def capacity_view(items, target_value, owner_by_entity) -> dict:
    """Contract F: `{daily_budget, currency, target, can_support, active_ads}` for one campaign's
    own ACTIVE ads (`items`: this campaign's own `classify()` items, already active-ads-only).
    `daily_budget` is `null` when there are no active ads, when any active ad has no daily budget
    owner (correction 4), or when the qualifying owners don't share one currency (never a partial
    sum across currencies, same "Gaps kept honest" rule `triage_scale.py` follows). `can_support`
    is `floor(daily_budget / (target * 2))` once both are known and `target > 0`."""
    active_ads = len(items)
    daily_budget = currency = None
    if active_ads > 0:
        owners = {}
        every_has_owner = True
        for item in items:
            owner = owner_by_entity.get(item["entity_id"])
            if owner is None:
                every_has_owner = False
                break
            owners[owner["id"]] = owner
        if every_has_owner:
            currencies = {owner.get("currency") for owner in owners.values()}
            if len(currencies) == 1 and next(iter(currencies)) is not None:
                currency = next(iter(currencies))
                daily_budget = sum(float(owner["budget_amount"]) for owner in owners.values())
    can_support = None
    if daily_budget is not None and target_value is not None and target_value > 0:
        can_support = math.floor(daily_budget / (target_value * 2))
    return {
        "daily_budget": daily_budget, "currency": currency, "target": target_value,
        "can_support": can_support, "active_ads": active_ads,
    }


def _new_ad_rows(conn, org_id, brand_id, campaign_id) -> list:
    """Every `new_ad` plan_json item of this campaign's non-superseded change sets that carries a
    `replaces_entity_id` (a replacement, never a fresh non-replacement ad -- same eligibility
    `triage_ladder._new_ad_by_created_entity` applies), regardless of its own verification state
    (unlike `triage_ladder`, which only cares once `confirmed`) -- this needs to find the ones
    still UNsettled too."""
    sets = conn.execute(
        "SELECT id,plan_json,status FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status != 'superseded'",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    rows = []
    for change_set in sets:
        change_set = dict(change_set)
        replaces_entity_id = change_set["plan_json"].get("replaces_entity_id")
        if not replaces_entity_id:
            continue
        for item in change_set["plan_json"].get("items", ()):
            if item.get("kind") == "new_ad":
                rows.append({
                    "set_id": change_set["id"], "item_id": item.get("id"),
                    "replaces_entity_id": replaces_entity_id,
                })
    return rows


def _open_lineage_entity_ids(conn, org_id, brand_id, campaign_id) -> set:
    """Entity ids that must never be a cleanup candidate (correction 4): the entity a still-
    unverified `new_ad` item created, or the old entity a CONFIRMED `new_ad` item has replaced
    while no non-superseded `pause` item targets that old entity yet (its own follow-up, Contract
    E, hasn't happened). One query for the campaign's own change sets (`_new_ad_rows`), one for
    the matching `ads_action` states, one for the created entity of each `new_ad` item
    (`ads_handoff_item.entity_id`, correction 11's same link) -- never per ad."""
    new_ad_rows = _new_ad_rows(conn, org_id, brand_id, campaign_id)
    if not new_ad_rows:
        return set()
    item_ids = [row["item_id"] for row in new_ad_rows]
    action_states = {
        r["id"]: r["verification_state"]
        for r in conn.execute(
            "SELECT id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND id = ANY(%s)",
            (org_id, brand_id, campaign_id, item_ids),
        ).fetchall()
    }
    created_entity_by_item = {
        r["action_id"]: r["entity_id"]
        for r in conn.execute(
            "SELECT action_id,entity_id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND action_id = ANY(%s) AND entity_id IS NOT NULL",
            (org_id, brand_id, campaign_id, item_ids),
        ).fetchall()
    }
    paused_targets = set()
    for change_set in conn.execute(
        "SELECT plan_json FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status != 'superseded'",
        (org_id, brand_id, campaign_id),
    ).fetchall():
        for item in dict(change_set)["plan_json"].get("items", ()):
            if item.get("kind") == "pause":
                paused_targets.add(item.get("target_id"))

    open_ids = set()
    for row in new_ad_rows:
        created_entity = created_entity_by_item.get(row["item_id"])
        state = action_states.get(row["item_id"])
        if state == "confirmed":
            # The replacement is live -- the OLD ad is open until its own follow-up pause exists.
            if row["replaces_entity_id"] not in paused_targets:
                open_ids.add(row["replaces_entity_id"])
        elif created_entity is not None:
            # Not yet verified -- the NEW ad itself (once it actually exists as an entity) is open.
            open_ids.add(created_entity)
    return open_ids


def _ad_spend_7d(rows_by_entity, entity_id, start, end):
    """This ad's own known spend over `[start, end]` -- `None` unless every day of that window is
    known (never a partial-window guess, same "7-day window not fully covered" rule correction 4
    names), single currency, ad scope only (same shape `triage.py::_ad_spend` uses for its own
    windows -- not imported directly, `triage.py` is this module's own caller, never the other way
    around)."""
    rows = [r for r in rows_by_entity.get(entity_id, []) if start <= r["day"] <= end]
    aggregated = review_evidence.aggregate(rows, start, end)
    if aggregated["missing_days"]:
        return None
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None
    if len({s["currency"] for s in entries}) > 1:
        return None
    return sum(s["metrics"]["spend"] for s in entries)


def cleanup_candidates(
    conn, org_id, brand_id, campaign_id, campaign_name, items, rows_by_entity, cutoff, capacity,
) -> dict | None:
    """Contract F cleanup rule -- `None` when `can_support` is unknown, `< 1`, or the campaign
    isn't over capacity; else the payload for a `cleanup` queue row, proposing to pause the
    (`active_ads - can_support - stop_loss ads`) active ads with the lowest 7-day spend. A
    `stop_loss` ad is never a candidate and already counts as leaving (drill 5: counting it as
    staying proposed pausing the best ad too and kept the 0-purchase one); also excluded:
    an ad in an open replacement lineage (correction 4), or an ad whose
    own 7-day window isn't fully covered. When fewer ads are eligible than the excess calls for,
    this proposes however many ARE eligible (never nothing just because the ideal count isn't
    reachable) -- `None` only when NO ad is eligible at all."""
    can_support = capacity["can_support"]
    active_ads = capacity["active_ads"]
    if can_support is None or can_support < 1 or active_ads <= can_support:
        return None
    excess = active_ads - can_support - sum(1 for item in items if item["class"] == "stop_loss")
    if excess <= 0:
        return None
    open_lineage = _open_lineage_entity_ids(conn, org_id, brand_id, campaign_id)
    start = cutoff - timedelta(days=_CLEANUP_WINDOW_DAYS - 1)
    eligible = []
    for item in items:
        entity_id = item["entity_id"]
        if item["class"] == "stop_loss" or entity_id in open_lineage:
            continue
        spend = _ad_spend_7d(rows_by_entity, entity_id, start, cutoff)
        if spend is None:
            continue
        eligible.append((spend, item))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: (pair[0], pair[1]["entity_id"]))
    chosen = eligible[:excess]
    return {
        "campaign_id": campaign_id, "campaign_name": campaign_name,
        "can_support": can_support, "active_ads": active_ads,
        "ads": [
            {
                "entity_id": item["entity_id"], "name": item["name"],
                "thumbnail_url": item["thumbnail_url"], "spend_7d": spend,
            }
            for spend, item in chosen
        ],
    }
