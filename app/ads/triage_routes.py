"""app/ads/triage_routes.py — F18-I02: GET .../triage, the program triage read. F18-I03: the
brand-level decision queue over triage, `POST .../queue/refresh` and `GET .../queue` (F18
outcome: backend only, no LLM, no platform write). Same auth shape as
`routes.py::get_campaign_target`: `require_actor` -> `require_brand` -> one read function -> wrap.
"""

from fastapi import APIRouter, Request

import app.shared.web as web
from app.ads import triage

router = APIRouter()

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/triage")
def get_campaign_triage(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        result = triage.classify(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(404, str(exc), CAMPAIGN_UNKNOWN_MESSAGE) from exc
    return {"triage": result}


@router.post("/brands/{brand_id}/queue/refresh")
def refresh_brand_queue(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {"queue": triage.refresh_queue(web.conn, actor.org_id, brand_id)}


@router.get("/brands/{brand_id}/queue")
def get_brand_queue(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {"queue": triage.get_queue(web.conn, actor.org_id, brand_id)}
