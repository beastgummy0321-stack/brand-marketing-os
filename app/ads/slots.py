"""F30 Contract F: the assets tab's slots -- one planned ad (app-built) or one platform ad
(imported) per slot -- and uploading a file into one planned ad's slot.

Readiness is the launch snapshot's own rule (`handoff_assignment.material_snapshot` ->
`assignment_status == "confirmed"`, the same count `home_overview._draft_view` shows), never a
second definition. A file uploaded into a slot goes through the user-asset placement path
(`user_assets_repository.attach_selected`) and waits on `ads_ad.slot_placement_id` until that
placement is confirmed; only then is it assigned through `handoff_assignment.assign`, so
`material_placement_id` keeps pointing at confirmed versions only. The pointer follows the
placement id (not a revision) because the manual confirmation needs a revision first (purpose).
"""

from app.ads import ad_status, handoff_assignment, material_tasks
from app.ads import assets as legacy_readiness
from app.ads import change_control_launch as launch
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets


def _asset_thumbnail(conn, org, brand, asset_id) -> str | None:
    """The brand original's poster, served by the user-asset content route (an authenticated
    same-origin path); None while its preview is not made yet."""
    try:
        asset = user_assets.get_asset(conn, org, brand, asset_id)
    except ValueError:
        return None
    if not asset.get("thumbnail_key"):
        return None
    return f"/api/ads/brands/{brand}/user-assets/{asset_id}/thumbnail"


def _planned_entities(conn, org, brand, campaign) -> dict:
    """planned ad id -> the platform ad its launch handoff was matched to (newest match)."""
    rows = conn.execute(
        "SELECT h.planned_id,e.* FROM ads_handoff_item h JOIN ads_external_entity e "
        "ON e.id=h.entity_id AND e.org_id=h.org_id AND e.brand_id=h.brand_id "
        "AND e.campaign_id=h.campaign_id WHERE h.org_id=%s AND h.brand_id=%s "
        "AND h.campaign_id=%s AND h.planned_kind='ad' AND h.entity_id IS NOT NULL "
        "ORDER BY h.created_at DESC,h.id DESC",
        (org, brand, campaign),
    ).fetchall()
    found: dict = {}
    for row in rows:
        found.setdefault(row["planned_id"], dict(row))
    return found


def _material(conn, org, brand, campaign, ad) -> dict | None:
    try:
        return handoff_assignment.material_snapshot(conn, org, brand, campaign, ad)
    except ValueError:
        return None


def _pending(conn, org, brand, campaign, ad) -> dict | None:
    """The current revision of the placement uploaded into this slot, not yet assigned."""
    placement_id = ad.get("slot_placement_id")
    if placement_id is None:
        return None
    try:
        return user_assets.placement(conn, org, brand, campaign, placement_id)
    except ValueError:
        return None


def _slot(ad_id, entity_id, name, state, thumbnail_url, replace_task_id=None) -> dict:
    return {
        "ad_id": ad_id,
        "entity_id": entity_id,
        "name": name,
        "state": state,
        "thumbnail_url": thumbnail_url,
        "confirmed": state == "ready",
        "replace_task_id": replace_task_id,
    }


def _planned_slot(conn, org, brand, campaign, ad, entity, readiness, replace_by_entity) -> dict:
    material = _material(conn, org, brand, campaign, ad)
    pending = _pending(conn, org, brand, campaign, ad)
    material_thumb = (
        _asset_thumbnail(conn, org, brand, material["asset_id"]) if material else None
    )
    if entity is not None:
        # Launched: the platform ad is the fact; a replace request reaches it through its id.
        from app.ads import triage

        return _slot(
            ad["id"],
            entity["id"],
            ad["name"],
            "ready",
            triage._thumbnail_url(entity) or material_thumb,
            replace_by_entity.get(entity["id"]),
        )
    if material and material["assignment_status"] == "confirmed":
        return _slot(ad["id"], None, ad["name"], "ready", material_thumb)
    if pending is not None:
        return _slot(
            ad["id"],
            None,
            ad["name"],
            "in_progress",
            _asset_thumbnail(conn, org, brand, pending["asset_id"]),
        )
    if material is not None:
        # Assigned, but the version was revised or its original is not ready: not launchable.
        return _slot(ad["id"], None, ad["name"], "in_progress", material_thumb)
    if readiness.get(ad["id"]) == "in_progress":
        return _slot(ad["id"], None, ad["name"], "in_progress", None)
    return _slot(ad["id"], None, ad["name"], "missing", None)


def _planned_groups(conn, org, brand, campaign, replace_by_entity) -> list:
    ads = ads_repo.list_ads_for_campaign(conn, org, brand, campaign)
    readiness = {
        row["ad_id"]: row["state"]
        for row in legacy_readiness.readiness(conn, org, brand, campaign)
    }
    entities = _planned_entities(conn, org, brand, campaign)
    return [
        {
            "group_id": group["id"],
            "name": group["name"],
            "slots": [
                _planned_slot(
                    conn, org, brand, campaign, ad, entities.get(ad["id"]), readiness,
                    replace_by_entity,
                )
                for ad in ads
                if ad["group_id"] == group["id"]
            ],
        }
        for group in ads_repo._groups_for_campaign(conn, org, brand, campaign)
    ]


def _platform_groups(conn, org, brand, campaign, replace_by_entity) -> list:
    """Imported: every live platform ad under its platform parent (ad set); parents by name."""
    from app.ads import triage

    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s ORDER BY id",
            (org, brand, campaign),
        ).fetchall()
    ]
    by_native = {(r["native_kind"], r["native_id"]): r for r in rows}
    groups: dict = {}
    for entity in rows:
        if entity["native_kind"] != "ad" or ad_status.is_closed(entity.get("native_status")):
            continue
        parent = by_native.get((entity.get("parent_native_kind"), entity.get("parent_native_id")))
        key = parent["id"] if parent is not None else None
        group = groups.setdefault(
            key,
            {
                "group_id": None,
                "name": (parent or {}).get("name") or entity.get("parent_native_id") or "",
                "slots": [],
            },
        )
        group["slots"].append(
            _slot(
                None,
                entity["id"],
                entity.get("name") or entity["native_id"],
                "ready",
                triage._thumbnail_url(entity),
                replace_by_entity.get(entity["id"]),
            )
        )
    ordered = sorted(groups.values(), key=lambda g: g["name"])
    for group in ordered:
        group["slots"].sort(key=lambda s: s["name"])
    return ordered


def read(conn, org, brand, campaign_id) -> dict:
    """`GET …/campaigns/{c}/slots` (Contract F)."""
    campaign = ads_repo.get_campaign(conn, org, brand, campaign_id)
    if campaign is None:
        raise ValueError("找不到此品牌的活動。")
    requests = material_tasks.replace_requests(conn, org, brand, campaign_id)
    by_entity = requests["by_entity"]
    if campaign["origin"] == "imported":
        groups = _platform_groups(conn, org, brand, campaign_id, by_entity)
    else:
        groups = _planned_groups(conn, org, brand, campaign_id, by_entity)
    slots = [s for g in groups for s in g["slots"]]
    return {
        "ready": sum(1 for s in slots if s["state"] == "ready"),
        "total": len(slots),
        "groups": groups,
        "requests": requests["requests"],
        "requests_truncated": requests["truncated"],
    }


def _planned_ad(conn, org, brand, campaign_id, ad_id) -> dict:
    row = conn.execute(
        "SELECT * FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s "
        "FOR UPDATE",
        (org, brand, campaign_id, ad_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到此活動的計畫廣告。")
    return dict(row)


def settle(conn, org, brand, campaign_id, placement_id) -> None:
    """Assign a slot's uploaded placement once its current revision is confirmed. A refusal by
    `handoff_assignment.assign` (e.g. an approved launch freezes the materials) leaves the slot
    waiting; the confirmation itself stands."""
    try:
        current = user_assets.placement(conn, org, brand, campaign_id, placement_id)
        asset = user_assets.get_asset(conn, org, brand, current["asset_id"])
    except ValueError:
        return
    if not current["confirmed_at"] or asset["status"] != "ready":
        return
    waiting = conn.execute(
        "SELECT id FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND slot_placement_id=%s ORDER BY created_at,id",
        (org, brand, campaign_id, placement_id),
    ).fetchall()
    for row in waiting:
        try:
            handoff_assignment.assign(
                conn, org, brand, campaign_id, row["id"], placement_id, current["revision"]
            )
        except ValueError:
            continue
        conn.execute(
            "UPDATE ads_ad SET slot_placement_id=NULL,updated_at=now() WHERE org_id=%s "
            "AND brand_id=%s AND campaign_id=%s AND id=%s AND slot_placement_id=%s",
            (org, brand, campaign_id, row["id"], placement_id),
        )
    conn.commit()


def upload(conn, org, brand, campaign_id, ad_id, body, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/upload`: `{upload_id}` (a finished upload) or
    `{asset_id}`, optional `copy_fields` -- the same inputs as `POST …/placements`."""
    if not isinstance(body, dict) or set(body) - {"upload_id", "asset_id", "copy_fields"}:
        raise ValueError("上傳欄位無效。")
    if not body.get("upload_id") and not body.get("asset_id"):
        raise ValueError("請先上傳檔案，或選一個品牌原檔。")
    ads_repo.require_internal_campaign(conn, org, brand, campaign_id)
    ad = _planned_ad(conn, org, brand, campaign_id, ad_id)
    if ad["id"] in _planned_entities(conn, org, brand, campaign_id):
        raise ValueError("這則廣告已在平台上；要換素材請用「換掉這一則」。")
    # The same freeze `handoff_assignment.assign` applies, told before the file is placed.
    if launch.launch_set(conn, org, brand, campaign_id) and not launch.is_stale(
        conn, org, brand, campaign_id
    ):
        raise ValueError("首次投放清單已核准，不能改寫原交接素材；請先處理原核准清單。")
    placement = user_assets.attach_selected(conn, org, brand, campaign_id, body, actor)
    conn.execute(
        "UPDATE ads_ad SET slot_placement_id=%s,updated_at=now() WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND id=%s",
        (placement["id"], org, brand, campaign_id, ad_id),
    )
    conn.commit()
    settle(conn, org, brand, campaign_id, placement["id"])
    return {
        "placement": user_assets.placement(conn, org, brand, campaign_id, placement["id"]),
        "slots": read(conn, org, brand, campaign_id),
    }
