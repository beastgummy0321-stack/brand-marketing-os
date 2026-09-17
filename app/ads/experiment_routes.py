"""Comparison proposals are read-only until the user explicitly confirms their fingerprint."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.ads import experiments
from app.shared import web

router = APIRouter()


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    controls_checked: bool


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/comparison", dependencies=[Depends(_guard)])
def read(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    try:
        return experiments.read(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(409, "comparison_unavailable", str(exc)) from exc


@router.post(
    "/brands/{brand_id}/campaigns/{campaign_id}/comparison", dependencies=[Depends(_guard)]
)
def confirm(request: Request, brand_id: str, campaign_id: str, body: Confirmation):
    actor = web.require_actor(request)
    try:
        experiments.confirm(
            web.conn,
            actor.org_id,
            brand_id,
            campaign_id,
            fingerprint=body.fingerprint,
            controls_checked=body.controls_checked,
            actor=str(actor.user_id),
        )
        return experiments.read(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(409, "comparison_unavailable", str(exc)) from exc
