"""Contract C (F27): GET-only, per-ad AI angle candidates. The first call enqueues a background
LLM task through the existing gateway; later calls (even from other browsers) return the cached
result keyed by (entity, copy hash) -- see `app/ads/angles.py` for the cache mechanism."""

from fastapi import APIRouter, Depends, Request

from app.ads import angles as service
from app.ads.review_routes import _guard, _run

router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


@router.get("/entities/{entity_id}/angles")
def get_angles(request: Request, brand_id: str, campaign_id: str, entity_id: str):
    return _run(request, brand_id, campaign_id, service.get, entity_id)
