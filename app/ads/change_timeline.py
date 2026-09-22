"""app/ads/change_timeline.py — F27-I08: Contract H (pre-dispatch correction 1, AUTHORITATIVE).

Nothing is scheduled at approve: the review monitor only takes ads, only "now", and scheduling a
future date there would trigger paid LLM rounds on a timer no one asked for. `next_review_at`,
`spend_stopped` and `delivery_started` are instead derived fresh, on every read, from the item's
own stored `approved_at` (the change set's) / `verified_at` (the item's own `ads_action` row) and
the campaign's own synced coverage (`triage._coverage`). The daily queue refresh re-judging the ad
once `next_review_at` arrives is a different issue's concern; this module only ever reports facts.

Read-only, no platform call, no LLM call (ARCHITECTURE.md §0 「程式整理，LLM 判斷」). `triage` is
imported lazily inside `attach()` -- `change_control_data.get` (this module's only caller) already
imports this module lazily for the same reason: `change_timeline -> triage -> review_evidence ->
change_control_data` would be an import-time cycle if either import were module-level.
"""

from datetime import timedelta

_REVIEW_DAYS = {"budget": 3, "copy": 7, "new_ad": 7}


def _next_review_at(kind, approved_at, verified_at):
    if kind == "budget":
        if approved_at is None:
            return None
        return (approved_at + timedelta(days=_REVIEW_DAYS["budget"])).date()
    if kind in ("copy", "new_ad"):
        if verified_at is None:
            return None
        return (verified_at + timedelta(days=_REVIEW_DAYS[kind])).date()
    return None


def _new_ad_entities(conn, org, brand, campaign_id, item_ids):
    """The native ad each `new_ad` item actually created -- `ads_handoff_item.entity_id` for the
    row whose `action_id` is that item's own id (same lookup `triage_ladder
    ._new_ad_by_created_entity` uses, correction 11), keyed by the item id itself: a `new_ad`
    item's own `target_id` names the destination placement, never the created ad."""
    if not item_ids:
        return {}
    rows = conn.execute(
        "SELECT action_id,entity_id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND action_id = ANY(%s) AND entity_id IS NOT NULL",
        (org, brand, campaign_id, item_ids),
    ).fetchall()
    return {r["action_id"]: r["entity_id"] for r in rows}


def _daily_rows(conn, org, brand, campaign_id, entity_ids):
    """Every ad-scope `ads_external_daily` row any item in this set could need -- one query,
    sliced per item below (same pre-fetch-then-slice shape `triage_ladder._daily_rows` uses)."""
    if not entity_ids:
        return {}
    rows = conn.execute(
        "SELECT entity_id,day,spend,impressions FROM ads_external_daily WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND metric_scope='ad' AND entity_id = ANY(%s)",
        (org, brand, campaign_id, list(entity_ids)),
    ).fetchall()
    by_entity: dict = {}
    for row in rows:
        by_entity.setdefault(row["entity_id"], []).append(dict(row))
    return by_entity


def _spend_stopped(rows, coverage, verified_at):
    """Correction 1: only the FIRST full day after `verified_at` -- true once that single day is
    synced with no row or zero spend, false once it shows real spend, null until that day itself
    is inside the campaign's recorded coverage (`triage._coverage`)."""
    if verified_at is None or coverage is None:
        return None
    day = verified_at.date() + timedelta(days=1)
    coverage_start, coverage_end = coverage
    if day < coverage_start or day > coverage_end:
        return None
    total = sum(float(r["spend"]) for r in rows if r["day"] == day and r["spend"] is not None)
    return total <= 0


def _delivery_started(rows, coverage, verified_at):
    """Contract H: any day after `verified_at` with impressions > 0 -- null while the campaign's
    recorded coverage has not yet reached a day past `verified_at` (nothing to judge yet)."""
    if verified_at is None or coverage is None:
        return None
    _, coverage_end = coverage
    if coverage_end <= verified_at.date():
        return None
    return any(row["day"] > verified_at.date() and (row["impressions"] or 0) > 0 for row in rows)


def attach(conn, org, brand, campaign_id, campaign_row, approved_at, items):
    """Mutates `items` (the `view` dicts `change_control_data.get` builds for one change set),
    adding each item's own `timeline`. One extra query for any `new_ad` item's created entity, one
    for the daily rows any item could need -- never one query per item."""
    from app.ads import triage  # Lazy: see module docstring for the import cycle this avoids.

    if not items:
        return items
    coverage = triage._coverage(campaign_row)
    new_ad_item_ids = [item["id"] for item in items if item["kind"] == "new_ad"]
    new_ad_entities = _new_ad_entities(conn, org, brand, campaign_id, new_ad_item_ids)
    entity_ids = set()
    for item in items:
        if item["kind"] in ("pause", "copy"):
            entity_ids.add(item["target_id"])
        elif item["kind"] == "new_ad" and item["id"] in new_ad_entities:
            entity_ids.add(new_ad_entities[item["id"]])
    rows_by_entity = _daily_rows(conn, org, brand, campaign_id, entity_ids)
    for item in items:
        kind, verified_at = item["kind"], item.get("verified_at")
        spend_stopped = delivery_started = None
        if kind == "pause":
            spend_stopped = _spend_stopped(
                rows_by_entity.get(item["target_id"], []), coverage, verified_at
            )
        elif kind in ("copy", "new_ad"):
            entity = item["target_id"] if kind == "copy" else new_ad_entities.get(item["id"])
            delivery_started = _delivery_started(
                rows_by_entity.get(entity, []) if entity else [], coverage, verified_at
            )
        item["timeline"] = {
            "spend_stopped": spend_stopped,
            "delivery_started": delivery_started,
            "next_review_at": _next_review_at(kind, approved_at, verified_at),
        }
    return items
