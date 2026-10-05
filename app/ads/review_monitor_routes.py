"""Explicit per-ad monitoring preferences, independent of source collection."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import review_monitor as service
from app.ads.review_routes import _guard, _run

router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}", dependencies=[Depends(_guard)]
)


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    enabled: bool
    # F50 Contract I: bounds and the cadence default from `review_monitor` (served as `limits`).
    window_days: int = Field(
        default=7, ge=service.DAYS_RANGE[0], le=service.DAYS_RANGE[1])
    cadence_days: int = Field(
        default=service.DEFAULT_CADENCE_DAYS, ge=service.DAYS_RANGE[0], le=service.DAYS_RANGE[1])
    reset_window: bool = False


@router.get("/review-monitors")
def workspace(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, service.workspace)


@router.get("/review-monitors/{entity_id}")
def detail(request: Request, brand_id: str, campaign_id: str, entity_id: str):
    return {"monitor": _run(request, brand_id, campaign_id, service.get, entity_id)}


@router.put("/review-monitors/{entity_id}")
def update(request: Request, brand_id: str, campaign_id: str, entity_id: str, body: MonitorRequest):
    return {
        "monitor": _run(request, brand_id, campaign_id, service.put, entity_id, body.model_dump())
    }
