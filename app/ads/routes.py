"""app/ads/routes.py — /api/ads/*. Private: only app/ads/__init__.py imports this (container
contract §1); it is only ever loaded via `register()`.

F03-I01: read-only for now — the list and the workspace payload. Writes (create campaign,
publish, bind, ...) arrive in later issues. Shape (container contract §7): every handler is
`require_actor` -> `require_brand` -> one repository function -> wrap.
"""

from fastapi import APIRouter, Request

import app.shared.web as web
from app.ads import repository

router = APIRouter(prefix="/api/ads")

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"


@router.get("/brands/{brand_id}/campaigns")
def list_campaigns(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaigns = repository.list_campaigns(web.conn, actor.org_id, brand_id)
    return {"campaigns": campaigns}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}")
def get_campaign(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaign = repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)
    if campaign is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    return {"campaign": campaign}
