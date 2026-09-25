"""Approved handoff nodes and their evidence, without another native-object registry."""

from app.ads import change_control_data as changes
from app.ads import launch_settings, manual_settings
from app.ads import user_assets_repository as assets
from app.core import db


def insert(
    conn,
    org,
    brand,
    campaign,
    set_id,
    action_id,
    kind,
    planned_id,
    name,
    expected,
    *,
    parent_id=None,
    placement_id=None,
    revision=None,
):
    row = conn.execute(
        "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,action_id,"
        "planned_kind,planned_id,name,parent_item_id,placement_id,"
        "placement_revision,expected_json) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(org_id,brand_id,campaign_id,change_set_id,planned_kind,planned_id) "
        "DO UPDATE SET planned_id=EXCLUDED.planned_id RETURNING id",
        (
            db.new_id("ahi"),
            org,
            brand,
            campaign,
            set_id,
            action_id,
            kind,
            planned_id,
            name,
            parent_id,
            placement_id,
            revision,
            db.jsonb(expected),
        ),
    ).fetchone()
    return row["id"]


def install_launch(conn, org, brand, campaign, set_id, action_id, frozen):
    root = insert(
        conn,
        org,
        brand,
        campaign,
        set_id,
        action_id,
        "campaign",
        campaign,
        frozen["name"],
        {"objective": frozen.get("objective")},
    )
    manual = {g["id"]: g["values"] for g in frozen.get("manual_settings", [])}
    for group in frozen["groups"]:
        expected = {
            "budget_type": "daily",
            "budget_amount": group.get("daily_budget"),
            "start_date": group.get("start_date") or frozen.get("start_date"),
            "end_date": group.get("end_date") or frozen.get("end_date"),
            "manual_settings": {
                f["key"]: manual.get(group["id"], {}).get(f["key"])
                for f in manual_settings.FIELDS
                if f["required"]
            },
        }
        # F29 Contract I: each ad set is read back against the frozen launch settings (a launch
        # approved before they existed froze none and compares none).
        if frozen.get("launch_settings") is not None:
            expected["launch_settings"] = launch_settings.group_subset(frozen["launch_settings"])
        group_id = insert(
            conn,
            org,
            brand,
            campaign,
            set_id,
            action_id,
            "group",
            group["id"],
            group["name"],
            expected,
            parent_id=root,
        )
        for ad in group.get("ads", []):
            material = ad.get("material_assignment") or {}
            copy = material.get("copy_fields") or {}
            expected = {"copy_text": ad.get("copy_text"), "material_required": True}
            if frozen.get("launch_settings") is not None:
                expected["launch_settings"] = launch_settings.ad_subset(frozen["launch_settings"])
            if material:
                expected.update(
                    copy={
                        "title": copy.get("headline"),
                        "body": copy.get("body"),
                        "description": copy.get("description"),
                    },
                    asset_sha256=material["asset_sha256"],
                    copy_hash=material["copy_hash"],
                )
            insert(
                conn,
                org,
                brand,
                campaign,
                set_id,
                action_id,
                "ad",
                ad["id"],
                ad["name"],
                expected,
                parent_id=group_id,
                placement_id=material.get("placement_id"),
                revision=material.get("placement_revision"),
            )


def carry_launch(conn, org, brand, campaign, old_set, new_set, action_id):
    """Re-approval (F28 "Stale launch"): the new set's items were just installed pending. An item
    whose expected fields and material are unchanged keeps the old item's platform binding,
    verification and evidence; a changed item stays pending with no binding; a removed one is
    simply not in the new set. The old items keep their rows; only the binding moves (one
    platform object answers one live handoff item), recorded in their evidence."""
    rows = conn.execute(
        "SELECT * FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND change_set_id IN (%s,%s)",
        (org, brand, campaign, old_set, new_set),
    ).fetchall()
    old = {(r["planned_kind"], r["planned_id"]): r for r in rows if r["change_set_id"] == old_set}
    carried = []
    for new in (r for r in rows if r["change_set_id"] == new_set):
        previous = old.get((new["planned_kind"], new["planned_id"]))
        if previous is None:
            continue
        same = (previous["expected_json"], previous["placement_id"], previous["placement_revision"])
        if same != (new["expected_json"], new["placement_id"], new["placement_revision"]):
            continue
        carried.append((previous, new))
    for previous in old.values():
        if previous["entity_id"] is not None:
            conn.execute(
                "UPDATE ads_handoff_item SET entity_id=NULL,"
                "evidence_json=evidence_json || %s::jsonb,updated_at=now() WHERE id=%s",
                (
                    db.jsonb({"superseded_by": new_set, "entity_id": previous["entity_id"]}),
                    previous["id"],
                ),
            )
    for previous, new in carried:
        # A readback that went stale because of the plan change proved nothing about this item;
        # it keeps the binding and waits for a fresh check.
        keep = previous["status"] != "stale"
        conn.execute(
            "UPDATE ads_handoff_item SET entity_id=%s,status=%s,evidence_json=%s,"
            "reported_at=%s,observed_at=%s,updated_at=now() WHERE id=%s",
            (
                previous["entity_id"],
                previous["status"] if keep else "pending",
                db.jsonb(previous["evidence_json"] if keep else {}),
                previous["reported_at"] if keep else None,
                previous["observed_at"] if keep else None,
                new["id"],
            ),
        )
    peers = conn.execute(
        "SELECT status FROM ads_handoff_item WHERE action_id=%s", (action_id,)
    ).fetchall()
    if peers and all(r["status"] == "confirmed" for r in peers):
        conn.execute(
            "UPDATE ads_action SET verification_state='confirmed',verified_at=now(),"
            "first_observed_at=COALESCE(first_observed_at,now()),evidence_json=%s WHERE id=%s",
            (
                db.jsonb(
                    {
                        "setting_matches": True,
                        "delivery_confirmed": False,
                        "message": "重新核准後各項沿用先前核對結果；不代表已投遞或成效改善。",
                    }
                ),
                action_id,
            ),
        )


def get(conn, org, brand, campaign, item_id):
    changes.campaign(conn, org, brand, campaign)
    row = conn.execute(
        "SELECT h.*,e.platform,e.source_account,e.native_kind,e.native_id,"
        "p.name AS expected_parent_name FROM ads_handoff_item h "
        "LEFT JOIN ads_external_entity e ON e.id=h.entity_id "
        "LEFT JOIN ads_handoff_item p ON p.id=h.parent_item_id "
        "WHERE h.org_id=%s AND h.brand_id=%s AND h.campaign_id=%s AND h.id=%s",
        (org, brand, campaign, item_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到此活動的人工交接項目。")
    result = dict(row)
    evidence = result["evidence_json"]
    result.update(
        entity_exists=evidence.get("entity_exists", False),
        setting_matches=evidence.get("setting_matches"),
        material_evidence=evidence.get("material_evidence", "unknown"),
    )
    return result


def workspace(conn, org, brand, campaign):
    # Lazy: `change_control_launch` imports this module inside its own functions, and
    # `handoff_check` imports this module.
    from app.ads import change_control_launch, handoff_check

    changes.campaign(conn, org, brand, campaign)
    rows = conn.execute(
        # A re-approved launch leaves its superseded set's items as history, not work.
        "SELECT h.id FROM ads_handoff_item h JOIN ads_change_set c ON c.id=h.change_set_id "
        "AND c.org_id=h.org_id AND c.brand_id=h.brand_id AND c.campaign_id=h.campaign_id "
        "WHERE h.org_id=%s AND h.brand_id=%s AND h.campaign_id=%s AND c.status<>'superseded' "
        "ORDER BY h.created_at,h.id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    placements = assets.list_placements(conn, org, brand, campaign)
    destinations = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind<>'ad' ORDER BY name,id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    return {
        "items": [get(conn, org, brand, campaign, r["id"]) for r in rows[:500]],
        "items_truncated": len(rows) > 500,
        "ready_placements": [
            {k: p[k] for k in ("id", "revision", "filename", "purpose", "destination_entity_id")}
            for p in placements
            if p["is_current"] and p["confirmed_at"] and p["asset_status"] == "ready"
        ],
        "destinations": [dict(r) for r in destinations[:500]],
        "destinations_truncated": len(destinations) > 500,
        "launch_stale": change_control_launch.stale(conn, org, brand, campaign),
        "settings_readback": handoff_check.settings_readback(conn, org, brand, campaign),
        "notice": "物件存在、設定相符與素材核對分別記錄；人工交接不代表平台已投遞。",
    }


def report(conn, org, brand, campaign, item_id):
    get(conn, org, brand, campaign, item_id)
    conn.execute(
        "UPDATE ads_handoff_item SET reported_at=COALESCE(reported_at,now()),"
        "status=CASE WHEN status IN ('pending','unknown') THEN 'reported' ELSE status END "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
        (org, brand, campaign, item_id),
    )
    conn.commit()
    return get(conn, org, brand, campaign, item_id)
