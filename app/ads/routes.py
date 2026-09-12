"""app/ads/routes.py — /api/ads/*. Private: only app/ads/__init__.py imports this (container
contract §1); it is only ever loaded via `register()`.

F03-I01: read-only — the list and the workspace payload.
F03-I03: `POST .../campaigns` (one sentence -> draft Campaign, `app/ads/brief.py::create_draft`)
and `PATCH .../campaigns/{id}` (plain field edits on a draft — never an `ads_action`).
Shape (container contract §7): every handler is `require_actor` -> `require_brand` -> one
repository/brief function -> wrap.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.ads import brief, repository, strategy

router = APIRouter(prefix="/api/ads")

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"


@router.get("/brands/{brand_id}/campaigns")
def list_campaigns(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaigns = repository.list_campaigns(web.conn, actor.org_id, brand_id)
    return {"campaigns": campaigns}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}")
def get_campaign(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaign = repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)
    if campaign is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    return {"campaign": campaign}


class CreateCampaignRequest(BaseModel):
    goal_text: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    constraints: dict = {}


_CREATE_CAMPAIGN_ERRORS = {
    "goal_text_required": (400, "請輸入這次投放的目標句子。"),
    brief.DATES_REQUIRED_MESSAGE: (400, brief.DATES_REQUIRED_MESSAGE),
    brief.END_BEFORE_START_MESSAGE: (400, brief.END_BEFORE_START_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns")
def create_campaign(request: Request, brand_id: str, body: CreateCampaignRequest):
    """F03-I03：一句話 -> 一列 `status='draft'` 的 Campaign。永不 500：AI 解析失敗一樣寫得出
    可用的草稿，`app/ads/brief.py::create_draft` 內部處理，這裡沒有多餘的例外要接（除了輸入
    本身不合法）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = brief.create_draft(
            web.conn, actor.org_id, brand_id, goal_text=body.goal_text or "",
            start_date=body.start_date or "", end_date=body.end_date or "",
            constraints=body.constraints, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _CREATE_CAMPAIGN_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": campaign}


class PatchCampaignRequest(BaseModel):
    name: str | None = None
    objective: str | None = None
    success_metric: str | None = None
    success_target: float | None = None
    success_basis: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    constraints_json: dict | None = None
    product_ids: list[str] | None = None


_PATCH_CAMPAIGN_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "name_unknown": (400, "名稱不能是空白。"),
    "objective_unknown": (400, "目標不能是空白。"),
    "success_metric_unknown": (400, "成功指標只能是 cpa／roas／purchases。"),
    "success_target_unknown": (400, "成功條件的目標值必須是數字。"),
}


@router.patch("/brands/{brand_id}/campaigns/{campaign_id}")
def patch_campaign(request: Request, brand_id: str, campaign_id: str, body: PatchCampaignRequest):
    """F03-I03：草稿欄位的一般編輯——不是 `ads_action`（還沒有任何東西綁定到平台，§0）。
    只送使用者真的填過的欄位（`exclude_unset`），沒填的欄位維持原樣，`success_target`／
    `success_basis` 因此可以被明確清成 `null`（使用者送 `null` 也算「填過」）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    updates = body.model_dump(exclude_unset=True)
    try:
        repository.update_campaign(web.conn, actor.org_id, brand_id, campaign_id, updates)
    except ValueError as exc:
        code = str(exc)
        status, message = _PATCH_CAMPAIGN_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)}


_STRATEGY_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "strategy_failed": (502, strategy.STRATEGY_FAILED_MESSAGE),
    "strategy_already_adopted": (400, "這個 Campaign 已經採用過策略，不能重新產生。"),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy")
def generate_strategy(request: Request, brand_id: str, campaign_id: str):
    """F03-I05：組 context、打模型、套預算情境，整包寫進 `budget_basis_json`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = strategy.generate(
            web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _STRATEGY_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": campaign}


class SelectScenarioRequest(BaseModel):
    scenario_key: str
    custom_total: float | None = None


_SELECT_SCENARIO_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "strategy_not_generated": (400, "請先產生策略，才能選預算情境。"),
    "scenario_unknown": (400, "找不到這個預算情境。"),
    "custom_total_invalid": (400, "手打的總額必須大於 0。"),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy/scenario")
def select_strategy_scenario(
    request: Request, brand_id: str, campaign_id: str, body: SelectScenarioRequest,
):
    """F03-I05：採用最低／推薦／積極其中一個情境，或手打一個總額——寫 `budget_planned`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = strategy.select_scenario(
            web.conn, actor.org_id, brand_id, campaign_id,
            scenario_key=body.scenario_key, custom_total=body.custom_total,
            actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _SELECT_SCENARIO_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": campaign}
