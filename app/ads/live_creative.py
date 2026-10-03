"""app/ads/live_creative.py — F31-I05 Contract O: what ran.

The ads learning readers (visual learning, the confirmed comparison, automatic A/B pairs, the
closeout learning scope) must read the creative that went out and the coordinates it was made
for -- never the set's current selection or the ad's current `*_key` once the ad was launched.
Two facts, one place:

- **Outputs.** Launch approval (`change_control_launch._approve_set`, every version) freezes, per
  ad in its batch, the workbench outputs that set showed at that moment (`adopted_output` of each
  part the set has) into `ads_ad.live_creative_json`. `launched_outputs` reads them back; None
  for an ad no approved launch has carried. A later selection change in the workbench does not
  move them; the publish checklist keeps showing the current selection (it does not read this).
- **Coordinates.** An ad's learning coordinates are the `coordinates_snapshot_json` of the set
  its creative came from (the dispatched set; the ruling for item 6: coordinates stay editable
  after dispatch, learning reads the snapshot taken at dispatch), normalised to keys. An ad with
  no dispatched set uses its current coordinates. F46 Contract F: the `format` of an ad with an
  assigned material is the file's actual format (`actual_format`), not the planned one.
- **Offer** (F48 Contract G). `offer_for` / `offers_for`: the offer an ad's copy was written for
  -- the same set's snapshot `offer`, else the ad's current `offer_key`. The copy confirmation
  (`asset_suggestions`) and the slots read it; one resolver, so the judgement, the slot and the
  learning name the same offer after a coordinate edit.

Workbench data only through the `app.workbench` facade (`briefs_for_source` /
`adopted_output`). Private to app/ads.
"""

import json

from app import workbench
from app.core.db import jsonb

COORDINATE_DIMENSIONS = ("audience", "pain", "angle", "hook", "proof", "offer", "format")


def _pack_source_kind() -> str:
    # Lazy: `assets` imports `change_control_launch`, which calls into this module.
    from app.ads import assets

    return assets.PACK_SOURCE_KIND


def _sets(conn, org, brand, campaign_id) -> tuple[dict, dict]:
    """`(ad_id -> the ad's latest dispatched set, set_id -> set)` of this campaign."""
    briefs = workbench.briefs_for_source(
        conn, org, brand, _pack_source_kind(), {"ads_campaign_id": campaign_id}
    )
    by_ad, by_id = {}, {}
    for brief in briefs:
        by_id[brief["id"]] = brief
        ad_id = (brief.get("source_ref") or {}).get("ads_ad_id")
        if ad_id:
            by_ad[ad_id] = brief  # created_at order: the latest set wins
    return by_ad, by_id


def _plain(row):
    """A workbench output row as JSON values, the same text `json.dumps(default=str)` gives the
    live row -- so a frozen row fingerprints exactly like the row it was frozen from."""
    return json.loads(json.dumps(row, default=str)) if row is not None else None


def record_launch(conn, org, brand, campaign_id, change_set_id, frozen) -> None:
    """Launch approval: freeze what each ad of the approved batch goes out with. Runs inside the
    approval's transaction; never touches `updated_at` (a freeze is not a plan edit)."""
    ad_ids = [ad["id"] for group in frozen.get("groups") or [] for ad in group.get("ads") or []]
    if not ad_ids:
        return
    by_ad, _ = _sets(conn, org, brand, campaign_id)
    for ad_id in ad_ids:
        brief = by_ad.get(ad_id)
        outputs = {}
        if brief is not None:
            outputs = {
                part: _plain(workbench.adopted_output(conn, org, brand, brief["id"], part))
                for part in (brief.get("parts") or {})
            }
        conn.execute(
            "UPDATE ads_ad SET live_creative_json=%s "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
            (
                jsonb(
                    {
                        "change_set_id": change_set_id,
                        "set_id": brief["id"] if brief is not None else None,
                        "outputs": outputs,
                    }
                ),
                org,
                brand,
                campaign_id,
                ad_id,
            ),
        )


def launched_outputs(conn, org, brand, campaign_id) -> dict:
    """Contract O: `ad_id -> {change_set_id, set_id, outputs: {part: output row | None}}` frozen
    by the ad's latest approved launch version, or `None` before any approved launch carried it."""
    return {
        row["id"]: row["live_creative_json"]
        for row in conn.execute(
            "SELECT id, live_creative_json FROM ads_ad "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
            (org, brand, campaign_id),
        ).fetchall()
    }


def materials(conn, org, brand, campaign_id, *, parts=None) -> dict:
    """`ad_id -> {"brief": set, "outputs": {part: row | None}}` for every ad with a dispatched
    set: the launched outputs once an approved launch carried the ad, the set's current
    selection (`adopted_output`) before. `parts` limits the parts read before launch (default:
    the parts the set has)."""
    by_ad, by_id = _sets(conn, org, brand, campaign_id)
    launched = launched_outputs(conn, org, brand, campaign_id)
    result = {}
    for ad_id, latest in by_ad.items():
        record = launched.get(ad_id)
        if record is not None:
            brief = by_id.get(record.get("set_id")) or latest
            outputs = dict(record.get("outputs") or {})
            if parts is not None:
                outputs = {part: outputs.get(part) for part in parts}
        else:
            brief = latest
            wanted = parts if parts is not None else (brief.get("parts") or {})
            outputs = {
                part: workbench.adopted_output(conn, org, brand, brief["id"], part)
                for part in wanted
            }
        result[ad_id] = {"brief": brief, "outputs": outputs}
    return result


def snapshot_keys(snapshot) -> dict | None:
    """A set's `coordinates_snapshot_json` as `{dimension: key | None}`. Both stored shapes are
    read: `{dim: "key"}` (ads dispatch) and `{dim: {"key": ..., "label": ...}}`. Not a dict ->
    None (no snapshot)."""
    if not isinstance(snapshot, dict):
        return None
    keys = {}
    for dimension in COORDINATE_DIMENSIONS:
        value = snapshot.get(dimension)
        if isinstance(value, dict):
            value = value.get("key")
        keys[dimension] = value if isinstance(value, str) and value else None
    return keys


def _materials(conn, org, brand, campaign_id) -> dict:
    """`ad_id -> {material_placement_id, material_placement_revision}` of this campaign's ads."""
    return {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT id, material_placement_id, material_placement_revision FROM ads_ad "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
            (org, brand, campaign_id),
        ).fetchall()
    }


def learning_coordinates(conn, org, brand, campaign_id, ads) -> dict:
    """`ad_id -> {dimension: key | None}` for `ads` (rows with `id` and `*_key`): the snapshot
    of the set the ad's creative came from (the launched set, else the ad's dispatched set),
    else the ad's current coordinates. F46 Contract F: an ad with an assigned material takes
    that file's actual format (`actual_format.of_ad`) over the planned `format` -- what shipped
    is what is learned."""
    from app.ads import actual_format

    by_ad, by_id = _sets(conn, org, brand, campaign_id)
    launched = launched_outputs(conn, org, brand, campaign_id)
    materials = _materials(conn, org, brand, campaign_id)
    result = {}
    for ad in ads:
        brief = _creative_set(launched.get(ad["id"]), by_ad, by_id, ad["id"])
        keys = snapshot_keys((brief or {}).get("coordinates_snapshot_json"))
        if keys is None:
            keys = {d: ad.get(f"{d}_key") for d in COORDINATE_DIMENSIONS}
        actual = actual_format.of_ad(
            conn, org, brand, campaign_id, materials.get(ad["id"]) or {}
        )
        if actual is not None:
            keys = {**keys, "format": actual}
        result[ad["id"]] = keys
    return result


def _creative_set(launched_record, by_ad, by_id, ad_id) -> dict | None:
    """The set an ad's creative came from: the launched set, else its latest dispatched set."""
    record = launched_record or {}
    return by_id.get(record.get("set_id")) or by_ad.get(ad_id)


def offers_for(conn, org, brand, campaign_id, ads) -> dict:
    """F48 Contract G: `ad_id -> offer key | None` -- the offer each ad's copy was written for:
    the `offer` of the snapshot of the set its creative came from (the same lookup
    `learning_coordinates` uses), else the ad's current `offer_key`. Coordinates stay editable
    after dispatch (§6.35); the next dispatch picks the new key up."""
    by_ad, by_id = _sets(conn, org, brand, campaign_id)
    launched = launched_outputs(conn, org, brand, campaign_id)
    result = {}
    for ad in ads:
        brief = _creative_set(launched.get(ad["id"]), by_ad, by_id, ad["id"])
        keys = snapshot_keys((brief or {}).get("coordinates_snapshot_json")) or {}
        result[ad["id"]] = keys.get("offer") or ad.get("offer_key")
    return result


def offer_for(conn, org, brand, campaign_id, ad) -> str | None:
    """`offers_for` of one ad: the one resolver of 「which offer this ad's copy is for」, read by
    the copy confirmation (`asset_suggestions`), the slots and the learning coordinates."""
    return offers_for(conn, org, brand, campaign_id, [ad])[ad["id"]]


def with_learning_coordinates(conn, org, brand, detail: dict) -> dict:
    """A copy of a `campaign_detail` whose ads carry their learning coordinates in `*_key`."""
    ads = [ad for group in detail.get("groups") or [] for ad in group.get("ads") or []]
    if not ads:
        return detail
    coordinates = learning_coordinates(conn, org, brand, detail["id"], ads)
    return {
        **detail,
        "groups": [
            {
                **group,
                "ads": [
                    {
                        **ad,
                        **{f"{d}_key": k for d, k in coordinates[ad["id"]].items()},
                    }
                    for ad in group.get("ads") or []
                ],
            }
            for group in detail.get("groups") or []
        ],
    }
