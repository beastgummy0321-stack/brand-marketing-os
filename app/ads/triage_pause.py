"""app/ads/triage_pause.py — F45-I05: Contract P (ads.md §6.49), the pause proposal's own read of
one ad. Root cause it removes (drill 10 §1 #4): the pause page found its ad only through a
home-queue row, so an entry from a review, a read-back or the 成效 tab had nothing to show. This
reads the ad itself -- its row in this campaign, its own triage item (`triage.ad_item`, the same
grade and window `GET …/triage` gives) and the open plain pause set on it. The home queue is never
read here. Pure reads: no LLM call, no platform write, no platform literal.
"""

from datetime import date, datetime

from app.ads import ad_status, repository, triage, triage_capacity

_DELETED = "DELETED"


def pause_view(conn, org_id: str, brand_id: str, campaign_id: str, entity_id: str) -> dict:
    """`{state, entity_id, name, triage, reason_text, closed_at, last_read_at, change_set_id}`.
    `state` is `active` (a platform ad of this campaign that `ad_status.is_closed` does not call
    closed -- unknown status is active), `closed` (closed, not `DELETED`) or `gone` (no such ad in
    this campaign, not an ad, or `DELETED`; `triage` is then `None`). `reason_text` (F48 Contract R
    "reason texts") is the pause's reason built from this ad's own grade and numbers
    (`triage_capacity.reason_text`, the cleanup entries' same sentences without a rank), `None`
    when `triage` is. Raises `ValueError("campaign_unknown")` only for an unknown campaign."""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    entity = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s",
        (org_id, brand_id, campaign_id, entity_id),
    ).fetchone()
    entity = dict(entity) if entity is not None else None
    state = _state(entity)
    item = triage.ad_item(conn, org_id, brand_id, campaign, entity) \
        if entity is not None and state != "gone" else None
    return {
        "state": state, "entity_id": entity_id,
        "name": entity.get("name") if entity is not None else None,
        "triage": item,
        "reason_text": triage_capacity.reason_text(item) if item is not None else None,
        "closed_at": _iso(entity.get("status_changed_at")) if entity is not None else None,
        "last_read_at": _iso(entity.get("last_success_at")) if entity is not None else None,
        "change_set_id": _open_pause_set_id(conn, org_id, brand_id, campaign_id, entity_id),
    }


def _state(entity) -> str:
    if entity is None or entity["native_kind"] != "ad" or entity["native_status"] == _DELETED:
        return "gone"
    return "closed" if ad_status.is_closed(entity["native_status"]) else "active"


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _open_pause_set_id(conn, org_id, brand_id, campaign_id, entity_id):
    """The newest non-superseded PLAIN set (no `plan_json.source`: a cleanup or A/B set is owned by
    its own page) of this campaign with a `pause` item on this ad that is still open -- `draft`,
    or `approved` with that item's `ads_action.verification_state` not `confirmed` (no action row
    reads `pending`, the same default `triage._queue_payload` uses). `None` otherwise."""
    sets = conn.execute(
        "SELECT id,status,plan_json FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status IN ('draft','approved') ORDER BY created_at DESC, id DESC",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    candidates = []
    for change_set in sets:
        plan = change_set["plan_json"] or {}
        if plan.get("source"):
            continue
        item = next(
            (i for i in plan.get("items", ())
             if i.get("kind") == "pause" and i.get("target_id") == entity_id),
            None,
        )
        if item is not None:
            candidates.append((change_set, item))
    if not candidates:
        return None
    action_ids = [item["id"] for _, item in candidates if item.get("id")]
    states = {
        row["id"]: row["verification_state"]
        for row in conn.execute(
            "SELECT id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s "
            "AND id = ANY(%s)",
            (org_id, brand_id, action_ids),
        ).fetchall()
    } if action_ids else {}
    for change_set, item in candidates:
        if change_set["status"] == "draft":
            return change_set["id"]
        if states.get(item.get("id"), "pending") != "confirmed":
            return change_set["id"]
    return None
