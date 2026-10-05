"""Brand-scoped local approvals and explicitly read-only platform checks."""

from typing import Literal

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


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: str = Field(min_length=1, max_length=2000)
    revisit_at: str | None = None
    revisit_on: str | None = None


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    month: str
    items: list[dict] = Field(min_length=1, max_length=30)
    supersedes_id: str | None = None
    review_id: str | None = None
    recommendation_id: str | None = None
    material_task_id: str | None = None
    material_revision: int | None = None
    # F27-I25: only this literal is accepted (Contract F's cleanup proposal match); anything else
    # is a 422 from pydantic before `change_control.create` ever sees it.
    source: Literal["cleanup"] | None = None
    # F29-I01 Contract B: the proposed cleanup ads the user unticked (only with `source`).
    declined_ids: list[str] | None = None
    # F47-I07 (drill-10 Q3): the user's 拒絕／暫緩 on the set this call creates, written in the
    # same transaction (`change_control.create`). Never part of the set's own hashes.
    decide: DecisionRequest | None = None


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_hash: str


def revisit_instant(request, revisit_on, revisit_at):
    """F50 Contract K: a deferral date `revisit_on` ("YYYY-MM-DD", the org's calendar) as the
    stored instant (`change_control_data.deferral_start`: that day's 00:00 in the org zone),
    refused with 400 unless after the org's today. `revisit_at` (an instant) is still accepted
    until the frontend senders move (F50-I12)."""
    if revisit_on is None:
        return revisit_at
    actor = web.require_actor(request)
    try:
        return data.deferral_start(web.conn, actor.org_id, revisit_on).isoformat()
    except ValueError as exc:
        raise web.ApiError(400, "revisit_on_invalid", str(exc)) from None


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
    # F27-I25/F29-I01: keep the dumped payload's key set identical to before these fields existed
    # when `source`/`declined_ids` are unset, so existing sets' `request_hash`/`content_hash` are
    # unaffected.
    payload = body.model_dump()
    decision = payload.pop("decide", None)
    if decision is not None:
        decision["revisit_at"] = revisit_instant(
            request, decision.pop("revisit_on", None), decision.get("revisit_at"))
    for key in ("source", "declined_ids"):
        if payload.get(key) is None:
            payload.pop(key, None)
    return {
        "change_set": _run(
            request,
            brand_id,
            campaign_id,
            service.create,
            payload,
            str(web.require_actor(request).user_id),
            decision,
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
            revisit_instant(request, body.revisit_on, body.revisit_at),
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
