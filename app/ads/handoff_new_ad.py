"""A confirmed placement becomes a separate manually created ad, under existing budget."""

import json

from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as changes
from app.ads import handoff_data, lifecycle, material_tasks, review_evidence, review_rounds
from app.core import db, settings
from app.shared.web import to_json_value


def _snapshot(conn, org, brand, campaign, placement_id, revision, destination):
    placement, asset = bindings.confirmed(
        conn, org, brand, campaign, placement_id, revision, write=True
    )
    parent = bindings.entity(conn, org, brand, campaign, destination)
    if parent["native_kind"] == "ad" or not parent["parent_native_id"]:
        raise ValueError("請選擇新廣告要加入的既有投放組，活動層不可當成廣告直接父層。")
    root = bindings.root(conn, org, brand, campaign, parent)
    owner = parent if parent.get("budget_amount") is not None else root
    result = {
        "placement_id": placement_id,
        "revision": revision,
        "asset_id": asset["id"],
        "sha256": asset["sha256"],
        "filename": asset["filename"],
        "copy": bindings.effective_copy(placement),
        "start_date": placement["start_date"],
        "end_date": placement["end_date"],
        "destination": {
            k: parent.get(k)
            for k in (
                "id",
                "platform",
                "source_account",
                "native_kind",
                "native_id",
                "parent_native_id",
                "parent_native_kind",
                "native_status",
            )
        },
        "budget_owner": {
            k: owner.get(k)
            for k in (
                "id",
                "budget_type",
                "budget_amount",
                "currency",
                "native_status",
                "start_date",
                "end_date",
            )
        },
        "context": changes.context(changes.campaign(conn, org, brand, campaign)),
    }
    return json.loads(json.dumps(result, default=to_json_value)), parent


def _review(conn, org, brand, campaign, review_id, recommendation_id):
    if not review_id and not recommendation_id:
        return {}
    if not review_id or not recommendation_id:
        raise ValueError("檢討與建議識別必須成對提供。")
    review = review_rounds.get(conn, org, brand, campaign, review_id)
    rec = next(
        (
            r
            for r in review["result_json"].get("recommendations", [])
            if r["id"] == recommendation_id and r["recommendation"] == "new_test"
        ),
        None,
    )
    if (
        review["status"] not in {"ready", "completed"}
        or rec is None
        or rec.get("target_id") != review["entity_id"]
    ):
        raise ValueError("請選擇已可採用的新測試建議；修改原廣告文案不會建立新廣告。")
    source = bindings.entity(conn, org, brand, campaign, review["entity_id"])
    current = review_evidence.premise(source, changes.campaign(conn, org, brand, campaign))
    if changes.digest(current) != changes.digest(review["evidence_json"]["premise"]):
        raise ValueError("檢討所依據的廣告或目標已變更，請先重新檢討。")
    if (settings.today_for_org(conn, org_id=org) - review["window_end"]).days > 30:
        raise ValueError("此檢討已超過三十日，請先重看近期資料。")
    return {
        "review_id": review_id,
        "recommendation_id": recommendation_id,
        "review_evidence_hash": review["evidence_hash"],
        "source_entity_id": review["entity_id"],
    }


def _active_ad(conn, org, brand, campaign, entity_id):
    try:
        ad = bindings.entity(conn, org, brand, campaign, entity_id)
    except ValueError:
        return False
    return ad["native_kind"] == "ad" and lifecycle.ad_running(ad) is True


def create(conn, org, brand, campaign, payload, actor):
    changes.campaign(conn, org, brand, campaign)
    operation = changes.operation(payload["operation_id"])
    month = changes.month(payload["month"])
    if not payload.get("reason", "").strip() or not payload.get("title", "").strip():
        raise ValueError("請填寫新廣告名稱與新增理由。")
    changes.lock(conn, org, brand)
    request_hash = changes.digest(payload)
    old = conn.execute(
        "SELECT id,request_hash FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND operation_id=%s",
        (org, brand, operation),
    ).fetchone()
    if old:
        if old["request_hash"] != request_hash:
            raise ValueError("同一次操作內容不同，請重新建立清單。")
        conn.commit()
        return changes.get(conn, org, brand, campaign, old["id"])
    frozen, parent = _snapshot(
        conn,
        org,
        brand,
        campaign,
        payload["placement_id"],
        payload["revision"],
        payload["destination_entity_id"],
    )
    reference = placement_reference(
        conn, org, brand, campaign, payload["placement_id"], payload["revision"]
    )
    replaces_entity_id = payload.get("replaces_entity_id")
    if replaces_entity_id is not None:
        old_ad = bindings.entity(conn, org, brand, campaign, replaces_entity_id)
        if old_ad["native_kind"] != "ad" or lifecycle.ad_running(old_ad) is not True:
            raise ValueError("要取代的廣告必須是本活動目前正在投放中的廣告，請重新選擇。")
    elif reference.get("material_task_id"):
        # Contract H: a "replace this ad" request carries its ad into the new-ad handoff. The
        # default applies only while that ad still runs; a paused ad has nothing left to replace.
        bound = material_tasks.get(conn, org, brand, campaign, reference["material_task_id"])
        old_ad = (bound["replaces"] or {}).get("entity_id")
        if old_ad and _active_ad(conn, org, brand, campaign, old_ad):
            replaces_entity_id = old_ad
    explicit = _review(
        conn, org, brand, campaign, payload.get("review_id"), payload.get("recommendation_id")
    )
    if (
        explicit
        and reference.get("review_id")
        and any(explicit.get(k) != reference.get(k) for k in ("review_id", "recommendation_id"))
    ):
        raise ValueError("選定素材與指定檢討來源不同，請先確認素材任務的來源。")
    reference.update(explicit)
    known_ads = conn.execute(
        "SELECT native_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND platform=%s AND source_account=%s AND native_kind='ad' LIMIT 501",
        (org, brand, campaign, parent["platform"], parent["source_account"]),
    ).fetchall()
    if len(known_ads) > 500:
        raise ValueError("此活動既有廣告超出交接範圍，請先縮小新測試範圍。")
    if conn.execute(
        "SELECT id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND placement_id=%s AND status<>'stale' LIMIT 1",
        (org, brand, campaign, payload["placement_id"]),
    ).fetchone():
        raise ValueError("此素材安排已有核准的新廣告交接，請先核對原項目。")
    item = {
        "id": db.new_id("adx"),
        "kind": "new_ad",
        "target_id": payload["placement_id"],
        "target": {
            "id": payload["placement_id"],
            "native_kind": "ad",
            "name": frozen["filename"] + "（新廣告）",
            "platform": parent["platform"],
            "source_account": parent["source_account"],
            "currency": frozen["budget_owner"]["currency"],
        },
        "before": {},
        "after": {
            "placement_id": payload["placement_id"],
            "placement_revision": payload["revision"],
            "destination_entity_id": parent["id"],
            "daily_amount": 0,
            "budget_basis": "existing_parent",
            "start_date": frozen["start_date"],
            "end_date": frozen["end_date"],
        },
        "reason": payload["reason"],
        "context": frozen["context"],
        "premise_hash": changes.digest(frozen),
        "handoff_snapshot": frozen,
        "source_entity_id": reference.get("source_entity_id"),
        "existing_native_ids": [r["native_id"] for r in known_ads],
        "replaces_entity_id": replaces_entity_id,
    }
    content = {"title": payload["title"], "month": month, "items": [item], **reference}
    set_id = db.new_id("acs")
    conn.execute(
        "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
        "content_hash,title,month,plan_json,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            set_id,
            org,
            brand,
            campaign,
            operation,
            request_hash,
            changes.digest(content),
            payload["title"],
            month,
            db.jsonb({"items": [item], **reference}),
            actor,
        ),
    )
    conn.commit()
    return changes.get(conn, org, brand, campaign, set_id)


def placement_reference(conn, org, brand, campaign, placement_id, revision):
    rows = conn.execute(
        "SELECT DISTINCT task_id FROM ads_material_revision WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND spec_json->>'placement_id'=%s "
        "AND (spec_json->>'placement_revision')::integer<=%s LIMIT 2",
        (org, brand, campaign, placement_id, revision),
    ).fetchall()
    if not rows:
        return {}
    if len(rows) != 1:
        raise ValueError("此素材安排有多個任務來源，無法確定檢討關係；請重新選定素材。")
    task_id = rows[0]["task_id"]
    conn.execute("SELECT id FROM ads_material_task WHERE id=%s FOR SHARE", (task_id,))
    task = material_tasks.open_task(conn, org, brand, campaign, task_id)
    source_revision = task.get("placement_revision")
    if (
        task.get("placement_id") != placement_id
        or source_revision is None
        or source_revision > revision
    ):
        raise ValueError("素材任務已修訂或另選成品，請回素材重新確認安排後建立交接。")
    from app.ads import user_assets_repository as assets

    source = assets.placement(conn, org, brand, campaign, placement_id, source_revision)
    applied = assets.placement(conn, org, brand, campaign, placement_id, revision)
    if source["asset_id"] != applied["asset_id"]:
        raise ValueError("素材原檔已改變，不能沿用原選定成品的來源關係。")
    return {
        "material_task_id": task_id,
        "material_revision": task["revision"],
        "material_content_hash": task["content_hash"],
        "material_placement_source": {
            "placement_id": placement_id,
            "selected_revision": source_revision,
            "applied_revision": revision,
            "asset_id": applied["asset_id"],
            "candidate_id": task.get("selected_candidate_id"),
            "selected_copy_hash": bindings.digest(bindings.effective_copy(source)),
            "applied_copy_hash": bindings.digest(bindings.effective_copy(applied)),
            "relation": "selected_version" if source_revision == revision else "revised_placement",
        },
        **_review(conn, org, brand, campaign, task.get("review_id"), task.get("recommendation_id")),
    }


def validate_reference(conn, org, brand, campaign, change_set):
    plan = change_set["plan_json"]
    for item in change_set["items"]:
        if item["kind"] != "new_ad":
            continue
        after = item["after"]
        current = placement_reference(
            conn, org, brand, campaign, after["placement_id"], after["placement_revision"]
        )
        for key in (
            "material_task_id",
            "material_revision",
            "material_content_hash",
            "material_placement_source",
        ):
            if current.get(key) != plan.get(key):
                raise ValueError("素材來源版本已變更，請重新建立交接清單。")
        review = _review(
            conn, org, brand, campaign, plan.get("review_id"), plan.get("recommendation_id")
        )
        if review.get("review_evidence_hash") != plan.get("review_evidence_hash"):
            raise ValueError("檢討證據已變更，請重新建立交接清單。")


def validate_approval(conn, org, brand, campaign, item):
    after = item["after"]
    current, parent = _snapshot(
        conn,
        org,
        brand,
        campaign,
        after["placement_id"],
        after["placement_revision"],
        after["destination_entity_id"],
    )
    if changes.digest(current) != item["premise_hash"]:
        raise ValueError("新廣告素材、父層或預算條件已改變，請重新建立交接清單。")
    budget = current["budget_owner"]
    # The budget owner is the parent or its root, on the parent's own platform.
    if (
        lifecycle.ad_running(parent) is not True
        or lifecycle.ad_running({**budget, "platform": parent["platform"]}) is not True
        or budget["budget_type"] != "daily"
        or budget["budget_amount"] is None
        or budget["budget_amount"] <= 0
        or not budget["currency"]
    ):
        raise ValueError("既有父層的持續投放與預算控制尚未核實，不能假定新增廣告沒有新增花費。")
    if conn.execute(
        "SELECT id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND placement_id=%s AND status<>'stale' LIMIT 1",
        (org, brand, campaign, after["placement_id"]),
    ).fetchone():
        raise ValueError("同一素材安排已有新廣告待核對，不可重複核准。")


def install(conn, org, brand, campaign, set_id, item):
    frozen, after = item["handoff_snapshot"], item["after"]
    copy = frozen["copy"]
    expected = {
        "copy": {
            "title": copy.get("headline"),
            "body": copy.get("body"),
            "description": copy.get("description"),
        },
        "destination_entity_id": after["destination_entity_id"],
        "asset_sha256": frozen["sha256"],
        "copy_hash": bindings.digest(copy),
        "source_entity_id": item.get("source_entity_id"),
        "existing_native_ids": item.get("existing_native_ids", []),
        "material_required": True,
    }
    return handoff_data.insert(
        conn,
        org,
        brand,
        campaign,
        set_id,
        item["id"],
        "ad",
        item["target_id"],
        item["target"]["name"],
        expected,
        placement_id=after["placement_id"],
        revision=after["placement_revision"],
    )
