"""Scoped cache/import/sync APIs. HTTP handlers never wait for platform reads."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from app.ads import channels, connections
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


@router.get("/brands/{brand_id}/connections")
def connections_view(request: Request, brand_id: str):
    """F30 Contract H: every data source's own read state and this month's day calendar.
    Read-only -- unlike `existing` below, this read never requests a sync."""
    actor = web.require_actor(request)
    return connections.get_connections(web.conn, actor.org_id, brand_id)


@router.get("/brands/{brand_id}/existing-campaigns")
def existing(
    request: Request,
    brand_id: str,
    platform: str | None = None,
    source_account: str | None = None,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=100),
):
    """F49 Contract O: read-only -- the cached listing, the account's job and its outcome. It never
    requests a read (that is `POST …/existing-campaigns/refresh`); an unreadable account answers
    200 with its cached items, `job: null` and a failed outcome naming why."""
    actor = web.require_actor(request)
    sources = _sources(web.conn, actor.org_id, brand_id)
    if not sources and platform is None:
        return {"items": [], "sources": [], "job": None, "outcome": None, "next_cursor": None}
    platform = platform or sources[0]["platform"]
    source_account = source_account or next(
        (a["account_id"] for a in sources if a["platform"] == platform), ""
    )
    result = repo.listing(
        web.conn, actor.org_id, brand_id, platform, source_account, after=cursor, limit=limit
    )
    try:
        sync.account_reader(web.conn, actor.org_id, brand_id, platform, source_account)
    except ValueError as exc:
        job, outcome = None, sync.failed_outcome(exc)
    else:
        job = sync.account_job(web.conn, actor.org_id, brand_id, platform, source_account)
        outcome = sync.outcome(job["tasks"] if job else {})
    return {
        **result,
        "sources": sources,
        "platform": platform,
        "source_account": source_account,
        "job": job,
        "outcome": outcome,
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
        return {"job": sync.request_sync(web.conn, actor.org_id, brand_id,
                                         retry_failed_monthly=True, **body.model_dump())}
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
                # F49 Contract N: the campaign just imported is read even if it already ended.
                campaign_ids=(campaign["id"],),
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
    """Every job the re-read requested (`jobs`, drill-11 #14): each root account, or -- a campaign
    not yet on the platform (first launch handoff, drill 5) -- every bound account's listing.
    `job` is the first, kept for callers not yet on `jobs`. The campaign is read monitored or
    not (`request_campaign_sync` passes it as an explicit `campaign_ids`, F49 Contract N)."""
    actor = web.require_actor(request)
    try:
        repo._campaign(web.conn, actor.org_id, brand_id, campaign_id)
        jobs = sync.request_campaign_sync(
            web.conn, actor.org_id, brand_id, campaign_id, **body.model_dump()
        )
    except ValueError as exc:
        raise _error(exc) from exc
    return {"job": jobs[0], "jobs": jobs}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/sync-outcome")
def campaign_sync_outcome(request: Request, brand_id: str, campaign_id: str):
    """F49 Contract O: `{state, code, text, job_ids, last_success_at}` -- the worst outcome over
    the jobs covering the campaign. Read-only."""
    actor = web.require_actor(request)
    try:
        repo._campaign(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(404, "campaign_unknown", str(exc)) from exc
    return sync.campaign_outcome(web.conn, actor.org_id, brand_id, campaign_id)


@router.get("/brands/{brand_id}/sync-jobs/{job_id}")
def job_status(request: Request, brand_id: str, job_id: str, campaign_id: str | None = None):
    """`{job, connected, outcome}`; `campaign_id` scopes the outcome to that campaign's tasks
    (plus the account's own)."""
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
    return {
        "job": job,
        "connected": connected,
        "outcome": sync.outcome(job["tasks"], campaign_id=campaign_id),
    }


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
