"""Upload compensation and asynchronous previews through the storage facade only."""

import hashlib
import logging

from app import background, storage
from app.ads import media_probe
from app.ads import user_assets_repository as repo
from app.core.db import connection, new_id, set_tenant_scope

TASK = "background.ads_user_asset_preview"

logger = logging.getLogger(__name__)


def acquire_slot(conn, org, brand, kind="upload"):
    for lane in range(2):
        key = f"ads-{kind}:{org}:{brand}:{lane}"
        row = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok", (key,)
        ).fetchone()
        conn.commit()
        if row and row["ok"]:
            return key
    raise ValueError("同時最多處理 2 個檔案，請稍候再試。")


def release_slot(conn, key):
    conn.rollback()
    conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))
    conn.commit()


def begin_upload(conn, org, brand, upload_id):
    upload = repo.get_upload(conn, org, brand, upload_id)
    if upload["status"] == "complete":
        raise ValueError("這個檔案已完成上傳，不需重傳。")
    if not 0 < (upload["expected_size"] or 0) <= media_probe.MAX_BYTES:
        raise ValueError("檔案超過 50 MiB 或沒有內容，請另建批次。")
    key = f"{org}/brands/{brand}/user-assets/uploads/{upload_id}/{new_id('attempt')}/original"
    orphans = list(upload["orphan_keys"])
    if upload["storage_key"] and upload["storage_key"] not in orphans:
        orphans.append(upload["storage_key"])
    repo.set_upload(
        conn,
        org,
        brand,
        upload_id,
        status="uploading",
        storage_key=key,
        error=None,
        sha256=None,
        mime_type=None,
        byte_size=None,
        orphan_keys=orphans,
    )
    return repo.get_upload(conn, org, brand, upload_id)


def fail_upload(conn, org, brand, upload_id, reason):
    conn.rollback()
    conn.execute(
        "UPDATE ads_asset_upload SET status='failed',error=%s,updated_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND id=%s AND status<>'complete'",
        (reason, org, brand, upload_id),
    )
    conn.commit()


def enqueue_preview(asset):
    lock = "asset-preview:" + asset["id"]
    if not background.is_active(lock):
        background.enqueue(
            TASK,
            org_id=asset["org_id"],
            lock=lock,
            brand_id=asset["brand_id"],
            asset_id=asset["id"],
        )


def cleanup_upload(conn, org, brand, upload_id):
    upload = repo.get_upload(conn, org, brand, upload_id)
    prefix = f"{org}/brands/{brand}/user-assets/uploads/{upload_id}/"
    retained = []
    for key in upload["orphan_keys"]:
        if not key.startswith(prefix):
            retained.append(key)
            continue
        used = conn.execute(
            "SELECT 1 FROM ads_user_asset WHERE org_id=%s AND brand_id=%s AND storage_key=%s",
            (org, brand, key),
        ).fetchone()
        if used:
            continue
        conn.commit()
        try:
            storage.delete(org_id=org, key=key)
        except storage.StorageError:
            retained.append(key)
    repo.set_upload(conn, org, brand, upload_id, orphan_keys=retained)


def accept_upload(conn, org, brand, upload_id, content):
    upload = repo.get_upload(conn, org, brand, upload_id)
    if (
        not content
        or len(content) > media_probe.MAX_BYTES
        or len(content) != upload["expected_size"]
    ):
        fail_upload(conn, org, brand, upload_id, "檔案大小不符或超過 50 MiB，請重試。")
        return repo.get_upload(conn, org, brand, upload_id)
    try:
        mime = media_probe.sniff(content)
    except media_probe.MediaError as exc:
        fail_upload(conn, org, brand, upload_id, str(exc))
        return repo.get_upload(conn, org, brand, upload_id)
    digest = hashlib.sha256(content).hexdigest()
    repo.set_upload(
        conn,
        org,
        brand,
        upload_id,
        status="storage_pending",
        sha256=digest,
        mime_type=mime,
        byte_size=len(content),
    )
    # Each upload has its own key. Concurrent duplicate originals never overwrite one another.
    try:
        storage.put(
            org_id=org,
            key=upload["storage_key"],
            filename=upload["filename"],
            content=content,
            content_type=mime,
        )
    except storage.StorageError:
        repo.set_upload(
            conn,
            org,
            brand,
            upload_id,
            status="reconcile_pending",
            error="儲存尚未確認，可重試核對；其他檔案已保留。",
        )
        return repo.get_upload(conn, org, brand, upload_id)
    try:
        asset = repo.finalize_original(conn, org, brand, upload_id)
    except Exception:
        conn.rollback()
        repo.set_upload(
            conn,
            org,
            brand,
            upload_id,
            status="reconcile_pending",
            error="原檔已送存，資料登記待重試。",
        )
        return repo.get_upload(conn, org, brand, upload_id)
    cleanup_upload(conn, org, brand, upload_id)
    enqueue_preview(asset)
    return repo.get_upload(conn, org, brand, upload_id)


def reconcile_upload(conn, org, brand, upload_id):
    upload = repo.get_upload(conn, org, brand, upload_id)
    if upload["status"] == "complete":
        cleanup_upload(conn, org, brand, upload_id)
        asset = repo.get_asset(conn, org, brand, upload["asset_id"])
        enqueue_preview(asset)
        return repo.get_upload(conn, org, brand, upload_id)
    if not upload["storage_key"] or not upload["sha256"]:
        raise ValueError("沒有可核對的原檔，請重新上傳此檔。")
    conn.commit()
    try:
        content, _ = storage.get(org_id=org, key=upload["storage_key"])
    except storage.StorageError:
        fail_upload(conn, org, brand, upload_id, "原檔尚未送存成功，請重新上傳此檔。")
        return repo.get_upload(conn, org, brand, upload_id)
    if (
        len(content) > media_probe.MAX_BYTES
        or hashlib.sha256(content).hexdigest() != upload["sha256"]
    ):
        fail_upload(conn, org, brand, upload_id, "原檔完整性核對失敗，請重新上傳此檔。")
        return repo.get_upload(conn, org, brand, upload_id)
    asset = repo.finalize_original(conn, org, brand, upload_id)
    cleanup_upload(conn, org, brand, upload_id)
    enqueue_preview(asset)
    return repo.get_upload(conn, org, brand, upload_id)


def retry_preview(conn, org, brand, asset_id):
    asset = repo.get_asset(conn, org, brand, asset_id)
    if asset["status"] == "processing":
        raise ValueError("預覽仍在處理，請稍候。")
    conn.execute(
        "UPDATE ads_user_asset SET "
        "status='pending',error=NULL,preview_attempts=0,next_attempt_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org, brand, asset_id),
    )
    conn.commit()
    enqueue_preview(asset)
    return repo.get_asset(conn, org, brand, asset_id)


def process_preview(org_id, brand_id, asset_id):
    with connection() as conn:
        set_tenant_scope(conn, org_id)
        asset = repo.get_asset(conn, org_id, brand_id, asset_id)
        if asset["status"] not in {"pending", "retryable"}:
            return
        try:
            slot = acquire_slot(conn, org_id, brand_id, "preview")
        except ValueError:
            return  # Durable pending row is retried by the dispatcher.
        ready = False
        try:
            changed = conn.execute(
                "UPDATE ads_user_asset SET "
                "status='processing',preview_attempts=preview_attempts+1,"
                "processing_started_at=now() "
                "WHERE org_id=%s AND brand_id=%s AND id=%s AND status IN ('pending','retryable')",
                (org_id, brand_id, asset_id),
            ).rowcount
            conn.commit()
            if not changed:
                return
            try:
                content, _ = storage.get(org_id=org_id, key=asset["storage_key"])
                if hashlib.sha256(content).hexdigest() != asset["sha256"]:
                    raise media_probe.MediaError("原檔完整性核對失敗。")
                result = media_probe.preview(content)
                prefix = f"{org_id}/brands/{brand_id}/user-assets/derived/{asset_id}/"
                poster_key = prefix + "poster.jpg"
                preview_key = prefix + (
                    "clip.mp4" if result["preview_mime"] == "video/mp4" else "preview.jpg"
                )
                storage.put(
                    org_id=org_id,
                    key=poster_key,
                    filename="poster.jpg",
                    content=result["thumbnail"],
                    content_type="image/jpeg",
                )
                storage.put(
                    org_id=org_id,
                    key=preview_key,
                    filename="preview",
                    content=result["preview"],
                    content_type=result["preview_mime"],
                )
                conn.execute(
                    "UPDATE ads_user_asset SET "
                    "width=%s,height=%s,duration=%s,thumbnail_key=%s,preview_key=%s,"
                    "preview_mime=%s,preview_duration=%s,status='ready',error=NULL,"
                    "updated_at=now() "
                    "WHERE org_id=%s AND brand_id=%s AND id=%s",
                    (
                        result["width"],
                        result["height"],
                        result["duration"],
                        poster_key,
                        preview_key,
                        result["preview_mime"],
                        result["preview_duration"],
                        org_id,
                        brand_id,
                        asset_id,
                    ),
                )
                conn.commit()
                ready = True
            except Exception as exc:
                conn.rollback()
                reason = (
                    str(exc)
                    if isinstance(exc, media_probe.MediaError)
                    else "預覽暫時無法完成，原檔保留，可重試。"
                )
                permanent = isinstance(exc, media_probe.MediaError)
                conn.execute(
                    "UPDATE ads_user_asset SET status=CASE WHEN %s OR "
                    "preview_attempts>=3 THEN 'error' ELSE 'retryable' END,"
                    "error=%s,next_attempt_at=now()+interval '5 minutes',updated_at=now() "
                    "WHERE org_id=%s AND brand_id=%s AND id=%s",
                    (permanent, reason, org_id, brand_id, asset_id),
                )
                conn.commit()
        finally:
            release_slot(conn, slot)
        if ready:
            _settle_waiting_slots(conn, org_id, brand_id, asset_id)


def _settle_waiting_slots(conn, org_id, brand_id, asset_id):
    """Drill-8 #4: the slots waiting on this now-ready original are confirmed and assigned here,
    where the preview finishes. A failure is logged and swallowed: the asset stays `ready`, the
    slot keeps waiting and the user's own confirmation still works."""
    # Lazy, the way `slots` reaches `asset_suggestions`: `slots` loads the launch modules.
    from app.ads import slots

    try:
        slots.settle_ready_asset(conn, org_id, brand_id, asset_id)
    except Exception:
        conn.rollback()
        logger.exception("settling slots for ready asset %s failed", asset_id)


def dispatch_pending(timestamp):
    with connection() as conn:
        orgs = conn.execute(
            "SELECT DISTINCT org_id FROM ads_user_asset WHERE status<>'ready'"
        ).fetchall()
    for org in orgs:
        with connection() as conn:
            set_tenant_scope(conn, org["org_id"])
            conn.execute(
                "UPDATE ads_user_asset SET status=CASE WHEN preview_attempts>=3 THEN "
                "'error' ELSE 'retryable' END,error='處理中斷，可重試。',next_attempt_at=now() "
                "WHERE org_id=%s AND status='processing' AND "
                "processing_started_at<now()-interval '15 minutes'",
                (org["org_id"],),
            )
            rows = conn.execute(
                "SELECT * FROM ads_user_asset WHERE org_id=%s AND status IN "
                "('pending','retryable') "
                "AND next_attempt_at<=now()",
                (org["org_id"],),
            ).fetchall()
            conn.commit()
        for row in rows:
            enqueue_preview(dict(row))
