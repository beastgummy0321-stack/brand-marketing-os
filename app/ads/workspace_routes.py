"""app/ads/workspace_routes.py — F30-I06 (Contract E): the campaign workspace reads,
`GET /api/ads/brands/{b}/campaigns/{c}/workspace|structure|timeline`. Brand-scoped, same guard as
`home_overview_routes.py`; an unknown campaign is 404. Read-only; see `workspace_reads.py`."""

from fastapi import APIRouter, Depends, Request

from app.ads import workspace_reads as service
from app.core import db
from app.shared import web

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


def _read(request: Request, brand_id: str, campaign_id: str, fn):
    actor = web.require_actor(request)
    try:
        return fn(db.current(), actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(404, str(exc), CAMPAIGN_UNKNOWN_MESSAGE) from None


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/workspace")
def get_workspace(request: Request, brand_id: str, campaign_id: str):
    return _read(request, brand_id, campaign_id, service.workspace)


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/structure")
def get_structure(request: Request, brand_id: str, campaign_id: str):
    return _read(request, brand_id, campaign_id, service.structure)


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/timeline")
def get_timeline(request: Request, brand_id: str, campaign_id: str):
    return _read(request, brand_id, campaign_id, service.timeline)
