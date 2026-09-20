"""Persistence of scoped native snapshots. No platform calls, deletion inference or totals."""

from datetime import timedelta

from app.ads import channels
from app.ads.external_models import ExternalEntity, ExternalObservation
from app.brand_intelligence import repository as bi_repo
from app.core import settings
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
        jsonb(value) if key in ("availability", "creative", "budget_raw") else value
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


def campaign_objective(conn, org_id, brand_id, platform, source_account, native_id):
    """The synced Meta-native objective for this root campaign entity, or None when the
    entity hasn't synced one yet (F16-I03, docs/architecture/ads.md §6.13). Callers must treat
    None as "no result mapping resolvable yet", never as a synonym for a specific objective."""
    row = conn.execute(
        "SELECT objective FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
        "platform=%s AND source_account=%s AND native_kind='campaign' AND native_id=%s",
        (org_id, brand_id, platform, source_account, native_id),
    ).fetchone()
    return row["objective"] if row else None


def upsert_observation(
    conn,
    org_id,
    brand_id,
    campaign_id,
    observation,
    *,
    result_kind=None,
    result_count=None,
    result_action=None,
    result_attribution=None,
):
    _campaign(conn, org_id, brand_id, campaign_id)
    data = ExternalObservation.model_validate(observation).model_dump()
    # result_kind/result_count/result_action/result_attribution (F16-I03) are kept outside the
    # strict ExternalObservation model on purpose: every other source (fixtures, future
    # platforms) that has no result mapping opinion would otherwise fail `extra="forbid"` for
    # fields it never sets. NULL is the correct default everywhere — "no result known", never a
    # guessed zero.
    data["availability"] = {
        **data["availability"],
        "result_count": "available" if result_count is not None else "unknown",
    }
    data["result_kind"] = result_kind
    data["result_count"] = result_count
    data["result_action"] = result_action
    data["result_attribution"] = result_attribution
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
    if state.get("status") in {"success", "syncing"} and not state.get("error"):
        state["error_code"] = None
    if state.get("status") in {"error", "failed", "unavailable", "partial"} or state.get("error"):
        state.pop("last_success_at", None)
        state.pop("coverage", None)
    state = {
        key: value
        for key, value in state.items()
        if value is not None or key in {"error", "error_code"}
    }
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{external_sync}', "
        "COALESCE(context_json->'external_sync','{}'::jsonb) || jsonb_build_object(%s::text, "
        "COALESCE(context_json->'external_sync'->%s,'{}'::jsonb) || %s::jsonb)) "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (section, section, jsonb(state), org_id, brand_id, campaign_id),
    )


def external_view(
    conn,
    org_id,
    brand_id,
    campaign_id,
    *,
    start=None,
    end=None,
    entity_after=None,
    observation_after=None,
    limit=100,
):
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    limit = min(max(int(limit), 1), 100)
    end = end or settings.today_for_org(conn, org_id=org_id)
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 365:
        raise ValueError("成效查詢請分成最多一年一期。")
    entities = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND (%s::text IS NULL OR id>%s) ORDER BY id LIMIT %s",
        (org_id, brand_id, campaign_id, entity_after, entity_after, limit + 1),
    ).fetchall()
    observations = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND day BETWEEN %s AND %s AND (%s::text IS NULL OR id>%s) ORDER BY id LIMIT %s",
        (
            org_id,
            brand_id,
            campaign_id,
            start,
            end,
            observation_after,
            observation_after,
            limit + 1,
        ),
    ).fetchall()
    sync = (campaign.get("context_json") or {}).get("external_sync", {})
    connections = []
    for platform, account in sorted({(row["platform"], row["source_account"]) for row in entities}):
        reader = channels.external_reader(platform)
        connected = bool(
            reader and account in {a["account_id"] for a in reader.accounts(conn, org_id, brand_id)}
        )
        connections.append(
            {
                "platform": platform,
                "source_account": account,
                "state": "connected" if connected else "disconnected",
            }
        )
    return {
        "entities": [dict(row) for row in entities[:limit]],
        "observations": [dict(row) for row in observations[:limit]],
        "next_entity_cursor": entities[limit - 1]["id"] if len(entities) > limit else None,
        "next_observation_cursor": observations[limit - 1]["id"]
        if len(observations) > limit
        else None,
        "window": {"start": start, "end": end},
        "connections": connections,
        "coverage": {key: value.get("coverage") for key, value in sync.items()},
        "sync": sync,
    }


def cache_listing(conn, org_id, brand_id, platform, account, item):
    model = ExternalEntity.model_validate(item)
    if model.platform != platform or model.source_account != account or model.parent_native_id:
        raise ValueError("來源活動範圍不符。")
    conn.execute(
        "INSERT INTO "
        "ads_external_listing(id,org_id,brand_id,platform,source_account,"
        "native_kind,native_id,snapshot) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
        "(org_id,brand_id,platform,source_account,native_kind,native_id) DO UPDATE SET "
        "snapshot=EXCLUDED.snapshot,observed_at=now()",
        (
            new_id("ael"),
            org_id,
            brand_id,
            platform,
            account,
            model.native_kind,
            model.native_id,
            jsonb(model.model_dump(mode="json")),
        ),
    )


def listing(conn, org_id, brand_id, platform, account, *, after=None, limit=100):
    limit = min(max(int(limit), 1), 100)
    rows = conn.execute(
        "SELECT * FROM ads_external_listing WHERE org_id=%s AND brand_id=%s AND platform=%s "
        "AND source_account=%s AND (%s::text IS NULL OR id>%s) ORDER BY id LIMIT %s",
        (org_id, brand_id, platform, account, after, after, limit + 1),
    ).fetchall()
    return {
        "items": [dict(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


def get_job(conn, org_id, brand_id, job_id):
    row = conn.execute(
        "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, job_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到同步工作。")
    return dict(row)


def import_cached(conn, org_id, brand_id, platform, account, native_kind, native_id, actor):
    key = ":".join((org_id, brand_id, platform, account, native_kind, native_id))
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
    row = conn.execute(
        "SELECT campaign_id FROM ads_external_entity WHERE org_id=%s AND "
        "brand_id=%s AND platform=%s "
        "AND source_account=%s AND native_kind=%s AND native_id=%s",
        (org_id, brand_id, platform, account, native_kind, native_id),
    ).fetchone()
    if row:
        return _campaign(conn, org_id, brand_id, row["campaign_id"])
    cached = conn.execute(
        "SELECT snapshot FROM ads_external_listing WHERE org_id=%s AND brand_id=%s AND platform=%s "
        "AND source_account=%s AND native_kind=%s AND native_id=%s",
        (org_id, brand_id, platform, account, native_kind, native_id),
    ).fetchone()
    if cached is None:
        raise ValueError("活動尚未讀回，請先更新既有活動清單。")
    if channels.has_legacy_campaign_binding(platform, native_kind):
        internal = conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND origin='internal' "
            "AND external_id=%s",
            (org_id, brand_id, native_id),
        ).fetchall()
        if len(internal) > 1:
            raise ValueError("此來源已對應多個內部工作區，請先釐清歸屬。")
        if internal:
            return dict(internal[0])
    item = cached["snapshot"]
    campaign = create_imported_campaign(
        conn, org_id, brand_id, name=item.get("name") or native_id, created_by=actor
    )
    upsert_entity(conn, org_id, brand_id, campaign["id"], item)
    return campaign
