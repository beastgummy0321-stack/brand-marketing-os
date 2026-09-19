"""Trace a new native test to its approved source review, without inventing a previous round."""


def source_review(conn, org, brand, campaign, entity_id):
    rows = conn.execute(
        "SELECT h.id,h.change_set_id,h.action_id,h.status,h.evidence_json,h.reported_at,"
        "h.observed_at,c.plan_json,a.first_observed_at FROM ads_handoff_item h "
        "JOIN ads_change_set c ON c.id=h.change_set_id AND c.org_id=h.org_id "
        "AND c.brand_id=h.brand_id AND c.campaign_id=h.campaign_id "
        "JOIN ads_action a ON a.id=h.action_id AND a.org_id=h.org_id "
        "AND a.brand_id=h.brand_id AND a.campaign_id=h.campaign_id "
        "WHERE h.org_id=%s AND h.brand_id=%s AND h.campaign_id=%s AND h.entity_id=%s "
        "AND a.kind='publish' AND c.status='approved' "
        "AND c.plan_json->'items' @> '[{\"kind\":\"new_ad\"}]'::jsonb "
        "ORDER BY h.id LIMIT 2",
        (org, brand, campaign, entity_id),
    ).fetchall()
    if len(rows) != 1:
        return None
    item = rows[0]
    plan = item["plan_json"]
    if not plan.get("review_id"):
        return None
    review = conn.execute(
        "SELECT * FROM ads_review_round WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND id=%s",
        (org, brand, campaign, plan["review_id"]),
    ).fetchone()
    if (
        not review
        or review["entity_id"] == entity_id
        or review["entity_id"] != plan.get("source_entity_id")
        or review["evidence_hash"] != plan.get("review_evidence_hash")
    ):
        return None
    recommendation = next(
        (
            r
            for r in review["result_json"].get("recommendations", [])
            if r["id"] == plan.get("recommendation_id")
            and r["recommendation"] == "new_test"
            and r["target_id"] == review["entity_id"]
        ),
        None,
    )
    if not recommendation:
        return None
    evidence = item["evidence_json"] or {}
    return {
        "relation": "new_test",
        "review_id": review["id"],
        "source_entity_id": review["entity_id"],
        "evidence_hash": review["evidence_hash"],
        "recommendation_id": recommendation["id"],
        "handoff_item_id": item["id"],
        "change_set_id": item["change_set_id"],
        "action_id": item["action_id"],
        "window": {"start": review["window_start"], "end": review["window_end"]},
        "recommendation": {
            k: recommendation.get(k)
            for k in ("recommendation", "hypothesis", "risks", "next_step", "evidence_refs")
        },
        "current": review["evidence_json"]["current"],
        "material": {
            k: plan.get(k)
            for k in ("material_task_id", "material_revision", "material_placement_source")
        },
        "readback": {
            "state": item["status"],
            "reported_at": item["reported_at"],
            "first_observed_at": item["first_observed_at"],
            "entity_exists": evidence.get("entity_exists"),
            "setting_matches": evidence.get("setting_matches"),
            "material_evidence": evidence.get("material_evidence", "unknown"),
            "delivery_confirmed": False,
        },
        "limitations": [
            "這是另一則廣告的新測試來源，不是同則廣告的前回，不能證明素材因果。",
            "讀到平台物件不等於已投遞；素材相符與成效仍需各自確認。",
        ],
    }


def action_summary(action):
    """Keep action identifiers and decision-bearing readback, never raw HTTP parent snapshots."""
    evidence = action.get("evidence_json") or {}
    return {
        **{
            k: action.get(k)
            for k in ("id", "kind", "verification_state", "reported_at", "first_observed_at")
        },
        "before_json": action.get("before_json"),
        "after_json": action.get("after_json"),
        "evidence_json": {
            k: evidence.get(k)
            for k in (
                "entity_exists",
                "setting_matches",
                "material_evidence",
                "delivery_confirmed",
                "actual",
                "differences",
                "observed",
                "expected",
                "media_identity_matches",
                "budget_conditions",
            )
        },
        "raw_evidence": "保留於原始操作記錄；此處只帶判讀摘要。",
    }
