"""Local change-list approval. No function in this module writes to a platform."""

from datetime import datetime

from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as data
from app.core import approval, db
from app.core.audit import write_audit


def workspace(conn, org, brand, campaign):
    data.campaign(conn, org, brand, campaign)
    targets = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s ORDER BY native_kind,name,id LIMIT 501",
        (org, brand, campaign),
    ).fetchall()
    rows = conn.execute(
        "SELECT id FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s ORDER BY created_at DESC LIMIT 100",
        (org, brand, campaign),
    ).fetchall()
    return {
        "targets": [dict(t) for t in targets[:500]],
        "targets_truncated": len(targets) > 500,
        "change_sets": [data.get(conn, org, brand, campaign, r["id"]) for r in rows],
    }


def create(conn, org, brand, campaign, payload, actor):
    c = data.campaign(conn, org, brand, campaign)
    required = {"operation_id", "title", "items", "month"}
    if (
        not isinstance(payload, dict)
        or not required <= set(payload)
        or set(payload)
        - required
        - {
            "supersedes_id",
            "review_id",
            "recommendation_id",
            "material_task_id",
            "material_revision",
            "source",
        }
    ):
        raise ValueError("請提供完整的變更清單。")
    # F27-I25 / Contract F: `source` only ever names the cleanup proposal match; any other value
    # is refused here too (defence for direct callers that bypass `CreateRequest`'s 422).
    source = payload.get("source")
    if source is not None and source != "cleanup":
        raise ValueError("不支援的清單來源。")
    operation_id, month = data.operation(payload["operation_id"]), data.month(payload["month"])
    if (
        not isinstance(payload["title"], str)
        or not payload["title"].strip()
        or len(payload["title"]) > 200
        or not isinstance(payload["items"], list)
        or not 1 <= len(payload["items"]) <= 30
    ):
        raise ValueError("請提供清單名稱與一到三十項具體變更。")
    request_hash = data.digest({"campaign_id": campaign, **payload})
    try:
        data.lock(conn, org, brand)
        prior = conn.execute(
            "SELECT id,campaign_id,request_hash FROM ads_change_set WHERE "
            "org_id=%s AND brand_id=%s AND operation_id=%s",
            (org, brand, operation_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash or prior["campaign_id"] != campaign:
                raise ValueError("同一次操作的內容已改變，請重新建立清單。")
            result = data.get(conn, org, brand, campaign, prior["id"])
            conn.commit()
            return result
        items = [data.build_item(conn, org, brand, campaign, item, c) for item in payload["items"]]
        if source == "cleanup" and any(i["kind"] != "pause" for i in items):
            raise ValueError("清理清單只能包含暫停項目。")
        from app.ads import review_rounds

        review_reference = review_rounds.proposal_reference(
            conn,
            org,
            brand,
            campaign,
            payload.get("review_id"),
            payload.get("recommendation_id"),
            items,
        )
        from app.ads import handoff_material

        material_reference = handoff_material.reference(
            conn,
            org,
            brand,
            campaign,
            payload.get("material_task_id"),
            payload.get("material_revision"),
            items,
        )
        supersedes = payload.get("supersedes_id")
        if supersedes:
            previous = data.get(conn, org, brand, campaign, supersedes)
            if not data.can_revise(previous):
                raise ValueError("原清單仍有未核對的操作，請先確認目前平台狀態。")
        targets = [(i["kind"], i["target_id"]) for i in items]
        if len(set(targets)) != len(targets):
            raise ValueError("同一物件的相同操作請合併成一項。")
        frozen = {
            "title": payload["title"].strip(),
            "month": month,
            "supersedes_id": supersedes,
            "items": [{k: v for k, v in i.items() if k != "id"} for i in items],
            **review_reference,
            **material_reference,
            # Only present when set, so an existing set created before `source` existed keeps its
            # exact `content_hash`.
            **({"source": source} if source else {}),
        }
        set_id = db.new_id("acs")
        conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                set_id,
                org,
                brand,
                campaign,
                operation_id,
                request_hash,
                data.digest(frozen),
                frozen["title"],
                month,
                db.jsonb(
                    {
                        "items": items,
                        "supersedes_id": supersedes,
                        **review_reference,
                        **material_reference,
                        **({"source": source} if source else {}),
                    }
                ),
                actor,
            ),
        )
        if supersedes:
            for item in previous["items"]:
                if item["verification_state"] in {"stale", "deviated"} or data.unchanged_readback(
                    item
                ):
                    conn.execute(
                        "UPDATE ads_action SET verification_state=CASE "
                        "WHEN verification_state='pending' THEN 'stale' "
                        "ELSE verification_state END,"
                        "evidence_json=evidence_json || %s::jsonb WHERE id=%s "
                        "AND org_id=%s AND brand_id=%s AND change_set_id=%s",
                        (
                            db.jsonb(
                                {
                                    "superseded_by": set_id,
                                    "superseded_message": "改由新清單審核；原核對結果與證據保留。",
                                }
                            ),
                            item["id"],
                            org,
                            brand,
                            supersedes,
                        ),
                    )
            conn.execute(
                "UPDATE ads_change_set SET status='superseded' WHERE org_id=%s "
                "AND brand_id=%s AND campaign_id=%s AND id=%s AND status<>'approved'",
                (org, brand, campaign, supersedes),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return data.get(conn, org, brand, campaign, set_id)


def _insert_actions(conn, org, brand, campaign, current, actor):
    for item in current["items"]:
        kind = {"copy": "creative", "launch": "publish", "new_ad": "publish"}.get(
            item["kind"], item["kind"]
        )
        target_kind = {"adset": "group"}.get(
            item["target"]["native_kind"], item["target"]["native_kind"]
        )
        conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,"
            "kind,before_json,after_json,approved_by,approved_at,change_set_id,"
            "verification_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,'pending')",
            (
                item["id"],
                org,
                brand,
                campaign,
                target_kind,
                item["target_id"],
                kind,
                db.jsonb(item["before"]),
                db.jsonb(
                    {
                        **item["after"],
                        "change_kind": item["kind"],
                        "target": item["target"],
                        "month": current["month"],
                        "content_hash": current["content_hash"],
                        "operation_id": current["operation_id"],
                        "adapter": "manual",
                    }
                ),
                actor,
                current["id"],
            ),
        )


def approve(conn, org, brand, campaign, set_id, expected_hash, actor):
    from app.ads import month_budget

    try:
        data.lock(conn, org, brand)
        current = data.get(conn, org, brand, campaign, set_id)
        if not expected_hash or expected_hash != current["content_hash"]:
            raise ValueError("核准內容與目前清單不同，請重新檢視。")
        if current["status"] == "approved":
            conn.commit()
            return current
        if current["status"] not in {"draft", "deferred"}:
            raise ValueError("此清單已拒絕，請重新建立。")
        c = data.campaign(conn, org, brand, campaign)
        from app.ads import handoff_material

        handoff_material.validate_approval(conn, org, brand, campaign, current)
        for item in current["items"]:
            if item["kind"] == "new_ad":
                from app.ads import handoff_new_ad

                handoff_new_ad.validate_approval(conn, org, brand, campaign, item)
                continue
            entity = bindings.entity(conn, org, brand, campaign, item["target_id"])
            if data.digest(data.premise(entity, item["kind"], c)) != item["premise_hash"]:
                raise ValueError("這項變更所依據的設定已改變，請依現況重新建立清單。")
            if conn.execute(
                "SELECT id FROM ads_action WHERE org_id=%s AND brand_id=%s "
                "AND target_id=%s AND kind=%s AND change_set_id IS NOT NULL "
                "AND verification_state IN ('pending','reported','unknown') LIMIT 1",
                (
                    org,
                    brand,
                    item["target_id"],
                    "creative" if item["kind"] == "copy" else item["kind"],
                ),
            ).fetchone():
                raise ValueError("這個物件已有相同操作待核對，請先處理原清單。")
        month_budget.preflight(conn, org, brand, current["month"], current["items"])
        amount = sum(float(i["after"].get("daily_amount") or 0) for i in current["items"])
        approval_id = approval.approve(
            conn,
            org_id=org,
            brand_id=brand,
            scope_type="ads_change_set",
            scope_ref=set_id,
            content_hash=current["content_hash"],
            amount=amount,
            max_daily_amount=amount,
            actor=actor,
            commit=False,
        )
        _insert_actions(conn, org, brand, campaign, current, actor)
        for item in current["items"]:
            if item["kind"] == "new_ad":
                handoff_new_ad.install(conn, org, brand, campaign, set_id, item)
        conn.execute(
            "UPDATE ads_change_set SET status='approved',approval_id=%s,approved_at=now() "
            "WHERE id=%s AND org_id=%s AND brand_id=%s",
            (approval_id, set_id, org, brand),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return data.get(conn, org, brand, campaign, set_id)


def decide(conn, org, brand, campaign, set_id, decision, reason, revisit_at, actor):
    if (
        decision not in {"rejected", "deferred"}
        or not isinstance(reason, str)
        or not reason.strip()
    ):
        raise ValueError("請選擇拒絕或暫緩，並填寫原因。")
    revisit = None
    if decision == "deferred":
        try:
            revisit = datetime.fromisoformat(str(revisit_at).replace("Z", "+00:00"))
            if revisit.tzinfo is None or revisit <= db.now_utc():
                raise ValueError
        except ValueError:
            raise ValueError("暫緩請選擇未來的重看時間。") from None
    try:
        data.lock(conn, org, brand)
        current = data.get(conn, org, brand, campaign, set_id)
        if current["status"] not in {"draft", "deferred"}:
            raise ValueError("已核准清單請逐項處理，不可用暫緩掩蓋尚未完成的操作。")
        conn.execute(
            "UPDATE ads_change_set SET status=%s,decision_reason=%s,revisit_at=%s "
            "WHERE id=%s AND org_id=%s AND brand_id=%s",
            (decision, reason.strip(), revisit, set_id, org, brand),
        )
        write_audit(
            conn,
            org_id=org,
            brand_id=brand,
            entity_type="ads_change_set",
            entity_id=set_id,
            action=decision,
            actor=actor,
            reason=reason,
            after={"revisit_at": str(revisit) if revisit else None},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return data.get(conn, org, brand, campaign, set_id)


def item(conn, org, brand, campaign, set_id, action_id):
    current = data.get(conn, org, brand, campaign, set_id)
    found = next((i for i in current["items"] if i["id"] == action_id), None)
    if current["status"] != "approved" or found is None:
        raise ValueError("找不到已核准的操作。")
    return current, found


def report(conn, org, brand, campaign, set_id, action_id, actor):
    try:
        data.lock(conn, org, brand)
        _, found = item(conn, org, brand, campaign, set_id, action_id)
        if found["verification_state"] == "stale":
            raise ValueError("此操作已失效，請重新檢視計畫。")
        if found["reported_at"] is not None:
            conn.commit()
            return data.get(conn, org, brand, campaign, set_id)
        conn.execute(
            "UPDATE ads_action SET reported_at=COALESCE(reported_at,now()),"
            "verification_state=CASE WHEN verification_state IN ('pending','unknown') "
            "THEN 'reported' ELSE verification_state END WHERE id=%s AND org_id=%s "
            "AND brand_id=%s AND change_set_id=%s",
            (action_id, org, brand, set_id),
        )
        write_audit(
            conn,
            org_id=org,
            brand_id=brand,
            entity_type="ads_action",
            entity_id=action_id,
            action="report",
            actor=actor,
            after={"platform_verified": False},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return data.get(conn, org, brand, campaign, set_id)
