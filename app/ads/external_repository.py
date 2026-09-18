"""Persistence of scoped native snapshots. No platform calls, deletion inference or totals."""

from app.ads.external_models import ExternalEntity, ExternalObservation
from app.brand_intelligence import repository as bi_repo
from app.core.db import jsonb, new_id


def _campaign(conn, org_id, brand_id, campaign_id):
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    return dict(row)


def create_imported_campaign(conn, org_id, brand_id, *, name, created_by=None):
    brand = bi_repo.get_brand(conn, brand_id)
    if brand is None or brand["org_id"] != org_id:
        raise ValueError("brand_unknown")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name_unknown")
    campaign_id = new_id("adc")
    conn.execute(
        "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,created_by) "
        "VALUES (%s,%s,%s,%s,'imported',%s)",
        (campaign_id, org_id, brand_id, name.strip(), created_by),
    )
    return _campaign(conn, org_id, brand_id, campaign_id)


def upsert_entity(conn, org_id, brand_id, campaign_id, entity):
    _campaign(conn, org_id, brand_id, campaign_id)
    model = ExternalEntity.model_validate(entity)
    data = model.model_dump()
    changed = model.model_fields_set
    # Native keys cannot silently move between workspaces.
    existing = conn.execute(
        "SELECT campaign_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND platform=%s AND source_account=%s AND native_kind=%s AND native_id=%s",
        (
            org_id,
            brand_id,
            data["platform"],
            data["source_account"],
            data["native_kind"],
            data["native_id"],
        ),
    ).fetchone()
    if existing and existing["campaign_id"] != campaign_id:
        raise ValueError("external_entity_already_imported")
    columns = list(data)
    values = [
        jsonb(value) if key in ("availability", "creative") else value
        for key, value in data.items()
    ]
    row = conn.execute(
        "INSERT INTO ads_external_entity (id,org_id,brand_id,campaign_id,"
        + ",".join(columns)
        + ") "
        "VALUES (" + ",".join(["%s"] * (4 + len(columns))) + ") "
        "ON CONFLICT (org_id,brand_id,platform,source_account,native_kind,native_id) DO UPDATE SET "
        + ",".join(key + "=EXCLUDED." + key for key in columns if key in changed)
        + ",updated_at=now() "
        "WHERE ads_external_entity.campaign_id=EXCLUDED.campaign_id RETURNING *",
        (new_id("aex"), org_id, brand_id, campaign_id, *values),
    ).fetchone()
    if row is None:
        raise ValueError("external_entity_already_imported")
    return dict(row)


def upsert_observation(conn, org_id, brand_id, campaign_id, observation):
    _campaign(conn, org_id, brand_id, campaign_id)
    data = ExternalObservation.model_validate(observation).model_dump()
    columns = list(data)
    values = [jsonb(value) if key == "availability" else value for key, value in data.items()]
    row = conn.execute(
        "INSERT INTO ads_external_daily (id,org_id,brand_id,campaign_id," + ",".join(columns) + ") "
        "VALUES (" + ",".join(["%s"] * (4 + len(columns))) + ") "
        "ON CONFLICT (org_id,brand_id,entity_id,day,metric_scope,attribution_key,currency) "
        "DO UPDATE SET "
        + ",".join(key + "=EXCLUDED." + key for key in columns)
        + ",observed_at=now() RETURNING *",
        (new_id("aed"), org_id, brand_id, campaign_id, *values),
    ).fetchone()
    return dict(row)


def record_sync(conn, org_id, brand_id, campaign_id, *, section, state):
    """Merge one section atomically; failed attempts retain prior coverage/success timestamps."""
    if section not in {"structure", "creatives", "observations"}:
        raise ValueError("sync_section_unknown")
    _campaign(conn, org_id, brand_id, campaign_id)
    state = dict(state)
    if state.get("status") in {"error", "failed", "unavailable", "partial"} or state.get("error"):
        state.pop("last_success_at", None)
        state.pop("coverage", None)
    state = {key: value for key, value in state.items() if value is not None or key == "error"}
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{external_sync}', "
        "COALESCE(context_json->'external_sync','{}'::jsonb) || jsonb_build_object(%s::text, "
        "COALESCE(context_json->'external_sync'->%s,'{}'::jsonb) || %s::jsonb)) "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (section, section, jsonb(state), org_id, brand_id, campaign_id),
    )


def external_view(conn, org_id, brand_id, campaign_id):
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    entities = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "ORDER BY created_at,id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    observations = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "ORDER BY day,entity_id,metric_scope,attribution_key,currency",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    sync = (campaign.get("context_json") or {}).get("external_sync", {})
    return {
        "entities": [dict(row) for row in entities],
        "observations": [dict(row) for row in observations],
        "coverage": {key: value.get("coverage") for key, value in sync.items()},
        "sync": sync,
    }
