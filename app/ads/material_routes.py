"""Campaign material API. Saving and explicit generation are separate actions."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import material_tasks as service
from app.shared import web


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)


router = APIRouter(
    prefix="/api/ads/brands/{brand_id}/campaigns/{campaign_id}/material-tasks",
    dependencies=[Depends(_guard)],
)


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["none", "manual", "workbench"] = "none"
    text: str | None = Field(default=None, max_length=24000)
    set_id: str | None = Field(default=None, max_length=200)
    version_id: str | None = Field(default=None, max_length=200)
    card_index: int | None = Field(default=None, ge=0, le=20)
    origin: str | None = Field(default=None, max_length=500)


class Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["existing", "external_image", "workbench_image", "copy"]
    instruction: str = Field(default="", max_length=8000)
    copy_fields: dict[str, str] = Field(default_factory=dict, max_length=20)
    prompt: Prompt = Field(default_factory=Prompt)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)
    review_id: str | None = Field(default=None, max_length=200)
    recommendation_id: str | None = Field(default=None, max_length=200)


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1, strict=True)


class Update(Operation):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    instruction: str | None = Field(default=None, max_length=8000)
    copy_fields: dict[str, str] | None = Field(default=None, max_length=20)
    prompt: Prompt | None = None
    reference_asset_ids: list[str] | None = Field(default=None, max_length=10)


class Candidates(Operation):
    asset_ids: list[str] = Field(min_length=1, max_length=10)
    prompt: Prompt = Field(default_factory=Prompt)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=10)


class Dispatch(Operation):
    content_hash: str = Field(min_length=64, max_length=64)


class Select(Dispatch):
    candidate_id: str = Field(min_length=1, max_length=200)


def _run(request, brand, campaign, function, *args):
    actor = web.require_actor(request)
    try:
        return function(web.conn, actor.org_id, brand, campaign, *args)
    except ValueError as exc:
        web.conn.rollback()
        raise web.ApiError(409, "material_unavailable", str(exc)) from None


@router.get("")
def listing(request: Request, brand_id: str, campaign_id: str):
    return _run(request, brand_id, campaign_id, service.workspace)


@router.post("")
def create(request: Request, brand_id: str, campaign_id: str, body: Create):
    return {
        "task": _run(
            request,
            brand_id,
            campaign_id,
            service.create,
            body.model_dump(exclude_unset=True),
            str(web.require_actor(request).user_id),
        )
    }


@router.get("/{task_id}")
def detail(
    request: Request, brand_id: str, campaign_id: str, task_id: str, revision: int | None = None
):
    return {"task": _run(request, brand_id, campaign_id, service.get, task_id, revision)}


@router.get("/{task_id}/prompt-options")
def options(request: Request, brand_id: str, campaign_id: str, task_id: str):
    return _run(request, brand_id, campaign_id, service.prompt_options, task_id)


@router.patch("/{task_id}")
def update(request: Request, brand_id: str, campaign_id: str, task_id: str, body: Update):
    return {
        "task": _run(
            request,
            brand_id,
            campaign_id,
            service.mutate,
            task_id,
            body.model_dump(exclude_unset=True),
            "update",
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/{task_id}/candidates")
def candidates(request: Request, brand_id: str, campaign_id: str, task_id: str, body: Candidates):
    return {
        "task": _run(
            request,
            brand_id,
            campaign_id,
            service.mutate,
            task_id,
            body.model_dump(exclude_unset=True),
            "candidates",
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/{task_id}/select")
def select(request: Request, brand_id: str, campaign_id: str, task_id: str, body: Select):
    return {
        "task": _run(
            request,
            brand_id,
            campaign_id,
            service.mutate,
            task_id,
            body.model_dump(),
            "select",
            str(web.require_actor(request).user_id),
        )
    }


@router.post("/{task_id}/dispatch")
def dispatch(request: Request, brand_id: str, campaign_id: str, task_id: str, body: Dispatch):
    return {
        "task": _run(
            request,
            brand_id,
            campaign_id,
            service.dispatch,
            task_id,
            body.model_dump(),
            str(web.require_actor(request).user_id),
        )
    }
