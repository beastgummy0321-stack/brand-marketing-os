"""Manual handoff submissions and read-only verification endpoints."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import (
    change_control_launch,
    handoff_assignment,
    handoff_check,
    handoff_data,
    handoff_new_ad,
    handoff_reconsider,
)
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str = Field(min_length=1, max_length=100)
    source_account: str = Field(min_length=1, max_length=200)
    native_kind: str = Field(min_length=1, max_length=100)
    native_id: str = Field(min_length=1, max_length=200)
    user_verified: bool = False


class NewAdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    month: str
    placement_id: str
    revision: int = Field(ge=1)
    destination_entity_id: str
    reason: str = Field(min_length=1, max_length=2000)
    review_id: str | None = None
    recommendation_id: str | None = None
    replaces_entity_id: str | None = None


class ReconsiderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class LaunchDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_set_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(min_length=64, max_length=64)


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placement_id: str | None
    revision: int | None = Field(ge=1)


def _run(request, brand, campaign, function, *args):
    try:
        return function(web.conn, web.require_actor(request).org_id, brand, campaign, *args)
    except ValueError as exc:
        web.conn.rollback()
        raise web.ApiError(409, "handoff_unavailable", str(exc)) from None


@router.get("/handoff")
def workspace(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, handoff_data.workspace)


def _launch_decision(request, brand_id, campaign_id, function, body):
    """Stale launch exits (F28): both answer with the refreshed handoff workspace."""
    _run(
        request,
        brand_id,
        campaign_id,
        function,
        body.change_set_id,
        body.content_hash,
        str(web.require_actor(request).user_id),
    )
    return _run(request, brand_id, campaign_id, handoff_data.workspace)


@router.post("/handoff/launch/reapprove")
def reapprove_launch(
    request: Request, brand_id: str, campaign_id: str, body: LaunchDecisionRequest
):
    return _launch_decision(request, brand_id, campaign_id, change_control_launch.reapprove, body)


@router.post("/handoff/launch/revert")
def revert_launch(request: Request, brand_id: str, campaign_id: str, body: LaunchDecisionRequest):
    return _launch_decision(request, brand_id, campaign_id, change_control_launch.revert, body)


@router.get("/launch-materials")
def assignments(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, handoff_assignment.workspace)


@router.put("/launch-materials/{ad_id}")
def assign_material(
    request: Request, brand_id: str, campaign_id: str, ad_id: str, body: AssignmentRequest
):
    return _run(
        request,
        brand_id,
        campaign_id,
        handoff_assignment.assign,
        ad_id,
        body.placement_id,
        body.revision,
    )


@router.post("/handoff/{item_id}/reconsider")
def reconsider(
    request: Request, brand_id: str, campaign_id: str, item_id: str, body: ReconsiderRequest
):
    return {
        "item": _run(
            request, brand_id, campaign_id, handoff_reconsider.reconsider, item_id, body.reason
        )
    }


@router.post("/handoff/{item_id}/report")
def report(request: Request, brand_id: str, campaign_id: str, item_id: str):
    return {"item": _run(request, brand_id, campaign_id, handoff_data.report, item_id)}


@router.post("/handoff/{item_id}/check")
def check(request: Request, brand_id: str, campaign_id: str, item_id: str, body: CheckRequest):
    return {
        "item": _run(
            request,
            brand_id,
            campaign_id,
            handoff_check.check,
            item_id,
            body.model_dump(),
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/new-ad-handoffs")
def new_ad(request: Request, brand_id: str, campaign_id: str, body: NewAdRequest):
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            handoff_new_ad.create,
            body.model_dump(),
            str(web.require_actor(request).user_id),
        )
    }
