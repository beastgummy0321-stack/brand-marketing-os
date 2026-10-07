"""Scoped evidence records and immutable interval boundaries."""

import hashlib
import json

from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.core import db


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def creative_hash(value):
    def stable(v):
        if isinstance(v, dict):
            return {
                k: stable(x)
                for k, x in v.items()
                if k
                not in {
                    "observed_at",
                    "last_attempt_at",
                    "last_success_at",
                    "thumbnail_url",
                    "image_url",
                }
            }
        if isinstance(v, list):
            return [stable(x) for x in v]
        return v

    return digest(stable(value))


def effective_copy(placement):
    original = placement["copy_fields"]
    return {
        **original,
        **{
            k: v
            for k, v in placement["suggested_copy"].items()
            if not str(original.get(k) or "").strip()
        },
    }


def confirmed(conn, org, brand, campaign, placement_id, revision, *, write=False):
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("請提供正整數版本。")
    c = campaigns.get_campaign(conn, org, brand, campaign)
    if c is None or (write and c["status"] == "closed"):
        raise ValueError("活動不存在或已結案。")
    if write:
        conn.execute(
            "SELECT id FROM ads_asset_placement WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND id=%s AND is_current FOR UPDATE",
            (org, brand, campaign, placement_id),
        )
    row = assets.placement(conn, org, brand, campaign, placement_id, revision)
    if not row["confirmed_at"] or (write and not row["is_current"]):
        raise ValueError("此素材版本尚未確認或已修訂，請重新載入。")
    asset = assets.get_asset(conn, org, brand, row["asset_id"])
    if write and asset["status"] != "ready":
        raise ValueError("原檔尚未完成媒體處理。")
    return row, asset


def entity(conn, org, brand, campaign, entity_id):
    if not isinstance(entity_id, str) or not 1 <= len(entity_id) <= 200:
        raise ValueError("來源候選識別碼無效。")
    row = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND id=%s",
        (org, brand, campaign, entity_id),
    ).fetchone()
    if row is None:
        raise ValueError("候選不屬於此品牌活動。")
    return dict(row)


def root(conn, org, brand, campaign, leaf):
    visited = set()
    node = leaf
    while node["parent_native_id"] is not None:
        if node["id"] in visited or len(visited) >= 100:
            raise ValueError("來源父鏈不完整。")
        visited.add(node["id"])
        row = conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND platform=%s AND source_account=%s AND native_kind=%s AND "
            "native_id=%s",
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
        if row is None:
            raise ValueError("來源父鏈不完整。")
        node = dict(row)
    return node


def list_bindings(conn, org, brand, campaign, placement_id, revision):
    confirmed(conn, org, brand, campaign, placement_id, revision)
    rows = conn.execute(
        "SELECT * FROM ads_asset_binding WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND placement_id=%s AND placement_revision=%s ORDER BY created_at "
        "DESC LIMIT 100",
        (org, brand, campaign, placement_id, revision),
    ).fetchall()
    current = assets.placement(conn, org, brand, campaign, placement_id)
    result = []
    for row in rows:
        item = dict(row)
        if current["revision"] != revision:
            item["stale_reason"] = item["stale_reason"] or "素材已修訂，舊版證據只供歷史核對。"
        result.append(item)
    return result


def report(conn, org, brand, campaign, placement_id, revision, actor):
    confirmed(conn, org, brand, campaign, placement_id, revision, write=True)
    existing = conn.execute(
        "SELECT * FROM ads_asset_binding WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND placement_id=%s AND placement_revision=%s AND "
        "existence_status='self_reported' ORDER BY created_at DESC LIMIT 1",
        (org, brand, campaign, placement_id, revision),
    ).fetchone()
    if existing:
        return dict(existing)
    row = conn.execute(
        "INSERT INTO ads_asset_binding(id,org_id,brand_id,campaign_id,placement_id,"
        "placement_revision,reported_at,reported_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (db.new_id("aab"), org, brand, campaign, placement_id, revision, db.now_utc(), actor),
    ).fetchone()
    return dict(row)


def stale_for_entity(conn, org, brand, campaign, entity_id, creative):
    lock_native(conn, entity(conn, org, brand, campaign, entity_id))
    conn.execute(
        "UPDATE ads_asset_binding SET stale_reason='平台 creative 已變更，需重新核對素材版本。',"
        "valid_to=COALESCE(valid_to,%s) WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND entity_id=%s AND existence_status='platform_confirmed' AND creative_hash<>%s "
        "AND valid_to IS NULL",
        (db.now_utc(), org, brand, campaign, entity_id, creative_hash(creative)),
    )


def sync_failed(conn, org, brand, campaign):
    conn.execute(
        "UPDATE ads_asset_binding SET stale_reason=COALESCE(stale_reason,"
        "'來源同步失敗，保留上次平台核對證據。') "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND "
        "existence_status='platform_confirmed' AND valid_to IS NULL",
        (org, brand, campaign),
    )


def lock_native(conn, row, *, wait=True):
    if not row.get("platform"):
        return None if wait else True
    key = "ads-binding:" + ":".join(
        str(row[k]) for k in ("org_id", "platform", "source_account", "native_kind", "native_id")
    )
    if wait:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        return None
    acquired = conn.execute(
        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired", (key,)
    ).fetchone()
    return bool(acquired and acquired["acquired"])


def record_failure(conn, org, brand, campaign, placement_id, revision, leaf):
    reason = "本次平台回讀失敗，保留上次證據，尚待重新核對。"
    now = db.now_utc()
    updated = conn.execute(
        "UPDATE ads_asset_binding SET last_attempt_at=%s,stale_reason=%s "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND "
        "placement_id=%s AND placement_revision=%s",
        (now, reason, org, brand, campaign, placement_id, revision),
    ).rowcount
    if not updated:
        conn.execute(
            "INSERT INTO ads_asset_binding(id,org_id,brand_id,campaign_id,placement_id,"
            "placement_revision,entity_id,platform,source_account,native_kind,native_id,"
            "existence_status,last_attempt_at,stale_reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)",
            (
                db.new_id("aab"),
                org,
                brand,
                campaign,
                placement_id,
                revision,
                leaf["id"],
                leaf["platform"],
                leaf["source_account"],
                leaf["native_kind"],
                leaf["native_id"],
                now,
                reason,
            ),
        )
