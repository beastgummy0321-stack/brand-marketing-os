"""Persistence of scoped native snapshots. No platform calls, deletion inference or totals."""

from datetime import timedelta

from app.ads import channels, lifecycle
from app.ads.external_models import ExternalEntity, ExternalObservation
from app.brand_intelligence import repository as bi_repo
from app.core import settings
from app.core.db import jsonb, new_id, now_utc

# F16-I06: the one shared, platform-neutral definition of an account-month budget source row
# (written by `app.ads.adapters.meta_read.MetaReader.read_monthly` / `app.ads.external_sync`'s
# `_save_monthly`) versus an ordinary per-entity observation row -- they can share entity, day,
# `metric_scope` and currency, so `attribution_key` is the only field that tells them apart. Every
# writer and reader of `ads_external_daily` routes through this constant/predicate instead of
# repeating the literal, so the two row families can never drift out of sync again.
MONTHLY_BUDGET_ATTRIBUTION_KEY = "account_monthly_spend"


# Entity columns that record a read, not the object read (F49 Contract B: never a change).
READ_BOOKKEEPING = frozenset({"last_success_at", "last_attempt_at", "sync_status", "sync_error"})


def is_monthly_budget_row(attribution_key: str | None) -> bool:
    return attribution_key == MONTHLY_BUDGET_ATTRIBUTION_KEY


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
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    model = ExternalEntity.model_validate(entity)
    data = model.model_dump()
    changed = model.model_fields_set
    # Native keys cannot silently move between workspaces.
    existing = conn.execute(
        "SELECT campaign_id,native_status FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
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
    # F27-I00 Done #4, F49 Contract L: `status_changed_at` only moves when this write actually
    # crosses the off／not-off boundary (`lifecycle.may_spend`) -- a first insert (no `existing`
    # row) or an unchanged category never touches it. Both the previously stored and the newly
    # written `native_status` must be known (contract J: "both non-null") -- an unknown -> known
    # transition is not evidence the ad itself changed category, only that it became observable.
    status_changed = bool(
        existing is not None
        and "native_status" in changed
        and existing["native_status"] is not None
        and data.get("native_status") is not None
        and lifecycle.may_spend({**data, "native_status": existing["native_status"]})
        != lifecycle.may_spend(data)
    )
    columns = list(data)
    values = [
        jsonb(value) if key in ("availability", "creative", "budget_raw") else value
        for key, value in data.items()
    ]
    set_clause = ",".join(key + "=EXCLUDED." + key for key in columns if key in changed)
    # F49 Contract B: `updated_at` is the source version a readback compares
    # (`handoff_check._source_versions`, `handoff_reconsider`) -- it moves only when a content
    # column actually changed, so a periodic re-read of the same object never races a check.
    # The read bookkeeping (`last_*_at`, `sync_*`, the creative's own `observed_at`) is written but
    # is not a change.
    content = [
        f"(ads_external_entity.{key} - 'observed_at') IS DISTINCT FROM "
        f"(EXCLUDED.{key} - 'observed_at')"
        if key == "creative"
        else f"ads_external_entity.{key} IS DISTINCT FROM EXCLUDED.{key}"
        for key in columns
        if key in changed and key not in READ_BOOKKEEPING
    ]
    set_clause += (
        ",updated_at=CASE WHEN " + " OR ".join(content) + " THEN now() "
        "ELSE ads_external_entity.updated_at END"
        if content
        else ",updated_at=ads_external_entity.updated_at"
    )
    if status_changed:
        set_clause += ",status_changed_at=now()"
    row = conn.execute(
        "INSERT INTO ads_external_entity (id,org_id,brand_id,campaign_id,"
        + ",".join(columns)
        + ") "
        "VALUES (" + ",".join(["%s"] * (4 + len(columns))) + ") "
        "ON CONFLICT (org_id,brand_id,platform,source_account,native_kind,native_id) DO UPDATE SET "
        + set_clause
        + " WHERE ads_external_entity.campaign_id=EXCLUDED.campaign_id RETURNING *",
        (new_id("aex"), org_id, brand_id, campaign_id, *values),
    ).fetchone()
    if row is None:
        raise ValueError("external_entity_already_imported")
    # F49 Contract L: an imported campaign's state follows its root (draft／live／ended).
    if campaign["origin"] == "imported" and row["parent_native_id"] is None:
        lifecycle.record(conn, org_id, brand_id, campaign_id)
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
    heal_superseded_attribution=False,
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
    # F39-I06: `observed_at` is product time -- bound from `now_utc()` on insert and update
    # alike (one clock; the drill rebinds that name), never the column DEFAULT or SQL `now()`.
    # `updated_at`/`status_changed_at` on the entity table are audit stamps and stay SQL `now()`.
    columns = [*data, "observed_at"]
    values = [jsonb(value) if key == "availability" else value for key, value in data.items()]
    values.append(now_utc())
    row = conn.execute(
        "INSERT INTO ads_external_daily (id,org_id,brand_id,campaign_id," + ",".join(columns) + ") "
        "VALUES (" + ",".join(["%s"] * (4 + len(columns))) + ") "
        "ON CONFLICT (org_id,brand_id,entity_id,day,metric_scope,attribution_key,currency) "
        "DO UPDATE SET " + ",".join(key + "=EXCLUDED." + key for key in columns) + " RETURNING *",
        (new_id("aed"), org_id, brand_id, campaign_id, *values),
    ).fetchone()
    if heal_superseded_attribution and not is_monthly_budget_row(data["attribution_key"]):
        # F16-I06 cause #2: Meta's `attribution_key` embeds the purchase action type, so a day
        # first synced before any purchase lands (`...:unavailable`) and later re-synced after a
        # purchase (`...:omni_purchase`) becomes a second row under the uniqueness key instead of
        # an update to the first. Only the sync write path opts in (never the generic write above,
        # never a monthly row) -- it removes any other observation row of this exact identity
        # (entity, day, metric_scope, currency, source) in this same transaction, so a re-sync of
        # an affected window heals its own duplicates without a hand-written data fix.
        conn.execute(
            "DELETE FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND entity_id=%s "
            "AND day=%s AND metric_scope=%s AND currency IS NOT DISTINCT FROM %s AND source=%s "
            "AND attribution_key<>%s AND attribution_key<>%s",
            (
                org_id,
                brand_id,
                data["entity_id"],
                data["day"],
                data["metric_scope"],
                data["currency"],
                data["source"],
                data["attribution_key"],
                MONTHLY_BUDGET_ATTRIBUTION_KEY,
            ),
        )
    return dict(row)


def record_sync(conn, org_id, brand_id, campaign_id, *, section, state):
    """Merge one section atomically; failed attempts retain prior ranges/success timestamps.

    F49 Contract V: a clean read's range (the `coverage` key of `state`, `{start, end}`) joins
    the section's stored `ranges` -- the merged union `coverage.with_range` keeps -- instead of
    replacing the last one; the legacy single `coverage` key is folded into `ranges` and no
    longer stored."""
    from app.ads import coverage  # lazy: coverage imports this module

    if section not in {"structure", "creatives", "observations"}:
        raise ValueError("sync_section_unknown")
    _campaign(conn, org_id, brand_id, campaign_id)
    state = dict(state)
    read = state.pop("coverage", None)
    if state.get("status") in {"success", "syncing"} and not state.get("error"):
        state["error_code"] = None
    failed = state.get("status") in {"error", "failed", "unavailable", "partial"} or state.get(
        "error"
    )
    if failed:
        state.pop("last_success_at", None)
    elif isinstance(read, dict) and read.get("start") and read.get("end"):
        stored = conn.execute(
            "SELECT context_json->'external_sync'->%s AS section FROM ads_campaign "
            "WHERE org_id=%s AND brand_id=%s AND id=%s FOR UPDATE",
            (section, org_id, brand_id, campaign_id),
        ).fetchone()
        state["ranges"] = coverage.with_range(
            stored["section"] if stored else None, read["start"], read["end"]
        )
    state = {
        key: value
        for key, value in state.items()
        if value is not None or key in {"error", "error_code"}
    }
    # Writing `ranges` drops the legacy `coverage` key it was folded into.
    drop = "coverage" if "ranges" in state else ""
    conn.execute(
        "UPDATE ads_campaign SET context_json=jsonb_set(context_json,'{external_sync}', "
        "COALESCE(context_json->'external_sync','{}'::jsonb) || jsonb_build_object(%s::text, "
        "(COALESCE(context_json->'external_sync'->%s,'{}'::jsonb) - %s::text) || %s::jsonb)) "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (section, section, drop, jsonb(state), org_id, brand_id, campaign_id),
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
    from app.ads import coverage  # lazy: coverage imports this module

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
        "entities": [_with_delivery(row) for row in entities[:limit]],
        "observations": [dict(row) for row in observations[:limit]],
        "next_entity_cursor": entities[limit - 1]["id"] if len(entities) > limit else None,
        "next_observation_cursor": observations[limit - 1]["id"]
        if len(observations) > limit
        else None,
        "window": {"start": start, "end": end},
        "connections": connections,
        # F49 Contract V: the observations read ranges (`coverage.served`), the one reader.
        "coverage": {"observations": coverage.served(campaign)},
        "sync": sync,
    }


def _with_delivery(entity) -> dict:
    """F49 Contract L: an entity row plus its served `delivery_label` (`lifecycle.delivery`)."""
    entity = dict(entity)
    return {**entity, "delivery_label": lifecycle.delivery(entity)["label"]}


def cache_listing(conn, org_id, brand_id, platform, account, item):
    model = ExternalEntity.model_validate(item)
    if model.platform != platform or model.source_account != account or model.parent_native_id:
        raise ValueError("來源活動範圍不符。")
    conn.execute(
        "INSERT INTO "
        "ads_external_listing(id,org_id,brand_id,platform,source_account,"
        "native_kind,native_id,snapshot,observed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
        "(org_id,brand_id,platform,source_account,native_kind,native_id) DO UPDATE SET "
        "snapshot=EXCLUDED.snapshot,observed_at=EXCLUDED.observed_at",
        (
            new_id("ael"),
            org_id,
            brand_id,
            platform,
            account,
            model.native_kind,
            model.native_id,
            jsonb(model.model_dump(mode="json")),
            now_utc(),
        ),
    )


def listing(conn, org_id, brand_id, platform, account, *, after=None, limit=100):
    limit = min(max(int(limit), 1), 100)
    # F47-I08: `campaign_id` is the workspace campaign this platform object is already bound to
    # (its `ads_external_entity` row), null when it is not in any workspace yet -- so the join
    # dialog never offers to add the same platform campaign twice.
    rows = conn.execute(
        "SELECT l.*, e.campaign_id FROM ads_external_listing l "
        "LEFT JOIN ads_external_entity e ON e.org_id=l.org_id AND e.brand_id=l.brand_id "
        "AND e.platform=l.platform AND e.source_account=l.source_account "
        "AND e.native_kind=l.native_kind AND e.native_id=l.native_id "
        "WHERE l.org_id=%s AND l.brand_id=%s AND l.platform=%s "
        "AND l.source_account=%s AND (%s::text IS NULL OR l.id>%s) ORDER BY l.id LIMIT %s",
        (org_id, brand_id, platform, account, after, after, limit + 1),
    ).fetchall()
    return {
        "items": [
            {**dict(row), "delivery_label": lifecycle.delivery({
                "platform": row["platform"],
                "native_status": (row["snapshot"] or {}).get("native_status"),
            })["label"]}
            for row in rows[:limit]
        ],
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
