"""Scoped cache/import/sync APIs. HTTP handlers never wait for platform reads."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from app.ads import channels
from app.ads import external_repository as repo
from app.ads import external_sync as sync
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


def _error(exc):
    return web.ApiError(409, "external_source_unavailable", str(exc))


def _sources(conn, org, brand):
    result = []
    for channel in channels.CHANNELS:
        reader = channels.external_reader(channel["key"])
        if reader:
            result.extend(
                {"platform": channel["key"], "label": channel["label"], **a}
                for a in reader.accounts(conn, org, brand)
            )
    return result


@router.get("/brands/{brand_id}/existing-campaigns")
def existing(
    request: Request,
    brand_id: str,
    platform: str | None = None,
    source_account: str | None = None,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=100),
):
    actor = web.require_actor(request)
    sources = _sources(web.conn, actor.org_id, brand_id)
    if not sources and platform is None:
        return {"items": [], "sources": [], "job": None, "next_cursor": None}
    platform = platform or sources[0]["platform"]
    source_account = source_account or next(
        (a["account_id"] for a in sources if a["platform"] == platform), ""
    )
    try:
        sync.account_reader(web.conn, actor.org_id, brand_id, platform, source_account)
        row = web.conn.execute(
            "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s "
            "AND platform=%s AND source_account=%s",
            (actor.org_id, brand_id, platform, source_account),
        ).fetchone()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        stale = not row or (
            row["status"] not in {"pending", "running"}
            and (
                row["last_attempt_at"] is None
                or now - row["last_attempt_at"] > timedelta(minutes=5)
            )
            and (
                row["last_success_at"] is None or now - row["last_success_at"] > timedelta(hours=6)
            )
        )
        job = (
            sync.request_sync(web.conn, actor.org_id, brand_id, platform, source_account)
            if stale
            else dict(row or {})
        )
        result = repo.listing(
            web.conn, actor.org_id, brand_id, platform, source_account, after=cursor, limit=limit
        )
    except ValueError as exc:
        raise _error(exc) from exc
    return {
        **result,
        "sources": sources,
        "platform": platform,
        "source_account": source_account,
        "job": job,
    }


class Refresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str
    source_account: str
    start: date | None = None
    end: date | None = None


@router.post("/brands/{brand_id}/existing-campaigns/refresh")
def refresh(request: Request, brand_id: str, body: Refresh):
    actor = web.require_actor(request)
    try:
        return {"job": sync.request_sync(web.conn, actor.org_id, brand_id, **body.model_dump())}
    except ValueError as exc:
        raise _error(exc) from exc


class Import(Refresh):
    native_kind: str
    native_id: str


@router.post("/brands/{brand_id}/imports")
def import_campaign(request: Request, brand_id: str, body: Import):
    actor = web.require_actor(request)
    try:
        sync.account_reader(web.conn, actor.org_id, brand_id, body.platform, body.source_account)
        campaign = repo.import_cached(
            web.conn,
            actor.org_id,
            brand_id,
            body.platform,
            body.source_account,
            body.native_kind,
            body.native_id,
            str(actor.user_id),
        )
        web.conn.commit()
        job = (
            sync.request_sync(
                web.conn,
                actor.org_id,
                brand_id,
                body.platform,
                body.source_account,
                start=body.start,
                end=body.end,
            )
            if campaign["origin"] == "imported"
            else None
        )
        return {"campaign": campaign, "job": job}
    except ValueError as exc:
        raise _error(exc) from exc


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date | None = None
    end: date | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/sync")
def campaign_sync(request: Request, brand_id: str, campaign_id: str, body: Window):
    actor = web.require_actor(request)
    try:
        repo._campaign(web.conn, actor.org_id, brand_id, campaign_id)
        source = web.conn.execute(
            "SELECT platform,source_account FROM ads_external_entity "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND parent_native_id IS NULL",
            (actor.org_id, brand_id, campaign_id),
        ).fetchone()
        if source is None:
            raise ValueError("此工作區沒有可同步的原生來源。")
        return {
            "job": sync.request_sync(
                web.conn, actor.org_id, brand_id, **dict(source), **body.model_dump()
            )
        }
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/brands/{brand_id}/sync-jobs/{job_id}")
def job_status(request: Request, brand_id: str, job_id: str):
    actor = web.require_actor(request)
    try:
        job = repo.get_job(web.conn, actor.org_id, brand_id, job_id)
    except ValueError as exc:
        raise web.ApiError(404, "sync_job_unknown", str(exc)) from exc
    try:
        sync.account_reader(
            web.conn, actor.org_id, brand_id, job["platform"], job["source_account"]
        )
        connected = True
    except ValueError:
        connected = False
    return {"job": job, "connected": connected}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/external")
def external_view(
    request: Request,
    brand_id: str,
    campaign_id: str,
    start: date | None = None,
    end: date | None = None,
    entity_cursor: str | None = None,
    observation_cursor: str | None = None,
    limit: int = Query(100, ge=1, le=100),
):
    actor = web.require_actor(request)
    try:
        return repo.external_view(
            web.conn,
            actor.org_id,
            brand_id,
            campaign_id,
            start=start,
            end=end,
            entity_after=entity_cursor,
            observation_after=observation_cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise _error(exc) from exc
