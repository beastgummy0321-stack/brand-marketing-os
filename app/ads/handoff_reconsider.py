"""A freshly verified stopped ad can release its old handoff for a new revision."""

from app.ads import asset_binding, external_sync, handoff_data
from app.ads import asset_binding_repository as bindings
from app.ads import change_control_data as changes
from app.ads import external_repository as external
from app.ads.external_models import ExternalEntity
from app.core import db


def reconsider(conn, org, brand, campaign, item_id, reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("請填寫重新安排原因，最多兩千字。")
    changes.lock(conn, org, brand)
    item = handoff_data.get(conn, org, brand, campaign, item_id)
    if not item["placement_id"] or not item["entity_id"]:
        raise ValueError("尚未取得原新廣告的確定身分，不能解除防重；請先讀回原交接。")
    leaf = bindings.entity(conn, org, brand, campaign, item["entity_id"])
    root = bindings.root(conn, org, brand, campaign, leaf)
    reader, account = external_sync.account_reader(
        conn, org, brand, leaf["platform"], leaf["source_account"]
    )
    attempt = db.new_id("ahr")
    conn.execute("UPDATE ads_handoff_item SET attempt_id=%s WHERE id=%s", (attempt, item_id))
    conn.commit()
    try:
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
        asset_binding._validate_chain(proof, leaf, root)
        node = ExternalEntity.model_validate(
            {k: v for k, v in proof["entity"].items() if k in ExternalEntity.model_fields}
        ).model_dump()
        if node["native_status"] not in {"PAUSED", "ARCHIVED", "DELETED"}:
            raise ValueError("原廣告尚未證明已停止；請先獨立暫停並核對，不可直接重建新廣告。")
        external_sync.account_reader(conn, org, brand, leaf["platform"], leaf["source_account"])
        changes.lock(conn, org, brand)
        current = handoff_data.get(conn, org, brand, campaign, item_id)
        if current["attempt_id"] != attempt:
            raise ValueError("已有較新的核對，請重新載入。")
        fresh = bindings.entity(conn, org, brand, campaign, item["entity_id"])
        if fresh["updated_at"] != leaf["updated_at"]:
            raise ValueError("核對期間來源已變更，請重試以保留較新的資料。")
        bindings.lock_native(conn, fresh)
        external.upsert_entity(conn, org, brand, campaign, node)
        evidence = {
            **current["evidence_json"],
            "reconsider_reason": reason.strip(),
            "stopped_at_observation": db.now_utc().isoformat(),
            "observed_native_status": node["native_status"],
            "entity_exists": True,
            "message": "平台已讀回原廣告停止；原身分與證據保留，可從素材建立新的交接清單。",
        }
        conn.execute(
            "UPDATE ads_handoff_item SET status='stale',evidence_json=%s,updated_at=now() "
            "WHERE id=%s",
            (db.jsonb(evidence), item_id),
        )
        conn.execute(
            "UPDATE ads_action SET verification_state='stale',"
            "evidence_json=evidence_json || %s::jsonb WHERE id=%s",
            (
                db.jsonb(
                    {
                        "reconsider_reason": reason.strip(),
                        "stopped_at_observation": evidence["stopped_at_observation"],
                    }
                ),
                current["action_id"],
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return handoff_data.get(conn, org, brand, campaign, item_id)
