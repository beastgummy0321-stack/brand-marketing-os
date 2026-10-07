"""Manual handoff, fresh source verification and conservative version attribution."""

from collections.abc import Callable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ads import asset_binding_repository as repo
from app.ads import external_repository as external
from app.ads import external_sync
from app.ads.adapters.external import SourceReadError
from app.ads.external_models import ExternalEntity
from app.core import db


def handoff(conn, org, brand, campaign, placement_id, revision):
    p, asset = repo.confirmed(conn, org, brand, campaign, placement_id, revision)
    return {
        "placement_id": placement_id,
        "revision": revision,
        "download_url": f"/api/ads/brands/{brand}/user-assets/{asset['id']}/download",
        "filename": asset["filename"],
        "mime_type": asset["mime_type"],
        "original_copy": p["copy_fields"],
        "suggested_copy": p["suggested_copy"],
        "effective_copy": repo.effective_copy(p),
        "destination_entity_id": p["destination_entity_id"],
        "purpose": p["purpose"],
        "start_date": p["start_date"],
        "end_date": p["end_date"],
        "tracking_name": f"MOS-{placement_id}-v{revision}",
        "platform_written": False,
        "notice": "追蹤名稱只用於找候選，不是素材相同證據；內部確認不代表已上架。",
        "bindings": repo.list_bindings(conn, org, brand, campaign, placement_id, revision),
    }


def candidates(
    conn, org, brand, campaign, placement_id, revision, *, platform, account_id, after=None
):
    repo.confirmed(conn, org, brand, campaign, placement_id, revision)
    reader, _ = external_sync.account_reader(conn, org, brand, platform, account_id)
    kinds = getattr(reader, "binding_kinds", lambda: ())()
    rows = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND platform=%s AND source_account=%s AND native_kind=ANY(%s) AND "
        "(%s::text IS NULL OR id>%s) ORDER BY id LIMIT 101",
        (org, brand, campaign, platform, account_id, list(kinds), after, after),
    ).fetchall()
    return {
        "candidates": [
            {
                "entity_id": r["id"],
                "native_id": r["native_id"],
                "native_kind": r["native_kind"],
                "name": r["name"],
                "creative": r["creative"],
                "last_success_at": r["last_success_at"],
            }
            for r in rows[:100]
        ],
        "next_cursor": rows[99]["id"] if len(rows) > 100 else None,
        "evidence": "cached_candidates_only",
    }


def _validate_chain(proof, leaf, root):
    node = proof.get("entity")
    parents = proof.get("parents")
    if not isinstance(node, dict) or not isinstance(parents, list) or len(parents) > 100:
        raise ValueError("平台未提供完整父鏈。")
    if node.get("native_id") != leaf["native_id"] or node.get("native_kind") != leaf["native_kind"]:
        raise ValueError("平台回讀的物件不是指定候選。")
    for child in [node, *parents]:
        if (
            not isinstance(child, dict)
            or child.get("platform") != leaf["platform"]
            or child.get("source_account") != leaf["source_account"]
        ):
            raise ValueError("平台回讀帳號不符。")
    lookup = {(p.get("native_kind"), p.get("native_id")): p for p in parents}
    if len(lookup) != len(parents):
        raise ValueError("平台父鏈重複。")
    seen = set()
    while node.get("parent_native_id") is not None:
        key = (node.get("parent_native_kind"), node.get("parent_native_id"))
        if key in seen or key not in lookup:
            raise ValueError("平台父鏈無法核對。")
        seen.add(key)
        node = lookup[key]
    if len(seen) != len(parents):
        raise ValueError("平台回傳無關父層。")
    if (node.get("native_kind"), node.get("native_id")) != (root["native_kind"], root["native_id"]):
        raise ValueError("平台廣告不屬於指定活動。")


def verify(
    conn, org, brand, campaign, placement_id, revision, entity_id, actor, *, user_verified=False,
    before_persist: Callable[[], None] | None = None,
):
    if not isinstance(user_verified, bool):
        raise ValueError("請明確選擇是否已人工核對素材。")
    p, asset = repo.confirmed(conn, org, brand, campaign, placement_id, revision)
    leaf = repo.entity(conn, org, brand, campaign, entity_id)
    root = repo.root(conn, org, brand, campaign, leaf)
    reader, account = external_sync.account_reader(
        conn, org, brand, leaf["platform"], leaf["source_account"]
    )
    if leaf["native_kind"] not in getattr(reader, "binding_kinds", lambda: ())():
        raise ValueError("此來源種類不能對應素材。")
    original = {"sha256": asset["sha256"], "copy_hash": repo.digest(repo.effective_copy(p))}
    conn.commit()  # No placement lock or transaction may span provider HTTP.
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
            original=original,
        )
        _validate_chain(proof, leaf, root)
    except ValueError as exc:
        # F49 Contract B: a refusal only (a code bug propagates), re-raised with its reason code
        # -- the source read's own, else the chain's.
        conn.rollback()
        if before_persist is not None:
            before_persist()
        repo.record_failure(conn, org, brand, campaign, placement_id, revision, leaf)
        conn.commit()
        raise SourceReadError(
            "指定廣告與完整父鏈無法重新核對，未新增平台確認。",
            getattr(exc, "code", None) or "chain_mismatch",
        ) from None
    # Facades may commit. Re-read connection/account/placement after all HTTP has finished.
    external_sync.account_reader(conn, org, brand, leaf["platform"], leaf["source_account"])
    # A caller may own a stricter attempt/revision boundary; acquire its lock before placement.
    if before_persist is not None:
        before_persist()
    current, asset = repo.confirmed(conn, org, brand, campaign, placement_id, revision, write=True)
    fresh_leaf = repo.entity(conn, org, brand, campaign, entity_id)
    fresh_root = repo.root(conn, org, brand, campaign, fresh_leaf)
    if (fresh_root["native_kind"], fresh_root["native_id"]) != (
        root["native_kind"],
        root["native_id"],
    ):
        raise ValueError("來源父鏈已改變，請重新載入。")
    if (
        repo.digest(repo.effective_copy(current)) != original["copy_hash"]
        or asset["sha256"] != original["sha256"]
    ):
        raise ValueError("素材版本已改變，請重新核對。")
    repo.lock_native(conn, leaf)
    now = db.now_utc()
    occupied = conn.execute(
        "SELECT * FROM ads_asset_binding WHERE org_id=%s AND platform=%s AND "
        "source_account=%s AND native_kind=%s AND native_id=%s AND "
        "existence_status='platform_confirmed' AND valid_to IS NULL FOR UPDATE",
        (org, leaf["platform"], leaf["source_account"], leaf["native_kind"], leaf["native_id"]),
    ).fetchone()
    if occupied and (
        occupied["brand_id"] != brand
        or occupied["campaign_id"] != campaign
        or occupied["placement_id"] != placement_id
    ):
        raise ValueError("此平台廣告已對應另一個素材安排，請先結束原對應。")
    creative = proof["entity"].get("creative") or {}
    digest = repo.creative_hash(creative)
    equivalence = proof.get("media_equivalence") or {}
    if not isinstance(equivalence, dict):
        raise ValueError("平台素材證據格式無效。")
    verified = (
        equivalence.get("asset_sha256") == original["sha256"]
        and equivalence.get("copy_hash") == original["copy_hash"]
        and equivalence.get("creative_hash") == digest
        and bool(equivalence.get("basis"))
    )
    same = bool(
        occupied
        and occupied["placement_revision"] == revision
        and occupied["creative_hash"] == digest
    )
    timezone = proof.get("timezone_name")
    if same and (
        (equivalence and not verified and occupied["evidence_level"] == "media_verified")
        or (timezone and occupied["timezone_name"] and timezone != occupied["timezone_name"])
    ):
        same = False  # Opposite evidence starts a new interval; old evidence remains immutable.
    if same and not equivalence and occupied["evidence_level"] == "media_verified":
        equivalence = occupied["media_equivalence"]
        verified = True
    if same and not timezone:
        timezone = occupied["timezone_name"]
    remembered_user = bool(same and occupied["user_verified_at"])
    level = (
        "media_verified"
        if verified
        else "user_verified"
        if user_verified or remembered_user
        else "unknown"
    )
    intervals = proof.get("continuous_intervals") or []
    if not isinstance(intervals, list) or len(intervals) > 100:
        raise ValueError("來源版本歷史範圍無效。")
    intervals = [item for item in intervals if isinstance(item, dict) and item.get("basis")]
    if same:
        intervals = list(
            {
                repo.digest(item): item for item in [*occupied["continuous_intervals"], *intervals]
            }.values()
        )
        if len(intervals) > 100:
            raise ValueError("版本證據達單筆上限，請先結束舊對應再新增。")
    if same:
        conn.execute(
            "UPDATE ads_asset_binding SET last_attempt_at=%s,last_verified_at=%s,"
            "verified_by=%s,stale_reason=NULL,evidence_level=%s,user_verified_at=CASE WHEN "
            "%s THEN %s ELSE user_verified_at END,user_verified_by=CASE WHEN %s THEN %s "
            "ELSE user_verified_by END,media_equivalence=%s,continuous_intervals=%s,"
            "timezone_name=%s WHERE id=%s",
            (
                now,
                now,
                actor,
                level,
                user_verified,
                now,
                user_verified,
                actor,
                db.jsonb(equivalence if verified else {}),
                db.jsonb(intervals),
                timezone,
                occupied["id"],
            ),
        )
        binding_id = occupied["id"]
    else:
        if occupied:
            conn.execute(
                "UPDATE ads_asset_binding SET valid_to=%s,"
                "stale_reason='由明確核對的新素材版本取代，舊證據保留。' WHERE id=%s",
                (now, occupied["id"]),
            )
        row = conn.execute(
            "INSERT INTO ads_asset_binding(id,org_id,brand_id,campaign_id,placement_id,"
            "placement_revision,entity_id,platform,source_account,native_kind,native_id,"
            "existence_status,evidence_level,user_verified_at,user_verified_by,"
            "first_verified_at,last_verified_at,last_attempt_at,verified_by,"
            "creative_snapshot,creative_hash,media_equivalence,continuous_intervals,"
            "timezone_name,valid_from) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'platform_confirmed',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                db.new_id("aab"),
                org,
                brand,
                campaign,
                placement_id,
                revision,
                entity_id,
                leaf["platform"],
                leaf["source_account"],
                leaf["native_kind"],
                leaf["native_id"],
                level,
                now if user_verified else None,
                actor if user_verified else None,
                now,
                now,
                now,
                actor,
                db.jsonb(creative),
                digest,
                db.jsonb(equivalence if verified else {}),
                db.jsonb(intervals),
                timezone,
                now,
            ),
        ).fetchone()
        binding_id = row["id"]
    for node in reversed([proof["entity"], *proof["parents"]]):
        # same filter as handoff_check: a reader's extra keys (launch_settings) are not stored
        node = {k: v for k, v in node.items() if k in ExternalEntity.model_fields}
        external.upsert_entity(conn, org, brand, campaign, node)
    conn.commit()
    return next(
        b
        for b in repo.list_bindings(conn, org, brand, campaign, placement_id, revision)
        if b["id"] == binding_id
    )


def end(conn, org, brand, campaign, placement_id, revision, binding_id):
    repo.confirmed(conn, org, brand, campaign, placement_id, revision)
    existing = conn.execute(
        "SELECT * FROM ads_asset_binding WHERE org_id=%s AND brand_id=%s AND "
        "campaign_id=%s AND placement_id=%s AND placement_revision=%s AND id=%s",
        (org, brand, campaign, placement_id, revision, binding_id),
    ).fetchone()
    if existing is None:
        raise ValueError("找不到版本對應。")
    repo.lock_native(conn, dict(existing))
    row = conn.execute(
        "UPDATE ads_asset_binding SET valid_to=COALESCE(valid_to,%s),"
        "stale_reason=COALESCE(stale_reason,'使用者已結束此版本對應。') WHERE org_id=%s AND "
        "brand_id=%s AND campaign_id=%s AND placement_id=%s AND placement_revision=%s AND "
        "id=%s RETURNING *",
        (db.now_utc(), org, brand, campaign, placement_id, revision, binding_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到版本對應。")
    return dict(row)


def _instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def _eligible(binding, observation, now):
    if observation["metric_scope"] != binding["native_kind"]:
        return "成效層級與此廣告種類不符，不能歸屬素材版本。"
    if binding["evidence_level"] != "media_verified":
        return "沒有平台可驗證的素材與文案等價證據。"
    if binding["creative_snapshot"].get("kind") not in {"image", "video"}:
        return "多素材或未知素材無法拆到單一版本。"
    try:
        zone = ZoneInfo(binding["timezone_name"])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        return "來源帳號時區未知。"
    day = observation["day"]
    start = datetime.combine(day, time.min, tzinfo=zone)
    stop = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    if stop > now:
        return "當日或未完成的日成效不能分到版本。"
    if start < binding["first_verified_at"] or start < binding["valid_from"]:
        return "首次核對前或部分日期不能回填給此版本。"
    if binding["valid_to"] and stop > binding["valid_to"]:
        return "當日版本切換或對應區間不完整。"
    for interval in binding["continuous_intervals"]:
        if not isinstance(interval, dict):
            continue
        begin = _instant(interval.get("start"))
        finish = _instant(interval.get("end"))
        if (
            interval.get("coverage") == "continuous"
            and interval.get("basis")
            and interval.get("creative_hash") == binding["creative_hash"]
            and begin
            and finish
            and begin <= start
            and finish >= stop
        ):
            return None
    return "無連續 creative 歷史證據；兩次相同快照不能證明整日版本。"


def metrics(conn, org, brand, campaign, placement_id, revision, *, start, end):
    if start > end or (end - start).days > 30:
        raise ValueError("請選擇最多31日。")
    bindings = repo.list_bindings(conn, org, brand, campaign, placement_id, revision)
    rows = []
    attributed = []
    for binding in bindings:
        if not binding["entity_id"]:
            continue
        native = conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND entity_id=%s AND day BETWEEN %s AND %s ORDER BY day,id LIMIT 501",
            (org, brand, campaign, binding["entity_id"], start, end),
        ).fetchall()
        if len(native) > 500:
            raise ValueError("原生成效超過單次上限，請縮小日期範圍。")
        for row in native:
            observation = dict(row)
            reason = _eligible(binding, observation, db.now_utc())
            if reason is None:
                conn.execute(
                    "INSERT INTO ads_asset_observation_claim(observation_id,org_id,"
                    "brand_id,campaign_id,binding_id) VALUES(%s,%s,%s,%s,%s) ON "
                    "CONFLICT(observation_id) DO NOTHING",
                    (row["id"], org, brand, campaign, binding["id"]),
                )
                owner = conn.execute(
                    "SELECT binding_id FROM ads_asset_observation_claim WHERE observation_id=%s",
                    (row["id"],),
                ).fetchone()
                if owner["binding_id"] != binding["id"]:
                    reason = "這筆觀測已歸屬另一版本，不能重複計算。"
            result = {
                **observation,
                "binding_id": binding["id"],
                "unattributed_reason": reason,
                "attributed": reason is None,
            }
            rows.append(result)
            if reason is None:
                attributed.append(result)
    # No totals across level, currency or attribution windows. Native rows remain available.
    native_rows = {}
    for row in rows:
        if row["id"] not in native_rows or row["attributed"]:
            native_rows[row["id"]] = row
    if len(native_rows) > 500:
        raise ValueError("原生成效超過單次上限，請縮小日期範圍。")
    return {
        "observations": list(native_rows.values()),
        "attributed_observations": attributed,
        "totals": None,
        "notice": "原生成效不等於素材版本成效；未知不補零。",
    }
