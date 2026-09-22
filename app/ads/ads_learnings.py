"""app/ads/ads_learnings.py — Contract D (F27): the ads-track learning a confirmed `pause` item
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
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn, ConnProxy

_AnyConn = Conn | ConnProxy

# Generous ceiling for the idempotency/promotion scans below -- same precedent as
# `visual_learning.py`'s `limit=500`; this module's own list endpoint stays at the contract's
# `<=50` (see `list_for_brand`).
_SCAN_LIMIT = 500


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
    return bi_repo.record_learning(
        cast(Conn, conn), brand, actor="system", learning_text=text,
        applicability_scope=f"ads;campaign={campaign}", confidence=_confidence_for_count(prior),
        sample_size="1", source_cycle_id=item_id, source_track="ads",
    )


def list_for_brand(conn: _AnyConn, brand: str) -> list[dict]:
    """Contract D: `GET .../learnings` -- ads-track rows only, newest first, <=50 (the ledger's
    own default). Each row's `campaign_id`/`campaign_name` is looked up through this module's own
    `ads_action` table (keyed by `source_cycle_id` = the change item id) -- `learning_ledger`
    itself carries no campaign column, and this module never adds one to the legacy table."""
    rows = _ads_rows(conn, brand)
    result = []
    for row in rows[:50]:
        campaign_id = None
        action = conn.execute(
            "SELECT campaign_id FROM ads_action WHERE org_id=%s AND brand_id=%s AND id=%s",
            (row["org_id"], brand, row["source_cycle_id"]),
        ).fetchone()
        if action:
            campaign_id = action["campaign_id"]
        campaign_name = None
        if campaign_id:
            campaign = ads_repo.get_campaign(cast(Conn, conn), row["org_id"], brand, campaign_id)
            campaign_name = campaign["name"] if campaign else None
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
            "learned_at": row["learned_at"],
        })
    return result
