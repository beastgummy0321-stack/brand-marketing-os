"""Contract D (F27): GET-only, brand-scoped ads-track learning list (`app/ads/ads_learnings.py`).
Brand-scoped only (no campaign in the path) -- same pattern as `month_budget_routes.py`'s
`change-control-summary`."""

from fastapi import APIRouter, Depends, Request

from app.ads import ads_learnings as service
from app.core import db
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/learnings")
def list_learnings(brand_id: str):
    return {"learnings": service.list_for_brand(db.current(), brand_id)}
