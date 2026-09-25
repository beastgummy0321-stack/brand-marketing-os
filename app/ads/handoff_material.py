"""Trace a selected copy-task revision into the existing copy approval contract."""

from app.ads import material_tasks


def reference(conn, org, brand, campaign, task_id, revision, items):
    if task_id is None and revision is None:
        return {}
    if not task_id or type(revision) is not int or revision < 1:
        raise ValueError("素材任務與版本必須成對提供。")
    conn.execute(
        "SELECT id FROM ads_material_task WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND id=%s FOR SHARE",
        (org, brand, campaign, task_id),
    )
    task = material_tasks.open_task(conn, org, brand, campaign, task_id)
    if task["mode"] != "copy" or task["revision"] != revision:
        raise ValueError("素材文案版本已變更，請回素材選定目前版本後重新建立清單。")
    copy = task["copy_fields"]
    selected = {
        key: copy[source]
        for key, source in (("title", "headline"), ("body", "body"))
        if copy.get(source)
    }
    if not selected or not items:
        raise ValueError("素材尚未選定可修改原廣告的文案。")
    target = (task.get("review_context") or {}).get("entity_id")
    for item in items:
        if item["kind"] != "copy" or target and item["target_id"] != target:
            raise ValueError("此文案素材僅適用原檢討廣告的文案調整。")
        if not item["after"] or any(selected.get(k) != v for k, v in item["after"].items()):
            raise ValueError("變更內容與選定素材文案不同；請先回素材修訂版本，再建立清單。")
    return {
        "material_task_id": task_id,
        "material_revision": revision,
        "material_content_hash": task["content_hash"],
        "material_copy_source": {
            k: task["prompt"].get(k)
            for k in ("source", "set_id", "version_id", "card_index", "part")
        },
        "material_review_id": task.get("review_id"),
        "material_recommendation_id": task.get("recommendation_id"),
    }


def validate_approval(conn, org, brand, campaign, change_set):
    if any(item["kind"] == "new_ad" for item in change_set["items"]):
        from app.ads import handoff_new_ad

        handoff_new_ad.validate_reference(conn, org, brand, campaign, change_set)
        return
    plan = change_set["plan_json"]
    if not plan.get("material_task_id"):
        return
    current = reference(
        conn,
        org,
        brand,
        campaign,
        plan["material_task_id"],
        plan["material_revision"],
        change_set["items"],
    )
    if current["material_content_hash"] != plan["material_content_hash"]:
        raise ValueError("素材內容已變更，請重新檢視文案清單。")
