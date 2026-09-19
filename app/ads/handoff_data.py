"""Approved handoff nodes and their evidence, without another native-object registry."""

from app.ads import change_control_data as changes
from app.ads import manual_settings
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
    changes.campaign(conn, org, brand, campaign)
    rows = conn.execute(
        "SELECT id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "ORDER BY created_at,id LIMIT 501",
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
