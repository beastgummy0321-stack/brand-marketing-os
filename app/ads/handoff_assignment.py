"""Explicit local planned-ad material selection, frozen by the existing launch approval."""

from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as changes
from app.ads import user_assets_repository as assets


def material_snapshot(conn, org, brand, campaign, ad, *, validate=False):
    placement_id = ad.get("material_placement_id")
    revision = ad.get("material_placement_revision")
    if placement_id is None:
        return None
    if validate:
        placement, asset = bindings.confirmed(
            conn, org, brand, campaign, placement_id, revision, write=True
        )
    else:
        placement = assets.placement(conn, org, brand, campaign, placement_id, revision)
        asset = assets.get_asset(conn, org, brand, placement["asset_id"])
    confirmed = bool(
        placement["is_current"] and placement["confirmed_at"] and asset["status"] == "ready"
    )
    copy = bindings.effective_copy(placement)
    return {
        "placement_id": placement_id,
        "placement_revision": revision,
        "asset_id": asset["id"],
        "filename": asset["filename"],
        "asset_sha256": asset["sha256"],
        "copy_fields": copy,
        "copy_hash": bindings.digest(copy),
        "assignment_status": "confirmed" if confirmed else "stale",
        "reason": None if confirmed else "指定素材版本已修訂、尚未確認或原檔未就緒，請重新指派。",
    }


def workspace(conn, org, brand, campaign):
    changes.campaign(conn, org, brand, campaign)
    rows = conn.execute(
        "SELECT a.*,g.name AS group_name FROM ads_ad a JOIN ads_delivery_group g "
        "ON g.id=a.group_id AND g.org_id=a.org_id AND g.brand_id=a.brand_id "
        "AND g.campaign_id=a.campaign_id WHERE a.org_id=%s AND a.brand_id=%s "
        "AND a.campaign_id=%s ORDER BY g.created_at,g.id,a.created_at,a.id",
        (org, brand, campaign),
    ).fetchall()
    planned = []
    for row in rows:
        material = material_snapshot(conn, org, brand, campaign, row) or {}
        planned.append(
            {
                **{k: row[k] for k in ("id", "name", "group_id", "group_name")},
                "placement_id": material.get("placement_id"),
                "placement_revision": material.get("placement_revision"),
                "assignment_status": material.get("assignment_status", "unassigned"),
                "filename": material.get("filename"),
                "copy_fields": material.get("copy_fields", {}),
                "reason": material.get("reason"),
            }
        )
    return {
        "planned_ads": planned,
        "ready_placements": [
            {
                "id": p["id"],
                "revision": p["revision"],
                "filename": p["filename"],
                "copy_fields": bindings.effective_copy(p),
            }
            for p in assets.list_placements(conn, org, brand, campaign)
            if p["is_current"] and p["confirmed_at"] and p["asset_status"] == "ready"
        ],
    }


def assign(conn, org, brand, campaign, ad_id, placement_id, revision):
    changes.lock(conn, org, brand)
    context = changes.campaign(conn, org, brand, campaign)
    if context["origin"] != "internal" or context["status"] == "closed":
        raise ValueError("只有未結案的內部計畫可以指派首次投放素材。")
    ad = conn.execute(
        "SELECT a.id FROM ads_ad a JOIN ads_delivery_group g ON g.id=a.group_id "
        "AND g.org_id=a.org_id AND g.brand_id=a.brand_id AND g.campaign_id=a.campaign_id "
        "WHERE a.org_id=%s AND a.brand_id=%s AND a.campaign_id=%s AND a.id=%s FOR UPDATE OF a",
        (org, brand, campaign, ad_id),
    ).fetchone()
    if not ad:
        raise ValueError("找不到此品牌活動的計畫廣告。")
    # Lazy: `change_control_launch` imports this module at load time.
    from app.ads import change_control_launch

    # An approved launch freezes its materials -- unless the plan already changed since (F28
    # "Stale launch"): then re-pointing a revised material is how the user reaches a plan that
    # can be re-approved, instead of a dead end between a refused re-approval and this refusal.
    if change_control_launch.launch_set(
        conn, org, brand, campaign
    ) and not change_control_launch.is_stale(conn, org, brand, campaign):
        raise ValueError("首次投放清單已核准，不能改寫原交接素材；請先處理原核准清單。")
    if (placement_id is None) != (revision is None):
        raise ValueError("素材安排與版本必須一起提供，或一起清除。")
    if placement_id is not None:
        bindings.confirmed(conn, org, brand, campaign, placement_id, revision, write=True)
    conn.execute(
        "UPDATE ads_ad SET material_placement_id=%s,material_placement_revision=%s,"
        "updated_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
        (placement_id, revision, org, brand, campaign, ad_id),
    )
    conn.commit()
    return workspace(conn, org, brand, campaign)
