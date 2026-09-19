"""Compatibility seam for the existing cold-start manual handoff, never a platform write."""

from app import workbench
from app.ads import assets, change_control, handoff_assignment, manual_settings, month_budget, plan
from app.ads import change_control_data as data
from app.ads import repository as campaigns
from app.core import approval, db, settings


def snapshot(conn, org, brand, campaign_id, *, validate_material=False):
    campaign = campaigns.campaign_detail(conn, org, brand, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    fields = (
        "id",
        "name",
        "goal_text",
        "objective",
        "success_metric",
        "success_target",
        "start_date",
        "end_date",
        "budget_planned",
        "channel",
        "external_id",
    )
    result = {key: campaign.get(key) for key in fields}
    result["month"] = settings.today_for_org(conn, org_id=org).strftime("%Y-%m")
    result["groups"] = [
        {
            **{
                key: group.get(key)
                for key in ("id", "name", "daily_budget", "start_date", "end_date", "external_id")
            },
            "ads": [
                {
                    **{
                        key: ad.get(key)
                        for key in (
                            "id",
                            "name",
                            "external_id",
                            "asset_ready",
                            "copy_text",
                            "image_prompt_text",
                        )
                    },
                    "material_assignment": handoff_assignment.material_snapshot(
                        conn, org, brand, campaign_id, ad, validate=validate_material
                    ),
                }
                for ad in group.get("ads", [])
            ],
        }
        for group in campaign["groups"]
    ]
    result["manual_settings"] = [
        {"id": group["id"], "values": group["values"]}
        for group in manual_settings.handoff(campaign)["groups"]
    ]
    source_ref = {"ads_campaign_id": campaign_id}
    legacy_ads = {
        ad["id"]: ad
        for group in result["groups"]
        for ad in group["ads"]
        if not ad["material_assignment"]
    }
    result["outputs"] = []
    # Match the manual checklist's selected brief for each unassigned planned ad.
    briefs_by_ad = {
        (brief.get("source_ref") or {}).get("ads_ad_id"): brief
        for brief in workbench.briefs_for_source(
            conn, org, brand, assets.PACK_SOURCE_KIND, source_ref
        )
        if (brief.get("source_ref") or {}).get("ads_ad_id") in legacy_ads
    }
    for ad_id, ad in legacy_ads.items():
        brief = briefs_by_ad.get(ad_id)
        if brief is None:
            continue
        for part in ("copy", "image_prompt"):
            output = workbench.adopted_output(conn, org, brand, brief["id"], part)
            if not output:
                continue
            body = output.get("body_json") or {}
            if part == "copy":
                cards = body.get("sets")
                text = (
                    cards[0].get("body")
                    if (isinstance(cards, list) and cards and isinstance(cards[0], dict))
                    else None
                )
            else:
                text = body.get("text") if output.get("is_adopted") else None
            if not isinstance(text, str) or not text:
                continue
            ad["copy_text" if part == "copy" else "image_prompt_text"] = text
            result["outputs"].append(
                {
                    "ad_id": ad_id,
                    "brief_id": brief["id"],
                    "part": part,
                    "id": output["id"],
                    "text": text,
                }
            )
    return result


def publish(conn, org, brand, campaign_id, actor, operation_id, expected_hash):
    if not operation_id or not expected_hash:
        raise ValueError("請重新檢視手動交接內容，再核准這次操作。")
    data.operation(operation_id)
    try:
        data.lock(conn, org, brand)
        request_hash = data.digest(
            {"campaign_id": campaign_id, "content_hash": expected_hash, "kind": "launch"}
        )
        prior = conn.execute(
            "SELECT id,campaign_id,request_hash FROM ads_change_set WHERE "
            "org_id=%s AND brand_id=%s AND operation_id=%s",
            (org, brand, operation_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash or prior["campaign_id"] != campaign_id:
                raise ValueError("同一次操作的內容已改變，請重新檢視。")
            conn.commit()
            return {"ok": True, "change_set_id": prior["id"]}
        frozen = snapshot(conn, org, brand, campaign_id, validate_material=True)
        content_hash = data.digest(frozen)
        if expected_hash != content_hash:
            raise ValueError("計畫、素材或月份已改變，請重新檢視後核准。")
        if conn.execute(
            "SELECT id FROM ads_action WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND kind='publish' AND change_set_id IS NOT NULL "
            "AND verification_state IN ('pending','reported','unknown') LIMIT 1",
            (org, brand, campaign_id),
        ).fetchone():
            raise ValueError("此計畫已有人工上架清單待核對，請先處理原清單。")
        daily = campaigns.group_budget_total(conn, org, brand, campaign_id)
        item = {
            "id": db.new_id("adx"),
            "kind": "launch",
            "target_id": campaign_id,
            "target": {"id": campaign_id, "native_kind": "campaign", "name": frozen["name"]},
            "before": {},
            "after": {
                "daily_amount": daily,
                "start_date": frozen["start_date"],
                "end_date": frozen["end_date"],
            },
            "reason": "核准此計畫的人工上架交接；尚未在平台建立或發布。",
            "context": data.context(frozen),
        }
        month_budget.preflight(conn, org, brand, frozen["month"], [item])
        set_id = db.new_id("acs")
        conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                set_id,
                org,
                brand,
                campaign_id,
                operation_id,
                request_hash,
                content_hash,
                "首次投放人工交接",
                frozen["month"],
                db.jsonb({"items": [item], "launch_snapshot": frozen}),
                actor,
            ),
        )
        detail = campaigns.campaign_detail(conn, org, brand, campaign_id)
        assert detail is not None
        approval_id = approval.approve(
            conn,
            org_id=org,
            brand_id=brand,
            scope_type=plan.APPROVAL_SCOPE_TYPE,
            scope_ref=campaign_id,
            content_hash=content_hash,
            amount=detail["budget_total"] or daily,
            max_daily_amount=daily,
            actor=actor,
            commit=False,
        )
        change_control._insert_actions(
            conn,
            org,
            brand,
            campaign_id,
            {
                "id": set_id,
                "month": frozen["month"],
                "items": [item],
                "operation_id": operation_id,
                "content_hash": content_hash,
            },
            actor,
        )
        conn.execute(
            "UPDATE ads_change_set SET status='approved',approval_id=%s,approved_at=now() "
            "WHERE id=%s",
            (approval_id, set_id),
        )
        from app.ads import handoff_data

        handoff_data.install_launch(conn, org, brand, campaign_id, set_id, item["id"], frozen)
        conn.commit()
        return {"ok": True, "change_set_id": set_id}
    except Exception:
        conn.rollback()
        raise
