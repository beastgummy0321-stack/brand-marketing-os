"""Read back one approved action. A matching setting is not delivery or causality."""

from app.ads import asset_binding, change_control, external_sync, handoff_check
from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as data
from app.ads import external_repository as external
from app.ads.external_models import ExternalEntity
from app.core import db
from app.core.audit import write_audit


def _copy_matches(observed, expected):
    """Contract B point 3: a dynamic ad's variant lists are sets, not sequences -- Meta (and a
    human re-ordering them) never promises the same order back."""
    if isinstance(observed, list) and isinstance(expected, list):
        return sorted(observed) == sorted(expected)
    return observed == expected


def _source_content(row):
    return {k: row.get(k) for k in ExternalEntity.model_fields if k not in {
        "last_success_at", "last_attempt_at", "sync_status", "sync_error"
    }}


def _snapshot_chain(conn, org, brand, campaign, leaf):
    snapshots = [leaf]
    while snapshots[-1]["parent_native_id"] is not None:
        node = snapshots[-1]
        parent = conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND platform=%s AND source_account=%s AND native_kind=%s "
            "AND native_id=%s",
            (
                org,
                brand,
                campaign,
                leaf["platform"],
                leaf["source_account"],
                node["parent_native_kind"],
                node["parent_native_id"],
            ),
        ).fetchone()
        if parent is None or parent["id"] in {r["id"] for r in snapshots} or len(snapshots) >= 100:
            raise ValueError("來源父鏈不完整。")
        snapshots.append(dict(parent))
    return snapshots


def _lock_snapshots(conn, org, brand, campaign, snapshots):
    # Match binding writers: native locks precede entity row locks. HTTP has finished.
    for row in snapshots:
        bindings.lock_native(conn, row)
    ids = [row["id"] for row in reversed(snapshots)]
    rows = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND id=ANY(%s) ORDER BY array_position(%s::text[],id) FOR UPDATE",
        (org, brand, campaign, ids, ids),
    ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def check(conn, org, brand, campaign, set_id, action_id, actor):
    data.lock(conn, org, brand)
    current, action = change_control.item(conn, org, brand, campaign, set_id, action_id)
    if action["verification_state"] == "stale" or action["evidence_json"].get("superseded_by"):
        conn.commit()
        return current
    leaf = bindings.entity(conn, org, brand, campaign, action["target_id"])
    snapshots = _snapshot_chain(conn, org, brand, campaign, leaf)
    root = snapshots[-1]
    attempt_id = db.new_id("ack")
    conn.execute(
        "UPDATE ads_action SET evidence_json=evidence_json || %s::jsonb "
        "WHERE id=%s AND org_id=%s AND brand_id=%s AND change_set_id=%s",
        (db.jsonb({"check_attempt_id": attempt_id}), action_id, org, brand, set_id),
    )
    evidence = {
        "check_attempt_id": attempt_id,
        "platform_written": False,
        "delivery_confirmed": False,
        "setting_matches": None,
        "media_equivalence": "unknown",
        "effective_at": None,
        "message": "尚未取得可核對的設定；使用者回報不等於平台確認。",
    }
    state, observed, verified = "unknown", None, None
    snapshot_proof = None
    conn.commit()  # Neither transaction nor advisory lock spans platform HTTP.
    try:
        reader, account = external_sync.account_reader(
            conn, org, brand, leaf["platform"], leaf["source_account"]
        )
        proof = reader.verify_native(
            conn,
            org,
            brand,
            account,
            native_kind=leaf["native_kind"],
            native_id=leaf["native_id"],
            root_kind=root["native_kind"],
            root_id=root["native_id"],
            original={},
        )
        handoff_check._coded(
            "chain_mismatch", asset_binding._validate_chain, proof, leaf, root
        )
        nodes = [proof["entity"], *proof["parents"]]
        validated = [
            ExternalEntity.model_validate(
                {key: value for key, value in node.items() if key in ExternalEntity.model_fields}
            ).model_dump(exclude_unset=True)
            for node in nodes
        ]
        external_sync.account_reader(conn, org, brand, leaf["platform"], leaf["source_account"])
        observed = db.now_utc()
        values = data.before(proof["entity"], action["kind"])
        expected = action["after"]
        known = all(key in values and values[key] is not None for key in expected)
        if not known:
            evidence["message"] = "已讀到指定物件，但來源未提供這項設定，仍待核對。"
        elif all(_copy_matches(values[key], value) for key, value in expected.items()):
            state, verified = "confirmed", observed
            evidence["setting_matches"] = True
            evidence["message"] = "本次讀回設定符合清單；不代表已開始投遞或已有足夠成效。"
        elif all(_copy_matches(values[key], action["before"].get(key)) for key in expected):
            state = "pending"
            evidence["setting_matches"] = False
            evidence["message"] = "平台仍是變更前設定，這項操作尚未完成。"
        else:
            state = "deviated"
            evidence["setting_matches"] = False
            evidence["message"] = "平台設定與核准內容不同，請檢視差異後重新決定。"
        if action["kind"] == "budget":
            approved_conditions = data.budget_conditions(action["target"])
            read_conditions = data.budget_conditions(proof["entity"])
            evidence["budget_conditions"] = {
                "approved": approved_conditions,
                "observed": read_conditions,
            }
            if any(value != approved_conditions.get(key) for key, value in read_conditions.items()):
                state, verified = "stale", None
                evidence["message"] = "預算幣別、投放期間或控制種類已改變，請重新檢視。"
            elif set(read_conditions) != set(approved_conditions) or any(
                (proof["entity"].get("availability") or {}).get(key) in {"unknown", "unavailable"}
                or (
                    value is None
                    and (proof["entity"].get("availability") or {}).get(key) != "available"
                )
                for key, value in read_conditions.items()
            ):
                state, verified = "unknown", None
                evidence["message"] = "來源尚未提供完整的預算幣別、期間與控制種類，仍待核對。"
        if action["kind"] == "copy":
            expected_media, read_media = (
                action.get("media_identity"),
                data.media_identity(proof["entity"]),
            )
            evidence["media_identity_matches"] = (
                read_media == expected_media if expected_media and read_media else None
            )
            if expected_media and read_media and read_media != expected_media:
                state, verified = "deviated", None
                evidence["message"] = "文案以外的圖片或影片也已改變，請檢視偏離計畫的內容。"
            if any(
                key not in expected
                and value is not None
                and values.get(key) is not None
                and not _copy_matches(values[key], value)
                for key, value in action["before"].items()
            ):
                state, verified = "deviated", None
                evidence["message"] = "未列入本次變更的文案欄位也已改變，請檢視差異。"
        evidence.update(
            observed=values,
            expected=expected,
            observed_at=observed.isoformat(),
            native_id=leaf["native_id"],
            source_account=leaf["source_account"],
        )
        snapshot_proof = validated
    except ValueError as exc:
        # F49 Contract B: a refusal only -- a code bug propagates. The evidence names why.
        conn.rollback()
        code, text = handoff_check.refusal(exc)
        evidence["reason_code"] = code
        evidence["message"] = (
            "目前無法核對帳戶、物件或設定。請確認連線後重試；未標為完成。"
            if code == "unverifiable"
            else text
        )
    try:
        data.lock(conn, org, brand)
        latest, latest_action = change_control.item(conn, org, brand, campaign, set_id, action_id)
        if latest_action["verification_state"] == "stale" or latest_action["evidence_json"].get(
            "superseded_by"
        ):
            conn.commit()
            return latest
        if latest_action["evidence_json"].get("check_attempt_id") != attempt_id:
            conn.commit()
            return (
                latest  # A later attempt owns the result; never overwrite it with an old response.
            )
        c = data.campaign(conn, org, brand, campaign)
        locked = _lock_snapshots(conn, org, brand, campaign, snapshots)
        fresh = bindings.entity(conn, org, brand, campaign, action["target_id"])
        old_identity = {k: leaf.get(k) for k in data._IDENTITY}
        scope_changed = (
            latest["content_hash"] != current["content_hash"]
            or latest_action["context"] != data.context(c, action["kind"])
            or old_identity != {k: fresh.get(k) for k in data._IDENTITY}
            or bindings.root(conn, org, brand, campaign, fresh)["id"] != root["id"]
            or (
                action["kind"] == "budget"
                and data.budget_conditions(fresh) != data.budget_conditions(action["target"])
            )
        )
        snapshot_changed = any(
            row["id"] not in locked
            or _source_content(locked[row["id"]]) != _source_content(row)
            for row in snapshots
        )
        if snapshot_proof is not None:
            identity_keys = data._IDENTITY[1:]
            scope_changed = scope_changed or {
                tuple(node.get(key) for key in identity_keys) for node in snapshot_proof
            } != {tuple(row.get(key) for key in identity_keys) for row in snapshots}
        if scope_changed:
            state, verified = "stale", None
            evidence["message"] = "此操作的目標或計畫條件已改變，請重新檢視。"
        elif snapshot_changed:
            relevant = data.premise(fresh, action["kind"], c) != data.premise(
                leaf, action["kind"], c
            )
            state, verified = "stale" if relevant else "unknown", None
            evidence["setting_matches"] = None
            evidence["message"] = (
                "核對期間相關設定已改變，保留較新資料，請重新檢視。" if relevant else
                "核對期間有其他設定同步，保留較新資料；稍後重新核對即可，無需重複核准。"
            )
        elif snapshot_proof is not None:
            for node in reversed(snapshot_proof):
                node["last_success_at"] = observed
                saved = external.upsert_entity(conn, org, brand, campaign, node)
                if "creative" in node:
                    bindings.stale_for_entity(
                        conn, org, brand, campaign, saved["id"], node["creative"]
                    )
        conn.execute(
            "UPDATE ads_action SET verification_state=%s,evidence_json=%s,"
            "first_observed_at=COALESCE(first_observed_at,%s),"
            "verified_at=COALESCE(%s,verified_at) WHERE id=%s AND org_id=%s "
            "AND brand_id=%s AND change_set_id=%s",
            (state, db.jsonb(evidence), observed, verified, action_id, org, brand, set_id),
        )
        write_audit(
            conn,
            org_id=org,
            brand_id=brand,
            entity_type="ads_action",
            entity_id=action_id,
            action="readback",
            actor=actor,
            after={"verification_state": state, **evidence},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if state == "confirmed" and action["kind"] == "pause":
        # Contract D + correction 8: only after this function's own transaction has committed
        # `confirmed` -- both writers are idempotent per change ITEM id, so an automatic runtime
        # re-check of an already-confirmed item (`app/ads/runtime.py`) never duplicates.
        from app.ads import ads_learnings

        if action.get("angle"):
            ads_learnings.record_for_item(conn, org, brand, campaign, set_id, action)
        # F29-I04 Contract F: the confirmed pause of an A/B set writes its comparison result.
        ads_learnings.record_for_ab_item(conn, org, brand, campaign, current, action)
    return data.get(conn, org, brand, campaign, set_id)
