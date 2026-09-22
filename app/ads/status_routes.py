"""Contract I (F27-I09): the brand-wide sync/queue status summary -- brand-scoped only (no
campaign in the path, same pattern as `month_summary_routes.py`/`learning_routes.py`'s
`/learnings`): the summary spans every non-closed campaign of the brand."""

from fastapi import APIRouter, Depends, Request

from app.ads import status_summary
from app.core import db
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/status-summary")
def get_status_summary(request: Request, brand_id: str):
    actor = web.require_actor(request)
    return status_summary.get_status_summary(db.current(), actor.org_id, brand_id)
