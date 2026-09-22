"""app/ads/triage_ladder.py — F27-I01: Contract A, the handling ladder and change history for a
campaign's ACTIVE ads. Read-only, no LLM call, no platform write (ARCHITECTURE.md §0). Attached by
`triage.classify()` onto its own per-ad items, never queried on its own.

Lineage: a replacement ad is created by a confirmed `new_ad` item whose change set's `plan_json`
carries `replaces_entity_id` (F27-I05) -- the native ad it actually created is read back through
`ads_handoff_item.entity_id` for the row whose `action_id` equals that `new_ad` item's own id
(`change_control.py::_insert_actions`/`handoff_new_ad.install` both key `ads_action`/
`ads_handoff_item` by the plan_json item's own id -- correction 11, `handoff_check.py:127-165`
writes `entity_id` back onto that same handoff row once the created ad is read back). Walking that
link backwards from an active ad's own `entity_id` gives its full lineage; `step`/`copy_changes`/
`image_changes` count confirmed items across that whole chain (Contract A), never `ads_action.kind`
(correction 11 -- that column's CHECK constraint doesn't even include `copy`/`new_ad`, see
`change_control.py::_insert_actions`'s own `kind` remap).
"""

from collections import defaultdict
from datetime import timedelta

from app.ads import review_evidence

_WINDOW_DAYS = 7
_HISTORY_CAP = 10
_HISTORY_KINDS = {"copy", "pause", "new_ad"}


def attach(conn, org_id, brand_id, campaign_id, items) -> list:
    """Mutates each of `items` (this campaign's own `_classify_ad()` dicts, ACTIVE ads only) in
    place, adding its own `ladder` and `history`. One extra query for this campaign's own change
    sets/actions/handoff bindings, one for the daily rows any needed window touches -- never one
    query per ad (same "one pass" shape `classify()`'s own single `ads_external_daily` read
    uses)."""
    if not items:
        return items
    sets = _campaign_change_sets(conn, org_id, brand_id, campaign_id)
    action_states, verified_at_by_action = _campaign_action_states(
        conn, org_id, brand_id, campaign_id
    )
    copy_by_target, pause_by_target, new_ad_items = _index_items(
        sets, action_states, verified_at_by_action
    )
    new_ad_by_created_entity = _new_ad_by_created_entity(
        conn, org_id, brand_id, campaign_id, new_ad_items
    )
    rows_by_entity = _daily_rows(
        conn, org_id, brand_id, campaign_id, copy_by_target, pause_by_target,
        new_ad_by_created_entity,
    )
    for item in items:
        lineage, links = _lineage(item["entity_id"], new_ad_by_created_entity)
        image_changes = len(links)
        copy_changes = sum(len(copy_by_target.get(eid, [])) for eid in lineage)
        item["ladder"] = {
            "step": 2 if image_changes >= 1 else 1 if copy_changes >= 1 else 0,
            "copy_changes": copy_changes, "image_changes": image_changes,
            "lineage_from": lineage[1] if len(lineage) > 1 else None,
        }
        item["history"] = _history(lineage, links, copy_by_target, pause_by_target, rows_by_entity)
    return items


def _campaign_change_sets(conn, org_id, brand_id, campaign_id) -> list:
    """This campaign's own non-superseded change sets -- one query (same `status != 'superseded'`
    scope `triage.py::_brand_change_sets_by_campaign` applies brand-wide, scoped here to the one
    campaign `classify()` is already reading, never a second brand-wide read per campaign)."""
    rows = conn.execute(
        "SELECT id,plan_json,approved_at FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status != 'superseded'",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _campaign_action_states(conn, org_id, brand_id, campaign_id) -> tuple[dict, dict]:
    """`ads_action.id -> verification_state`/`verified_at` for this campaign -- one query (same
    shape `triage.py::_brand_action_verification_states` uses brand-wide)."""
    rows = conn.execute(
        "SELECT id,verification_state,verified_at FROM ads_action WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    states = {r["id"]: r["verification_state"] for r in rows}
    verified_at = {r["id"]: r["verified_at"] for r in rows}
    return states, verified_at


def _index_items(sets, action_states, verified_at_by_action) -> tuple[dict, dict, list]:
    """Every CONFIRMED `copy`/`pause`/`new_ad` plan_json item of this campaign, grouped by its own
    target entity (`copy`/`pause`) or collected separately (`new_ad`, whose `target_id` is a
    placement, not an entity -- `handoff_new_ad.py::create`). `kind` read from `plan_json`, never
    `ads_action.kind` (correction 11). A set never approved (`approved_at is None`) can hold no
    confirmed item -- skipped without a per-item check."""
    copy_by_target, pause_by_target, new_ad_items = defaultdict(list), defaultdict(list), []
    for change_set in sets:
        approved_at = change_set["approved_at"]
        if approved_at is None:
            continue
        for item in change_set["plan_json"].get("items", ()):
            kind = item.get("kind")
            item_id = item.get("id")
            if kind not in _HISTORY_KINDS or action_states.get(item_id) != "confirmed":
                continue
            entry = {
                "change_set_id": change_set["id"], "kind": kind, "approved_at": approved_at,
                "verified_at": verified_at_by_action.get(item_id),
            }
            if kind == "copy":
                copy_by_target[item["target_id"]].append(entry)
            elif kind == "pause":
                pause_by_target[item["target_id"]].append(entry)
            else:
                new_ad_items.append({
                    **entry, "item_id": item_id,
                    "replaces_entity_id": change_set["plan_json"].get("replaces_entity_id"),
                })
    return copy_by_target, pause_by_target, new_ad_items


def _new_ad_by_created_entity(conn, org_id, brand_id, campaign_id, new_ad_items) -> dict:
    """The native ad each confirmed, replacement-carrying `new_ad` item actually created --
    `ads_handoff_item.entity_id` for the row whose `action_id` is that item's own id (correction
    11), keyed by that created entity so `_lineage` can walk backwards from any ad's own
    `entity_id`. A `new_ad` item with no `replaces_entity_id` is not a replacement (a brand-new ad
    with no lineage) and never reaches this query."""
    eligible = [i for i in new_ad_items if i["replaces_entity_id"]]
    if not eligible:
        return {}
    action_ids = [i["item_id"] for i in eligible]
    rows = conn.execute(
        "SELECT action_id,entity_id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND action_id = ANY(%s) AND entity_id IS NOT NULL",
        (org_id, brand_id, campaign_id, action_ids),
    ).fetchall()
    created_entity_by_action = {r["action_id"]: r["entity_id"] for r in rows}
    by_created_entity = {}
    for entry in eligible:
        created_entity = created_entity_by_action.get(entry["item_id"])
        if created_entity is not None:
            by_created_entity[created_entity] = entry
    return by_created_entity


def _lineage(entity_id, new_ad_by_created_entity) -> tuple[list, list]:
    """This ad's own lineage, newest (itself) first, and the confirmed replacement links walked to
    build it -- stops at a missing link or a cycle (defensive; `replaces_entity_id` is always an
    earlier ad in practice)."""
    lineage, links, seen = [entity_id], [], {entity_id}
    current = entity_id
    while True:
        link = new_ad_by_created_entity.get(current)
        if link is None:
            break
        predecessor = link["replaces_entity_id"]
        if predecessor is None or predecessor in seen:
            break
        links.append({**link, "created_entity_id": current})
        lineage.append(predecessor)
        seen.add(predecessor)
        current = predecessor
    return lineage, links


def _daily_rows(
    conn, org_id, brand_id, campaign_id, copy_by_target, pause_by_target, new_ad_by_created_entity
) -> dict:
    """Every `ads_external_daily` row (ad scope) of exactly the entities any `cost_before`/
    `cost_after` window could need -- one query, sliced per window in `_cost` below (same
    pre-fetch-then-slice shape `triage.py::classify`'s own `rows_by_entity` uses)."""
    entity_ids = set(copy_by_target) | set(pause_by_target)
    for created_entity, link in new_ad_by_created_entity.items():
        entity_ids.add(created_entity)
        entity_ids.add(link["replaces_entity_id"])
    if not entity_ids:
        return {}
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND metric_scope='ad' AND entity_id = ANY(%s)",
        (org_id, brand_id, campaign_id, list(entity_ids)),
    ).fetchall()
    rows_by_entity = defaultdict(list)
    for row in rows:
        rows_by_entity[row["entity_id"]].append(dict(row))
    return rows_by_entity


def _cost(rows_by_entity, entity_id, start, end) -> float | None:
    """This entity's own cost per result over `[start, end]` -- `None` unless every day of that
    window is known (fewer-than-7-known-days rule, Contract A), same `metric_scope == "ad"`,
    single-view-or-unknown shape `triage.py::_ad_window` applies for its own windows."""
    entity_rows = [r for r in rows_by_entity.get(entity_id, []) if start <= r["day"] <= end]
    if not entity_rows:
        return None
    aggregated = review_evidence.aggregate(entity_rows, start, end)
    views = [v for v in aggregated["result_views"] if v["metric_scope"] == "ad"]
    view = views[0] if len(views) == 1 else None
    days = (end - start).days + 1
    if view is None or view["reason"] is not None or view["days_known"] < days:
        return None
    return view["cost_per_result"]


def _cost_before(rows_by_entity, entity_id, approved_at):
    end = approved_at.date() - timedelta(days=1)
    start = end - timedelta(days=_WINDOW_DAYS - 1)
    return _cost(rows_by_entity, entity_id, start, end)


def _cost_after(rows_by_entity, entity_id, verified_at):
    start = verified_at.date() + timedelta(days=1)
    end = start + timedelta(days=_WINDOW_DAYS - 1)
    return _cost(rows_by_entity, entity_id, start, end)


def _entry(entry, before_entity, after_entity, rows_by_entity) -> dict:
    verified_at = entry.get("verified_at")
    return {
        "change_set_id": entry["change_set_id"], "kind": entry["kind"],
        "approved_at": entry["approved_at"], "verified_at": verified_at,
        "cost_before": _cost_before(rows_by_entity, before_entity, entry["approved_at"]),
        "cost_after": _cost_after(rows_by_entity, after_entity, verified_at)
        if verified_at else None,
    }


def _history(lineage, links, copy_by_target, pause_by_target, rows_by_entity) -> list:
    """This ad and its lineage predecessors' own handling events (correction 11: only items that
    target one of those ads -- `copy`/`pause` in place, plus the `new_ad` that replaced each
    predecessor; budget items target owners, never listed here), newest `approved_at` first,
    capped at 10."""
    entries = []
    for entity_id in lineage:
        for entry in copy_by_target.get(entity_id, []):
            entries.append(_entry(entry, entity_id, entity_id, rows_by_entity))
        for entry in pause_by_target.get(entity_id, []):
            entries.append(_entry(entry, entity_id, entity_id, rows_by_entity))
    for link in links:
        entries.append(
            _entry(link, link["replaces_entity_id"], link["created_entity_id"], rows_by_entity)
        )
    entries.sort(key=lambda e: e["approved_at"], reverse=True)
    return entries[:_HISTORY_CAP]
