"""Brand-scoped local approvals and explicitly read-only platform checks."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import change_control as service
from app.ads import change_control_data as data
from app.ads import change_control_verify as verify
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    month: str
    items: list[dict] = Field(min_length=1, max_length=30)
    supersedes_id: str | None = None
    review_id: str | None = None
    recommendation_id: str | None = None


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: str = Field(min_length=1, max_length=2000)
    revisit_at: str | None = None


def _run(request, brand_id, campaign_id, function, *args):
    actor = web.require_actor(request)
    try:
        return function(web.conn, actor.org_id, brand_id, campaign_id, *args)
    except ValueError as exc:
        web.conn.rollback()
        raise web.ApiError(409, "change_control_unavailable", str(exc)) from None


@router.get("/change-control")
def workspace(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, service.workspace)


@router.post("/change-sets")
def create(request: Request, brand_id: str, campaign_id: str, body: CreateRequest):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            service.create,
            body.model_dump(),
            str(web.require_actor(request).user_id),
        )
    }


@router.get("/change-sets/{set_id}")
def detail(request: Request, brand_id: str, campaign_id: str, set_id: str):
    return {"change_set": _run(request, brand_id, campaign_id, data.get, set_id)}


@router.post("/change-sets/{set_id}/approve")
def approve(request: Request, brand_id: str, campaign_id: str, set_id: str, body: ApproveRequest):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            service.approve,
            set_id,
            body.content_hash,
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/change-sets/{set_id}/decision")
def decide(request: Request, brand_id: str, campaign_id: str, set_id: str, body: DecisionRequest):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            service.decide,
            set_id,
            body.decision,
            body.reason,
            body.revisit_at,
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/change-sets/{set_id}/items/{action_id}/report")
def report(request: Request, brand_id: str, campaign_id: str, set_id: str, action_id: str):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            service.report,
            set_id,
            action_id,
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/change-sets/{set_id}/items/{action_id}/check")
def check(request: Request, brand_id: str, campaign_id: str, set_id: str, action_id: str):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            verify.check,
            set_id,
            action_id,
            str(web.require_actor(request).user_id),
        )
    }
