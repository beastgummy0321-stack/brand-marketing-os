"""Comparison proposals are read-only until the user explicitly confirms their fingerprint."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import ab_pairs, experiments
from app.shared import web

router = APIRouter()


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    controls_checked: bool


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    overrides: dict[str, Any]


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/comparison", dependencies=[Depends(_guard)])
def read(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    try:
        return experiments.read(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(409, "comparison_unavailable", str(exc)) from exc


@router.put(
    "/brands/{brand_id}/campaigns/{campaign_id}/comparison", dependencies=[Depends(_guard)]
)
def put_settings(request: Request, brand_id: str, campaign_id: str, body: SettingsUpdate):
    actor = web.require_actor(request)
    try:
        experiments.save_settings(
            web.conn,
            actor.org_id,
            brand_id,
            campaign_id,
            revision=body.revision,
            overrides=body.overrides,
            actor=str(actor.user_id),
        )
        return experiments.read(web.conn, actor.org_id, brand_id, campaign_id)
    except experiments.StaleSettings as exc:
        raise web.ApiError(409, "comparison_settings_stale", str(exc)) from exc
    except experiments.ClosedSettings as exc:
        raise web.ApiError(409, "comparison_settings_closed", str(exc)) from exc
    except experiments.InvalidSettings as exc:
        raise web.ApiError(400, "comparison_settings_invalid", str(exc)) from exc
    except ValueError as exc:
        raise web.ApiError(409, "comparison_unavailable", str(exc)) from exc


class PauseLoser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/ab-pairs", dependencies=[Depends(_guard)])
def ab_pairs_read(request: Request, brand_id: str, campaign_id: str):
    """F29-I04 Contract F: automatic A/B pairs, judged on the campaign's daily ad rows."""
    actor = web.require_actor(request)
    try:
        return ab_pairs.read(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        raise web.ApiError(409, "ab_unavailable", str(exc)) from exc


@router.post(
    "/brands/{brand_id}/campaigns/{campaign_id}/ab-pairs/{pair_id}/pause-loser",
    dependencies=[Depends(_guard)],
)
def ab_pause_loser(request: Request, brand_id: str, campaign_id: str, pair_id: str,
                   body: PauseLoser):
    """F29-I04 Contract F: proposes pausing the loser as a local change set (approval still
    required); never writes to a platform."""
    actor = web.require_actor(request)
    try:
        change_set = ab_pairs.pause_loser(
            web.conn, actor.org_id, brand_id, campaign_id, pair_id, body.operation_id,
            str(actor.user_id),
        )
    except ValueError as exc:
        web.conn.rollback()
        status, code = {
            ab_pairs.PairUnknown: (404, "ab_pair_unknown"),
            ab_pairs.NotJudged: (409, "ab_not_judged"),
            ab_pairs.LoserUnbound: (409, "ab_loser_unbound"),
        }.get(type(exc), (409, "ab_unavailable"))
        raise web.ApiError(status, code, str(exc)) from exc
    return {"change_set": change_set}


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
