"""Bounded raw uploads; never parse an unbounded multipart body before enforcing limits."""

import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app import storage
from app.ads import media_probe
from app.ads import user_assets as service
from app.ads import user_assets_repository as repo
from app.core import db
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


async def _body(request, limit):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise web.ApiError(413, "upload_too_large", "檔案或批次超過大小上限。")
        data.extend(chunk)
    return bytes(data)


async def _json(request):
    try:
        body = json.loads(await _body(request, 64 * 1024))
    except (ValueError, UnicodeDecodeError):
        raise web.ApiError(400, "invalid_json", "無法讀取上傳描述。") from None
    if not isinstance(body, dict):
        raise web.ApiError(400, "invalid_json", "上傳描述必須是物件。")
    return body


def _error(exc):
    if isinstance(exc, repo.PlacementConflict):
        return web.ApiError(
            409, "placement_copy_conflict", str(exc), {"placement": jsonable_encoder(exc.current)}
        )
    return web.ApiError(409, "user_asset_unavailable", str(exc))


@router.post("/brands/{brand_id}/user-assets/batches")
async def create_batch(request: Request, brand_id: str):
    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return {
            "batch": repo.create_batch(
                db.current(), actor.org_id, brand_id, body.get("files"), str(actor.user_id)
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/user-assets/batches/{batch_id}")
def batch(request: Request, brand_id: str, batch_id: str):
    actor = web.require_actor(request)
    try:
        return {"batch": repo.batch_detail(db.current(), actor.org_id, brand_id, batch_id)}
    except ValueError as exc:
        raise web.ApiError(404, "upload_batch_unknown", str(exc)) from exc


def _lock_upload(conn, org, brand, upload_id):
    repo.get_upload(conn, org, brand, upload_id)
    slot = service.acquire_slot(conn, org, brand)
    item = f"ads-upload-item:{org}:{brand}:{upload_id}"
    row = conn.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok", (item,)
    ).fetchone()
    conn.commit()
    if not row or not row["ok"]:
        service.release_slot(conn, slot)
        raise ValueError("此檔案正在上傳，請稍候。")
    return slot, item


@router.put("/brands/{brand_id}/user-assets/uploads/{upload_id}/content")
async def upload(request: Request, brand_id: str, upload_id: str):
    actor = web.require_actor(request)
    conn = db.current()  # One physical connection; thread work is awaited, never concurrent on it.
    try:
        slot, item = _lock_upload(conn, actor.org_id, brand_id, upload_id)
    except ValueError as exc:
        raise _error(exc) from exc
    begun = False
    storing = None
    try:
        service.begin_upload(conn, actor.org_id, brand_id, upload_id)
        begun = True
        length = request.headers.get("content-length")
        if length is not None:
            try:
                count = int(length)
            except ValueError:
                raise web.ApiError(400, "invalid_length", "檔案大小標頭無效。") from None
            if count < 0 or count > media_probe.MAX_BYTES:
                raise web.ApiError(413, "upload_too_large", "單檔不能超過 50 MiB。")
        content = await _body(request, media_probe.MAX_BYTES)
        storing = asyncio.create_task(
            run_in_threadpool(
                service.accept_upload, conn, actor.org_id, brand_id, upload_id, content
            )
        )
        result = await asyncio.shield(storing)
        return {"upload": result}
    except (ClientDisconnect, asyncio.CancelledError):
        if storing is not None:
            while not storing.done():
                try:
                    await asyncio.shield(storing)
                except asyncio.CancelledError:
                    continue
            storing.result()
        elif begun:
            service.fail_upload(conn, actor.org_id, brand_id, upload_id, "上傳已中斷，可重試此檔。")
        raise
    except web.ApiError:
        if begun:
            service.fail_upload(
                conn, actor.org_id, brand_id, upload_id, "檔案超過大小上限或請求無效，可重試此檔。"
            )
        raise
    except ValueError as exc:
        if begun:
            service.fail_upload(conn, actor.org_id, brand_id, upload_id, str(exc))
        raise _error(exc) from exc
    finally:
        service.release_slot(conn, item)
        service.release_slot(conn, slot)


@router.post("/brands/{brand_id}/user-assets/uploads/{upload_id}/retry")
def retry_upload(request: Request, brand_id: str, upload_id: str):
    actor = web.require_actor(request)
    conn = db.current()
    try:
        slot, item = _lock_upload(conn, actor.org_id, brand_id, upload_id)
    except ValueError as exc:
        raise _error(exc) from exc
    try:
        return {"upload": service.reconcile_upload(conn, actor.org_id, brand_id, upload_id)}
    except ValueError as exc:
        raise _error(exc) from exc
    finally:
        service.release_slot(conn, item)
        service.release_slot(conn, slot)


@router.get("/brands/{brand_id}/user-assets")
def assets(
    request: Request, brand_id: str, cursor: str | None = None, upload_cursor: str | None = None
):
    actor = web.require_actor(request)
    return repo.list_assets(db.current(), actor.org_id, brand_id, cursor, upload_cursor)


@router.post("/brands/{brand_id}/user-assets/{asset_id}/retry-preview")
def retry_preview(request: Request, brand_id: str, asset_id: str):
    actor = web.require_actor(request)
    try:
        return {"asset": service.retry_preview(db.current(), actor.org_id, brand_id, asset_id)}
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/user-assets/{asset_id}/{kind}")
def content(request: Request, brand_id: str, asset_id: str, kind: str):
    actor = web.require_actor(request)
    try:
        asset = repo.get_asset(db.current(), actor.org_id, brand_id, asset_id)
    except ValueError as exc:
        raise web.ApiError(404, "user_asset_unknown", str(exc)) from exc
    if kind not in {"download", "preview", "thumbnail"}:
        raise web.ApiError(404, "asset_content_unknown", "找不到素材內容。")
    key = asset[
        {"download": "storage_key", "preview": "preview_key", "thumbnail": "thumbnail_key"}[kind]
    ]
    if not key:
        raise web.ApiError(409, "preview_pending", asset["error"] or "預覽尚未完成，原檔可下載。")
    try:
        data, mime = storage.get(org_id=actor.org_id, key=key)
    except storage.StorageError:
        raise web.ApiError(
            502, "asset_storage_unavailable", "暫時無法取得素材，請稍後重試。"
        ) from None
    disposition = "attachment" if kind == "download" else "inline"
    filename = quote(asset["filename"], safe="")
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Accept-Ranges": "bytes",
    }
    requested = request.headers.get("range")
    if requested and requested.startswith("bytes=") and "," not in requested:
        try:
            start, end = requested[6:].split("-", 1)
            begin = int(start) if start else max(0, len(data) - int(end))
            stop = int(end) if start and end else len(data) - 1
            if not 0 <= begin <= stop < len(data):
                raise ValueError()
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        headers["Content-Range"] = f"bytes {begin}-{stop}/{len(data)}"
        return Response(data[begin : stop + 1], status_code=206, media_type=mime, headers=headers)
    return Response(data, media_type=mime, headers=headers)


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/placements")
def placements(request: Request, brand_id: str, campaign_id: str, history: bool = False):
    actor = web.require_actor(request)
    try:
        return {
            "placements": repo.list_placements(
                db.current(), actor.org_id, brand_id, campaign_id, history
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/placements")
async def attach(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    body = await _json(request)
    try:
        result = repo.attach_selected(
            db.current(), actor.org_id, brand_id, campaign_id, body, str(actor.user_id)
        )
        return {"placement": result}
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/slots")
def campaign_slots(request: Request, brand_id: str, campaign_id: str):
    from app.ads import slots

    actor = web.require_actor(request)
    try:
        return slots.read(db.current(), actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(404, "campaign_unknown", str(exc)) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/slots/{ad_id}/upload")
async def upload_into_slot(request: Request, brand_id: str, campaign_id: str, ad_id: str):
    from app.ads import slots

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return slots.upload(
            db.current(), actor.org_id, brand_id, campaign_id, ad_id, body, str(actor.user_id)
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.patch("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}")
async def revise(request: Request, brand_id: str, campaign_id: str, placement_id: str):
    actor = web.require_actor(request)
    body = await _json(request)
    expected = body.pop("expected_revision", None)
    try:
        return {
            "placement": repo.revise(
                db.current(),
                actor.org_id,
                brand_id,
                campaign_id,
                placement_id,
                expected,
                body,
                str(actor.user_id),
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/asset-suggestions")
async def suggest_assets(request: Request, brand_id: str, campaign_id: str):
    from app.ads import asset_suggestions

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return {
            "batch": asset_suggestions.request(
                db.current(),
                actor.org_id,
                brand_id,
                campaign_id,
                body.get("placements"),
                body.get("idempotency_key"),
                body.get("summary", ""),
            ),
            "limits": {
                "max_placements": 10,
                "input_code_points": 12000,
                "response_code_points": 16384,
                "timeout_seconds": 120,
                "codex_notice": asset_suggestions.policy.CODEX_NOTICE,
            },
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/asset-suggestions/{batch_id}")
def asset_suggestion_batch(request: Request, brand_id: str, campaign_id: str, batch_id: str):
    from app.ads import asset_suggestions

    actor = web.require_actor(request)
    try:
        return {
            "batch": asset_suggestions.get_batch(
                db.current(), actor.org_id, brand_id, campaign_id, batch_id
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/confirm")
async def confirm_placement(request: Request, brand_id: str, campaign_id: str, placement_id: str):
    from app.ads import asset_suggestions, slots

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        result = asset_suggestions.confirm(
            db.current(),
            actor.org_id,
            brand_id,
            campaign_id,
            placement_id,
            body.get("expected_revision"),
            body.get("batch_id"),
            str(actor.user_id),
        )
        if result.get("confirmed_at"):
            # A file uploaded into a slot is assigned to that planned ad once confirmed.
            slots.settle(db.current(), actor.org_id, brand_id, campaign_id, placement_id)
        return {"placement": result}
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/asset-suggestions")
def list_asset_suggestion_batches(
    request: Request, brand_id: str, campaign_id: str, cursor: str | None = None, limit: int = 20
):
    from app.ads import asset_suggestions

    actor = web.require_actor(request)
    try:
        return asset_suggestions.list_batches(
            db.current(), actor.org_id, brand_id, campaign_id, after=cursor, limit=limit
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/handoff")
def asset_handoff(
    request: Request, brand_id: str, campaign_id: str, placement_id: str, revision: int
):
    from app.ads import asset_binding

    actor = web.require_actor(request)
    try:
        return asset_binding.handoff(
            db.current(), actor.org_id, brand_id, campaign_id, placement_id, revision
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get(
    "/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/binding-candidates"
)
def asset_binding_candidates(
    request: Request,
    brand_id: str,
    campaign_id: str,
    placement_id: str,
    revision: int,
    platform: str,
    account_id: str,
    cursor: str | None = None,
):
    from app.ads import asset_binding

    actor = web.require_actor(request)
    try:
        return asset_binding.candidates(
            db.current(),
            actor.org_id,
            brand_id,
            campaign_id,
            placement_id,
            revision,
            platform=platform,
            account_id=account_id,
            after=cursor,
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/self-report")
async def asset_self_report(request: Request, brand_id: str, campaign_id: str, placement_id: str):
    from app.ads import asset_binding_repository

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return {
            "binding": asset_binding_repository.report(
                db.current(),
                actor.org_id,
                brand_id,
                campaign_id,
                placement_id,
                body.get("expected_revision"),
                str(actor.user_id),
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


async def _await_binding_work(function, *args, **kwargs):
    task = asyncio.create_task(run_in_threadpool(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/verify-binding")
async def asset_verify_binding(
    request: Request, brand_id: str, campaign_id: str, placement_id: str
):
    from app.ads import asset_binding

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return {
            "binding": await _await_binding_work(
                asset_binding.verify,
                db.current(),
                actor.org_id,
                brand_id,
                campaign_id,
                placement_id,
                body.get("expected_revision"),
                body.get("entity_id"),
                str(actor.user_id),
                user_verified=body.get("user_verified", False),
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/end-binding")
async def asset_end_binding(request: Request, brand_id: str, campaign_id: str, placement_id: str):
    from app.ads import asset_binding

    actor = web.require_actor(request)
    body = await _json(request)
    try:
        return {
            "binding": asset_binding.end(
                db.current(),
                actor.org_id,
                brand_id,
                campaign_id,
                placement_id,
                body.get("expected_revision"),
                body.get("binding_id"),
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/placements/{placement_id}/version-metrics")
def asset_version_metrics(
    request: Request,
    brand_id: str,
    campaign_id: str,
    placement_id: str,
    revision: int,
    start: str,
    end: str,
):
    from datetime import date

    from app.ads import asset_binding

    actor = web.require_actor(request)
    try:
        return asset_binding.metrics(
            db.current(),
            actor.org_id,
            brand_id,
            campaign_id,
            placement_id,
            revision,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
        )
    except ValueError as exc:
        raise _error(exc) from exc
