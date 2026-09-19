"""Saved monitoring state; opening a page never executes AI or platform reads."""

from fastapi import APIRouter, Depends, Request

from app.ads import runtime
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


@router.get("/runtime")
def detail(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    try:
        return runtime.view(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(404, "runtime_unavailable", "找不到這個活動的追蹤紀錄。") from exc
