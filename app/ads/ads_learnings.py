"""app/ads/ads_learnings.py — F48 Contract W: `write` is the one door every `learning_ledger` row
from `app/ads` goes through (`bi_repo.record_learning` is called nowhere else in this module tree,
`test_ads_one_ruler.py` enforces it), always with the sell-way it belongs to.

Contract D (F27): the ads-track learning a confirmed `pause` item
carrying an `angle` (Contract C) writes to the brand's learning ledger
(`app.brand_intelligence.repository`, public functions only -- this module never touches
`learning_ledger` directly).

Pre-dispatch correction 8 (2026-09-22, authoritative): the write happens AFTER
`change_control_verify.check` has already committed the item as `confirmed` (`record_learning`
commits its own transaction); idempotency is keyed by an existing learning whose
`source_cycle_id` equals the change ITEM id (`ads_action.id`), never the change SET id -- the
automatic runtime re-check (`app/ads/runtime.py`) calls `check` again on items that are already
`confirmed`, and that second pass must not write a second row.

Promotion (Contract D): confidence is decided by counting earlier `source_track="ads"` learnings
of the brand with the exact same `learning_text` -- 0 earlier -> observed, 1 -> likely, >=2 ->
validated. `list_learnings` has no text filter, so this scans and filters in Python, the same
precedent as `app/ads/visual_learning.py`'s own promotion scan.
"""

from typing import cast

from app.ads import repository as ads_repo
from app.ads import sell_way
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

# Generous ceiling for the idempotency/promotion scans below -- same precedent as
# `visual_learning.py`'s `limit=500`; this module's own list endpoint stays at the contract's
# `<=50` (see `list_for_brand`).
_SCAN_LIMIT = 500


def write(conn: _AnyConn, org_id: str, brand_id: str, *, product_id: str | None, text: str,
          scope: str, confidence: str, sample_size: str, source_cycle_id: str | None,
          source_track: str, needs_revalidation: bool = False, platform: str | None = None,
          actor: str = "system") -> dict:
    """F48 Contract W: write one learning-ledger row and return it. `product_id` is required: the
    sell-way the learning belongs to (`sell_way.of_campaign`／`of_ad`／`of_campaign_id`); pass
    `None` explicitly only for a campaign that has no sell-way (an imported campaign) -- that row
    is read as brand level. `org_id` names the caller's tenant; the ledger derives the org from
    the brand itself."""
    return bi_repo.record_learning(
        cast(Conn, conn), brand_id, actor=actor, learning_text=text,
        applicability_scope=scope, confidence=confidence, sample_size=sample_size,
        source_cycle_id=source_cycle_id, product_id=product_id, platform=platform,
        needs_revalidation=needs_revalidation, source_track=source_track,
    )


def _text(angle: str) -> str:
    return f"「{angle}」對這群受眾無效"


def _confidence_for_count(count: int) -> str:
    if count >= 2:
        return "validated"
    if count >= 1:
        return "likely"
    return "observed"


def _ads_rows(conn: _AnyConn, brand: str) -> list[dict]:
    return bi_repo.list_learnings(cast(Conn, conn), brand, source_track="ads", limit=_SCAN_LIMIT)


def view_for_item(conn: _AnyConn, brand: str, item_id: str) -> dict:
    """Contract D: the set item view's `learning` field. Read-time lookup (never stored on the
    item itself) so a later promotion of another item's identical text never has to reach back
    and rewrite this one."""
    rows = _ads_rows(conn, brand)
    mine = next((row for row in rows if row["source_cycle_id"] == item_id), None)
    if mine is None:
        return {"recorded": False, "confidence": None, "count": 0}
    count = sum(
        1 for row in rows
        if row["learning_text"] == mine["learning_text"] and row["learned_at"] <= mine["learned_at"]
    )
    return {"recorded": True, "confidence": mine["confidence"], "count": count}


def record_for_item(conn: _AnyConn, org: str, brand: str, campaign: str, set_id: str,
                     item: dict) -> dict | None:
    """Contract D + correction 8: call only once `check` has already committed `item` as
    `confirmed`. `item` is the item view returned by `change_control.item`/`change_control_data
    .get` (carries `kind`, `angle`, and `id` -- the change ITEM id, never the change SET id).
    A no-op (returns `None`) for anything but a `pause` item that carries an `angle`, or when a
    learning for this exact item was already recorded (idempotent against the automatic runtime
    re-check in `app/ads/runtime.py`, which calls `check` again on items already `confirmed`)."""
    angle = item.get("angle")
    if item.get("kind") != "pause" or not angle:
        return None
    item_id = item["id"]
    rows = _ads_rows(conn, brand)
    if any(row["source_cycle_id"] == item_id for row in rows):
        return None
    text = _text(angle)
    prior = sum(1 for row in rows if row["learning_text"] == text)
    return write(
        conn, org, brand, product_id=sell_way.of_campaign_id(conn, org, brand, campaign),
        text=text, scope=f"ads;campaign={campaign}", confidence=_confidence_for_count(prior),
        sample_size="1", source_cycle_id=item_id, source_track="ads",
    )


def ab_text(ab: dict) -> str:
    """F29-I04 Contract F: the learning an A/B set's confirmed pause writes -- no numbers, so the
    same conclusion reached twice promotes confidence (Contract D)."""
    return (
        f"「{ab['dimension_label']}」用「{ab['winner']['value_label']}」"
        f"比「{ab['loser']['value_label']}」划算"
    )


def record_for_ab_item(conn: _AnyConn, org: str, brand: str, campaign: str, change_set: dict,
                       item: dict) -> dict | None:
    """F29-I04 Contract F, same rules as `record_for_item`: call only once `check` has already
    committed `item` as `confirmed`; idempotent per change ITEM id (the runtime re-check calls
    `check` again). A no-op for anything but the `pause` item of a `source: "ab"` set."""
    plan = change_set.get("plan_json") or {}
    ab = plan.get("ab")
    if plan.get("source") != "ab" or not ab or item.get("kind") != "pause":
        return None
    item_id = item["id"]
    rows = _ads_rows(conn, brand)
    if any(row["source_cycle_id"] == item_id for row in rows):
        return None
    text = ab_text(ab)
    prior = sum(1 for row in rows if row["learning_text"] == text)
    return write(
        conn, org, brand, product_id=sell_way.of_campaign_id(conn, org, brand, campaign),
        text=text, scope=f"ads;campaign={campaign}", confidence=_confidence_for_count(prior),
        sample_size="1", source_cycle_id=item_id, source_track="ads",
    )


# F29-I03 Contract E: a period-settle learning's `source_cycle_id` is `settle:<month>:<entity_id>`
# (`app/ads/settle.py`), naming the ad entity instead of a change item.
_SETTLE_PREFIX = "settle:"


def _campaign_of_source(conn: _AnyConn, org: str, brand: str, source_cycle_id: str | None):
    """The campaign a learning came from: a settle learning through its ad entity, every other one
    through the change item (`ads_action`) its `source_cycle_id` names. `None` when unknown."""
    if not source_cycle_id:
        return None
    if source_cycle_id.startswith(_SETTLE_PREFIX):
        entity_id = source_cycle_id.rsplit(":", 1)[-1]
        row = conn.execute(
            "SELECT campaign_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, entity_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT campaign_id FROM ads_action WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, source_cycle_id),
        ).fetchone()
    return row["campaign_id"] if row else None


def list_for_brand(conn: _AnyConn, brand: str) -> list[dict]:
    """Contract D: `GET .../learnings` -- ads-track rows only, newest first, <=50 (the ledger's
    own default). Each row's `campaign_id`/`campaign_name` is looked up through this module's own
    `ads_action` table (keyed by `source_cycle_id` = the change item id) -- `learning_ledger`
    itself carries no campaign column, and this module never adds one to the legacy table.
    `campaign_objective` (F27-I27) reuses `repository.campaign_objective_family` -- `null` only
    when the campaign itself is unknown/deleted, never a frontend-side guess off the raw
    objective string."""
    rows = _ads_rows(conn, brand)
    result = []
    for row in rows[:50]:
        campaign_id = _campaign_of_source(conn, row["org_id"], brand, row["source_cycle_id"])
        campaign_name = None
        campaign_objective = None
        if campaign_id:
            campaign = ads_repo.get_campaign(cast(Conn, conn), row["org_id"], brand, campaign_id)
            if campaign is not None:
                campaign_name = campaign["name"]
                # F27-I27: the same `campaign_objective_family` rule the month summary and
                # `CampaignChip` elsewhere already use -- never a second, frontend-side guess
                # off the raw `objective` string.
                campaign_objective = ads_repo.campaign_objective_family(
                    cast(Conn, conn), row["org_id"], brand, campaign,
                )
        count = sum(
            1 for other in rows
            if other["learning_text"] == row["learning_text"]
            and other["learned_at"] <= row["learned_at"]
        )
        result.append({
            "id": row["id"],
            "text": row["learning_text"],
            "confidence": row["confidence"],
            "count": count,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "campaign_objective": campaign_objective,
            "learned_at": row["learned_at"],
        })
    return result
