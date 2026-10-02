"""Contract D (F27): GET-only, brand-scoped ads-track learning list (`app/ads/ads_learnings.py`).
Brand-scoped only (no campaign in the path) -- same pattern as `month_budget_routes.py`'s
`change-control-summary`.

F46 Contract L: `coordinate-learnings` serves `learning_view.learnings_view` as is -- the one read
品牌智庫 「投放學到的」, the closeout dialog and the month review share. `campaign_id` /
`sell_way_id` are filters, not lookups: an unknown one of this brand reads as an empty list."""

from fastapi import APIRouter, Depends, Request

from app.ads import ads_learnings as service
from app.ads import learning_view
from app.core import db
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/learnings")
def list_learnings(brand_id: str):
    return {"learnings": service.list_for_brand(db.current(), brand_id)}


@router.get("/brands/{brand_id}/coordinate-learnings")
def coordinate_learnings(request: Request, brand_id: str, campaign_id: str | None = None,
                         sell_way_id: str | None = None):
    org_id = web.require_actor(request).org_id
    return learning_view.learnings_view(
        db.current(), org_id, brand_id, campaign_id=campaign_id or None,
        sell_way_id=sell_way_id or None,
    )
