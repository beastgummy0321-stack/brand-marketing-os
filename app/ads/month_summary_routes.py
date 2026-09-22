"""Contract G (F27): the monthly review summary and suggestion dismissal -- brand-scoped only (no
campaign in the path, same pattern as `month_budget_routes.py`'s `change-control-summary` and
`learning_routes.py`'s `/learnings`): the summary spans every imported campaign of the brand, and
a dismissed suggestion's own campaign id travels inside its `key` (see `month_summary.py`)."""

from fastapi import APIRouter, Depends, Request

from app.ads import month_summary as service
from app.core import db, settings
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/month-summary")
def get_month_summary(request: Request, brand_id: str, month: str | None = None):
    actor = web.require_actor(request)
    conn = db.current()
    month = month or settings.today_for_org(conn, org_id=actor.org_id).strftime("%Y-%m")
    try:
        return service.get_summary(conn, actor.org_id, brand_id, month)
    except ValueError as exc:
        raise web.ApiError(422, "month_summary_invalid", str(exc)) from None


@router.post("/brands/{brand_id}/month-summary/suggestions/{key}/dismiss")
def dismiss_suggestion(request: Request, brand_id: str, key: str, month: str):
    actor = web.require_actor(request)
    try:
        service.dismiss_suggestion(db.current(), actor.org_id, brand_id, month, key)
    except ValueError as exc:
        raise web.ApiError(422, "month_summary_invalid", str(exc)) from None
    return {"ok": True}
