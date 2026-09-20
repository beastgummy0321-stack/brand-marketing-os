"""Native source contracts: unknown values stay unknown and source dimensions stay separate."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Availability = Literal["available", "unknown", "unavailable", "derived_zero"]
IMPORTED_REASON = "既有活動只支援查看、同步與自帶素材安排；不使用內部策略、預算、模擬發布或結案。"
LEGACY_OPERATIONS = (
    "strategy",
    "budget",
    "pack",
    "publish",
    "bind",
    "simulate",
    "close",
    "comparison",
)


def capabilities(origin: str) -> dict:
    imported = origin == "imported"
    return {
        "allowed": ["view", "sync", "edit_goal", "add_assets", "arrange", "confirm"]
        if imported
        else ["view", "add_assets", "arrange", "confirm", *LEGACY_OPERATIONS],
        "unavailable": {key: IMPORTED_REASON for key in LEGACY_OPERATIONS} if imported else {},
    }


class ExternalEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    platform: str = Field(min_length=1)
    source_account: str = Field(min_length=1)
    native_kind: str = Field(min_length=1)
    native_id: str = Field(min_length=1)
    parent_native_kind: str | None = None
    parent_native_id: str | None = None
    native_label: str | None = None
    name: str | None = None
    objective: str | None = None
    native_status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget_type: Literal["daily", "lifetime", "unknown"] = "unknown"
    budget_amount: float | None = None
    budget_raw: dict[str, Any] = Field(default_factory=dict)
    currency: str | None = None
    budget_source: str | None = None
    availability: dict[str, Availability] = Field(default_factory=dict)
    creative: dict[str, Any] = Field(default_factory=dict)
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    sync_status: str = "unknown"
    sync_error: str | None = None

    @model_validator(mode="after")
    def parent_pair(self):
        if (self.parent_native_kind is None) != (self.parent_native_id is None):
            raise ValueError("parent_kind_and_id_required_together")
        return self


class ExternalObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    entity_id: str
    day: date
    metric_scope: str = Field(min_length=1)
    attribution_key: str = Field(min_length=1)
    currency: str | None = None
    spend: float | None = None
    impressions: int | None = None
    clicks: int | None = None
    purchases: float | None = None
    revenue: float | None = None
    availability: dict[str, Availability] = Field(default_factory=dict)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def metric_availability(self):
        for key in ("spend", "impressions", "clicks", "purchases", "revenue"):
            value = getattr(self, key)
            state = self.availability.setdefault(key, "unknown" if value is None else "available")
            if (state == "available") != (value is not None):
                raise ValueError("metric_availability_mismatch")
        return self
