"""Local-only isolated recovery, with identity checks before body validation."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import simulation_recovery as recovery
from app.shared import web

router = APIRouter()
Number = Annotated[float, Field(strict=True, ge=0, le=1e12, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=1000000000)]


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ad_id: str
    spend: Number
    impressions: Count
    clicks: Count
    purchases: Count
    revenue: Number


class Save(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Count
    mode: str
    rows: list[Row] = Field(max_length=200)


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_isolation: bool = False


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)
    return actor


def _error(exc):
    return web.ApiError(409, "simulation_recovery", str(exc))


@router.get(
    "/brands/{brand_id}/campaigns/{campaign_id}/simulation/{day}", dependencies=[Depends(_guard)]
)
def read(request: Request, brand_id: str, campaign_id: str, day: date):
    actor = web.require_actor(request)
    try:
        return recovery.read_day(web.conn, actor.org_id, brand_id, campaign_id, day)
    except ValueError as exc:
        raise _error(exc) from exc


@router.post(
    "/brands/{brand_id}/campaigns/{campaign_id}/simulation/start", dependencies=[Depends(_guard)]
)
def start(request: Request, brand_id: str, campaign_id: str, body: Start):
    actor = web.require_actor(request)
    try:
        recovery.start(
            web.conn,
            actor.org_id,
            brand_id,
            campaign_id,
            actor=str(actor.user_id),
            confirm_isolation=body.confirm_isolation,
        )
    except ValueError as exc:
        raise _error(exc) from exc
    return {"ok": True}


@router.put(
    "/brands/{brand_id}/campaigns/{campaign_id}/simulation/{day}", dependencies=[Depends(_guard)]
)
def save(request: Request, brand_id: str, campaign_id: str, day: date, body: Save):
    actor = web.require_actor(request)
    try:
        recovery.save_day(
            web.conn,
            actor.org_id,
            brand_id,
            campaign_id,
            day,
            [r.model_dump() for r in body.rows],
            revision=body.revision,
            mode=body.mode,
            actor=str(actor.user_id),
        )
        return recovery.read_day(web.conn, actor.org_id, brand_id, campaign_id, day)
    except ValueError as exc:
        raise _error(exc) from exc
