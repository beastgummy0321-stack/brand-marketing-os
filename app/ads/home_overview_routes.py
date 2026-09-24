"""F28-I06 "Home overview": `GET /api/ads/brands/{b}/home?month=YYYY-MM` -- brand-scoped, same
guard and default-month rule as `month_summary_routes.py` (the month defaults to the org
timezone's current month). Read-only; see `home_overview.py`."""

from fastapi import APIRouter, Depends, Request

from app.ads import home_overview as service
from app.core import db, settings
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/home")
def get_home_overview(request: Request, brand_id: str, month: str | None = None):
    actor = web.require_actor(request)
    conn = db.current()
    month = month or settings.today_for_org(conn, org_id=actor.org_id).strftime("%Y-%m")
    try:
        return service.get_overview(conn, actor.org_id, brand_id, month)
    except ValueError as exc:
        raise web.ApiError(422, "home_overview_invalid", str(exc)) from None
