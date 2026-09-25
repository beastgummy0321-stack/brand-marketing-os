"""Brand-scoped review reads, explicit requests and human decisions."""

from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import review_monitor
from app.ads import review_rounds as service
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, max_length=200)
    start: date
    end: date
    previous_id: str | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: str = Field(min_length=1, max_length=2000)
    revisit_at: str | None = None


def _run(request, brand, campaign, function, *args):
    actor = web.require_actor(request)
    try:
        return function(web.conn, actor.org_id, brand, campaign, *args)
    except ValueError as exc:
        web.conn.rollback()
        raise web.ApiError(409, "review_unavailable", str(exc)) from None


@router.get("/reviews")
def workspace(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, service.workspace)


@router.post("/reviews")
def create(request: Request, brand_id: str, campaign_id: str, body: CreateRequest):
    review = _run(
        request,
        brand_id,
        campaign_id,
        service.request_manual,
        body.entity_id,
        body.start,
        body.end,
        body.previous_id,
        str(web.require_actor(request).user_id),
    )
    return {
        "review": review,
        "monitor": review_monitor.get(
            web.conn, review["org_id"], brand_id, campaign_id, review["entity_id"]
        ),
    }


@router.post("/reviews/{review_id}/retry")
def retry(request: Request, brand_id: str, campaign_id: str, review_id: str):
    review = _run(
        request,
        brand_id,
        campaign_id,
        service.retry,
        review_id,
        str(web.require_actor(request).user_id),
    )
    return {
        "review": review,
        "monitor": review_monitor.get(
            web.conn, review["org_id"], brand_id, campaign_id, review["entity_id"]
        ),
    }


@router.get("/reviews/{review_id}")
def detail(request: Request, brand_id: str, campaign_id: str, review_id: str):
    return {"review": _run(request, brand_id, campaign_id, service.get, review_id)}


@router.post("/reviews/{review_id}/decision")
def decide(
    request: Request, brand_id: str, campaign_id: str, review_id: str, body: DecisionRequest
):
    return {
        "review": _run(
            request,
            brand_id,
            campaign_id,
            service.decide,
            review_id,
            body.decision,
            body.reason,
            body.revisit_at,
        )
    }
