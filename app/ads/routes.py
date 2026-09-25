"""app/ads/routes.py — /api/ads/*. Private: only app/ads/__init__.py imports this (container
contract §1); it is only ever loaded via `register()`.

F03-I01: read-only — the list and the workspace payload.
F03-I03: `POST .../campaigns` (one sentence -> draft Campaign, `app/ads/brief.py::create_draft`)
and `PATCH .../campaigns/{id}` (plain field edits on a draft — never an `ads_action`).
Shape (container contract §7): every handler is `require_actor` -> `require_brand` -> one
repository/brief function -> wrap.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

import app.shared.web as web
from app import workbench
from app.ads import (
    adapters,
    assets,
    brief,
    change_control_data,
    change_control_launch,
    channels,
    closeout,
    experiment_routes,
    external_models,
    external_repository,
    handoff_assignment,
    judgment,
    manual_settings_routes,
    outcome,
    plan,
    readiness,
    repository,
    settle_routes,
    simulation_mode,
    simulation_recovery,
    simulation_routes,
    strategy,
    triage_routes,
)
from app.ads.adapters import simulated
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings


def _legacy_campaign_guard(request: Request):
    """Protect existing mutation routes, including the mounted legacy routers."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    params = request.path_params
    brand_id = params.get("brand_id")
    if not brand_id:
        return
    campaign_id = params.get("campaign_id")
    # F13 source/material routes have their own capability contracts.
    if campaign_id:
        suffix = request.url.path.split("/campaigns/" + campaign_id, 1)[-1]
        if not suffix and request.method == "PATCH":
            return  # update_campaign validates the imported goal-only allowlist
        if suffix and suffix.split("/")[1] not in {
            "strategy", "plan", "groups", "ads", "pack", "publish", "bind", "ingest", "close",
            "comparison", "simulation", "simulate", "simulation-recovery",
        }:
            return
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)
    if not campaign_id:
        row = None
        if params.get("group_id"):
            row = repository.get_group(web.conn, actor.org_id, brand_id, params["group_id"])
        elif params.get("ad_id"):
            row = repository.get_ad(web.conn, actor.org_id, brand_id, params["ad_id"])
        if row:
            campaign_id = row["campaign_id"]
    if campaign_id:
        campaign = repository.get_campaign(web.conn, actor.org_id, brand_id, campaign_id)
        if campaign and campaign.get("origin") == "imported":
            raise web.ApiError(
                409, "imported_operation_unavailable", external_models.IMPORTED_REASON,
            )


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_legacy_campaign_guard)])
router.include_router(manual_settings_routes.router)
router.include_router(simulation_routes.router)
router.include_router(experiment_routes.router)
router.include_router(triage_routes.router)
router.include_router(settle_routes.router)

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"
GROUP_UNKNOWN_MESSAGE = "找不到這個投放組。"
AD_UNKNOWN_MESSAGE = "找不到這支廣告。"


def _conversion_labels(brand_id: str) -> dict:
    """F05-I12：每個 Campaign payload 跟著出去的一份對照表——畫面上的「購買」／「名單」等
    詞從這個品牌自己的 `conversion_goal` 來，不寫死（`app.ads.judgment.conversion_labels`）。"""
    brand = bi_repo.get_brand(web.conn, brand_id)
    return judgment.conversion_labels(brand.get("conversion_goal") if brand else None)


def _with_readiness(actor, brand_id: str, campaign: dict | None) -> dict | None:
    """每一條回 Campaign 的路由都跟 GET 回同一個形狀（`campaign_detail` + `asset_readiness`
    + `labels`）。少一個欄位，瀏覽器就是白畫面（F04-I24，演練四）。"""
    if campaign is None:
        return None
    campaign["asset_readiness"] = assets.readiness_summary(
        assets.readiness(web.conn, actor.org_id, brand_id, campaign["id"]),
        assets.pack_id(web.conn, actor.org_id, brand_id, campaign["id"]),
    )
    campaign["labels"] = _conversion_labels(brand_id)
    campaign["simulation_mode"] = simulation_mode.enabled(web.conn, actor.org_id, brand_id)
    return campaign


@router.get("/brands/{brand_id}/readiness")
def get_readiness(request: Request, brand_id: str):
    """F05-I04：可投放檢查表——精靈最後一頁與投放中心「建立 Campaign」入口讀同一份。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {"readiness": readiness.launch_readiness(web.conn, actor.org_id, brand_id)}


@router.get("/brands/{brand_id}/channels")
def get_channels(request: Request, brand_id: str):
    """F05-I05：通路清單——畫面不准自己寫死平台名字，一律讀這支。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {"channels": channels.list_channels(web.conn, actor.org_id, brand_id)}


@router.get("/brands/{brand_id}/campaigns")
def list_campaigns(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaigns = repository.list_campaigns(web.conn, actor.org_id, brand_id)
    labels = _conversion_labels(brand_id)
    for c in campaigns:
        c["labels"] = labels
    return {"campaigns": campaigns}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}")
def get_campaign(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaign = repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)
    if campaign is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    # F03-I08：素材 tab 跟發布畫面共用同一組 ready_count/total（§0）。
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


# F03-I20：租戶界線先於欄位驗證（既有慣例，同 app/workbench/routes.py）：這個檔案裡每一個
# request model 的每個欄位都要有預設值，真正的必填檢查留給下面的 handler／domain function 做。
# 一個沒有預設值的欄位會讓 FastAPI 在 `require_actor`／`require_brand` 跑之前就先回 422，
# 對沒登入的呼叫者洩漏「這個路由存在、body 長這樣」，也讓租戶界線的掃描測試測不到這條路由。


class CreateCampaignRequest(BaseModel):
    goal_text: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    constraints: dict = {}


_CREATE_CAMPAIGN_ERRORS = {
    "goal_text_required": (400, "請輸入這次投放的目標句子。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "end_before_start": (400, brief.END_BEFORE_START_MESSAGE),
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
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


class PatchCampaignRequest(BaseModel):
    # `extra="allow"` only so the handler can answer an unknown key AFTER the tenant checks:
    # a retired goal key gets its own 400, any other unknown key the usual 422 (F28-I01).
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    goal_text: str | None = None
    name: str | None = None
    objective: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    constraints_json: dict | None = None
    product_ids: list[str] | None = None


RETIRED_GOAL_MESSAGE = "成功條件已改成一個上限（每筆成果成本），請在策略頁設定上限。"

_PATCH_CAMPAIGN_ERRORS = {
    external_models.IMPORTED_REASON: (409, external_models.IMPORTED_REASON),
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "name_unknown": (400, "名稱不能是空白。"),
    "objective_unknown": (400, "目標不能是空白。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "end_before_start": (400, brief.END_BEFORE_START_MESSAGE),
    "campaign_bound": (
        400,
        "這個 Campaign 已經跟平台配對過了，名稱／投放期間要改的話請走異動流程，"
        "才會留下異動紀錄。",
    ),
    "product_unknown": (400, "這個商品不屬於這個品牌。"),
}


@router.patch("/brands/{brand_id}/campaigns/{campaign_id}")
def patch_campaign(request: Request, brand_id: str, campaign_id: str, body: PatchCampaignRequest):
    """F03-I03：草稿欄位的一般編輯——不是 `ads_action`（還沒有任何東西綁定到平台，§0）。
    只送使用者真的填過的欄位（`exclude_unset`），沒填的欄位維持原樣（使用者送 `null` 也算
    「填過」）。F28-I01：舊的成功條件欄位（`success_` 開頭）已退役——上限只在策略頁的
    `PUT .../target` 設定，送來一律 400，不悄悄忽略。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    unknown = sorted(body.model_extra or {})
    if any(key.startswith("success_") for key in unknown):
        raise web.ApiError(400, "goal_fields_retired", RETIRED_GOAL_MESSAGE)
    if unknown:
        raise web.ApiError(422, "field_unknown", "不認得的欄位：" + "、".join(unknown))
    updates = body.model_dump(exclude_unset=True)
    try:
        repository.update_campaign(web.conn, actor.org_id, brand_id, campaign_id, updates)
    except ValueError as exc:
        code = str(exc)
        status, message = _PATCH_CAMPAIGN_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    campaign = repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


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
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


class SelectScenarioRequest(BaseModel):
    scenario_key: str = ""
    custom_total: float | None = None
    # F28-I03: required to save a total above the campaign's budget cap.
    confirm_over_cap: bool = False


_SELECT_SCENARIO_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "strategy_not_generated": (400, "請先產生策略，才能選預算情境。"),
    "scenario_unknown": (400, "找不到這個預算情境。"),
    "scenario_amount_unknown": (
        400, "這個情境還算不出金額：請先補上商品的售價與成本，或自訂預算。",
    ),
    "custom_total_invalid": (400, "手打的總額必須大於 0。"),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy/scenario")
def select_strategy_scenario(
    request: Request, brand_id: str, campaign_id: str, body: SelectScenarioRequest,
):
    """F03-I05：採用其中一個情境，或手打一個總額——寫 `budget_planned`。F28-I03：超過預算
    上限要帶 `confirm_over_cap: true`，否則 409 `over_cap_unconfirmed`，訊息寫出超出多少。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = strategy.select_scenario(
            web.conn, actor.org_id, brand_id, campaign_id,
            scenario_key=body.scenario_key, custom_total=body.custom_total,
            confirm_over_cap=body.confirm_over_cap, actor=str(actor.user_id),
        )
    except strategy.OverCapUnconfirmed as exc:
        raise web.ApiError(
            409, "over_cap_unconfirmed",
            f"這個預算 NT${round(exc.total):,} 超出你設的預算上限 NT${exc.cap:,}，"
            f"多了 NT${exc.over:,}。確定要超出，請再確認一次。",
            {"total": exc.total, "cap": exc.cap, "over": exc.over},
        ) from exc
    except ValueError as exc:
        code = str(exc)
        status, message = _SELECT_SCENARIO_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


class BudgetCapRequest(BaseModel):
    # `object`, not `int`: a string or a fraction must reach the handler (after the tenant
    # checks) and be refused there, never silently coerced by the model.
    budget_cap: object = None


_BUDGET_CAP_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    external_models.IMPORTED_REASON: (409, external_models.IMPORTED_REASON),
    "budget_cap_invalid": (422, "預算上限要是大於 0 的整數；要取消上限請送 null。"),
}


@router.put("/brands/{brand_id}/campaigns/{campaign_id}/strategy/budget-cap")
def put_budget_cap(request: Request, brand_id: str, campaign_id: str, body: BudgetCapRequest):
    """F28-I03（使用者裁決 2026-09-25）：精靈之後、任何狀態都能改預算上限。只寫
    `constraints_json.budget`——不寫平台、不動已存的情境與 `budget_planned`、不讓交接過期。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if "budget_cap" not in body.model_fields_set:  # a missing key is not "clear the cap"
        status, message = _BUDGET_CAP_ERRORS["budget_cap_invalid"]
        raise web.ApiError(status, "budget_cap_invalid", message)
    try:
        campaign = strategy.set_budget_cap(
            web.conn, actor.org_id, brand_id, campaign_id, budget_cap=body.budget_cap,
            actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _BUDGET_CAP_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


class AllocationItem(BaseModel):
    role: str = ""
    pct: float = 0.0


class SetAllocationRequest(BaseModel):
    allocation: list[AllocationItem] = []


_ALLOCATION_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "strategy_not_generated": (400, "請先產生策略。"),
    "plan_already_adopted": (
        400,
        "投放結構已經建立，預算分配請到投放結構分頁改每個投放組的日預算。",
    ),
    "allocation_invalid": (400, "三個角色的百分比要加起來等於 100，而且不能是負數。"),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy/allocation")
def set_strategy_allocation(
    request: Request, brand_id: str, campaign_id: str, body: SetAllocationRequest,
):
    """F04-I13：採用之前調整三個角色的百分比，金額由 `strategy.set_allocation` 重算。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = strategy.set_allocation(
            web.conn, actor.org_id, brand_id, campaign_id,
            allocation=[item.model_dump() for item in body.allocation], actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _ALLOCATION_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


# -- F03-I06: 採用策略 -> 投放組／廣告，以及後續編輯 ------------------------------------------

_PLAN_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "plan_already_adopted": (400, "這個 Campaign 已經展開過投放結構，不能重新展開。"),
    "strategy_not_adopted": (400, "請先採用一個預算情境，才能展開投放結構。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "budget_exceeds_approval": (400, plan.BUDGET_EXCEEDS_APPROVAL_MESSAGE),
    "delivery_plan_failed": (502, plan.PLAN_FAILED_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/plan")
def adopt_strategy(request: Request, brand_id: str, campaign_id: str):
    """F03-I06：把已採用的策略角色分配展開成投放組／廣告，草稿 -> `ready`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        campaign = plan.adopt_strategy(
            web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _PLAN_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


_GROUP_EDIT_ERRORS = {
    "group_unknown": (404, GROUP_UNKNOWN_MESSAGE),
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "name_unknown": (400, "名稱不能是空白。"),
    "role_unknown": (400, "角色只能是新客／再行銷／探索。"),
    "daily_budget_invalid": (400, "日預算必須大於 0。"),
    "budget_exceeds_approval": (400, plan.BUDGET_EXCEEDS_APPROVAL_MESSAGE),
    "group_bound": (400, "這個投放組已經綁定平台，不能直接刪除。"),
}


class CreateGroupRequest(BaseModel):
    name: str = ""
    role: str = ""
    daily_budget: float | None = None
    start_date: str | None = None
    end_date: str | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/groups")
def create_group(
    request: Request, brand_id: str, campaign_id: str, body: CreateGroupRequest,
):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if body.daily_budget is None:
        code = "daily_budget_invalid"
        status, message = _GROUP_EDIT_ERRORS[code]
        raise web.ApiError(status, code, message)
    try:
        group = plan.create_group(
            web.conn, actor.org_id, brand_id, campaign_id, name=body.name, role=body.role,
            daily_budget=body.daily_budget, start_date=body.start_date, end_date=body.end_date,
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _GROUP_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"group": group}


class PatchGroupRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    daily_budget: float | None = None
    start_date: str | None = None
    end_date: str | None = None


@router.patch("/brands/{brand_id}/groups/{group_id}")
def patch_group(request: Request, brand_id: str, group_id: str, body: PatchGroupRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    updates = body.model_dump(exclude_unset=True)
    try:
        group = plan.update_group(
            web.conn, actor.org_id, brand_id, group_id, updates, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _GROUP_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"group": group}


@router.delete("/brands/{brand_id}/groups/{group_id}")
def delete_group(request: Request, brand_id: str, group_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        plan.delete_group(web.conn, actor.org_id, brand_id, group_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _GROUP_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"ok": True}


_AD_EDIT_ERRORS = {
    "ad_unknown": (404, AD_UNKNOWN_MESSAGE),
    "group_unknown": (404, GROUP_UNKNOWN_MESSAGE),
    "name_unknown": (400, "名稱不能是空白。"),
    "coordinates_incomplete": (400, "七個座標維度都要填，不能留空。"),
    "ad_bound": (400, "這支廣告已經綁定平台，不能直接刪除。"),
    "ready_invalid": (400, "請指定要勾選或取消。"),
}


class CreateAdRequest(BaseModel):
    group_id: str = ""
    name: str = ""
    coordinates: dict = {}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/ads")
def create_ad(request: Request, brand_id: str, campaign_id: str, body: CreateAdRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        ad = plan.create_ad(
            web.conn, actor.org_id, brand_id, campaign_id, body.group_id, name=body.name,
            coordinates=body.coordinates,
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _AD_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"ad": ad}


class PatchAdRequest(BaseModel):
    name: str | None = None
    coordinates: dict | None = None


@router.patch("/brands/{brand_id}/ads/{ad_id}")
def patch_ad(request: Request, brand_id: str, ad_id: str, body: PatchAdRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    updates = body.model_dump(exclude_unset=True)
    try:
        ad = plan.update_ad(
            web.conn, actor.org_id, brand_id, ad_id, updates, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _AD_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"ad": ad}


@router.delete("/brands/{brand_id}/ads/{ad_id}")
def delete_ad(request: Request, brand_id: str, ad_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        plan.delete_ad(web.conn, actor.org_id, brand_id, ad_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _AD_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"ok": True}


# -- F03-I08：素材就緒 -- 交棒工作檯任務包／讀就緒狀態／手動勾「素材已就位」 -------------------

_PACK_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "pack_already_exists": (400, assets.PACK_ALREADY_EXISTS_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/pack")
def dispatch_pack(request: Request, brand_id: str, campaign_id: str):
    """F03-I08：把這個 Campaign 底下所有廣告一次交棒成一個素材工作檯任務包。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        pack_id = assets.dispatch_pack(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _PACK_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"pack_id": pack_id}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/assets")
def get_assets(request: Request, brand_id: str, campaign_id: str):
    """F03-I08：每支廣告的素材就緒狀態，加上 `ready_count`／`total` 小計。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    rows = assets.readiness(web.conn, actor.org_id, brand_id, campaign_id)
    pack_id = assets.pack_id(web.conn, actor.org_id, brand_id, campaign_id)
    return {"assets": rows, **assets.readiness_summary(rows, pack_id)}


class AssetReadyRequest(BaseModel):
    ready: bool | None = None


@router.post("/brands/{brand_id}/ads/{ad_id}/asset-ready")
def set_asset_ready(request: Request, brand_id: str, ad_id: str, body: AssetReadyRequest):
    """F03-I08：手動勾／取消勾「素材已就位」。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if body.ready is None:
        code = "ready_invalid"
        status, message = _AD_EDIT_ERRORS[code]
        raise web.ApiError(status, code, message)
    try:
        ad = assets.mark_ready(
            web.conn, actor.org_id, brand_id, ad_id, actor=str(actor.user_id), ready=body.ready,
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _AD_EDIT_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"ad": ad}


# -- F03-I09：手動發布／配對 -- 一個 describe 路徑，GET／POST 都用它（修正 3：POST 以前用
# 沒有工作檯內容的原始 campaign_detail 建清單，跟 GET 看到的不是同一份） -----------------------

def _enriched_campaign(conn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    """`campaign_detail` 再疊工作檯已採用的文案／圖片提示詞（`copy_text`／`image_prompt_text`，
    只有工作檯真的產出過才有值，否則是 `None`）——`describe()` 的清單要印的是使用者已經選定
    的內容，不是叫他自己去工作檯找。只透過工作檯既有的公開入口讀（`pack_for_source`／
    `briefs_for_source`／`adopted_output`），不碰 `workbench_*` 表（跟 `app/ads/assets.py` 同一
    條規矩）。"""
    detail = repository.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        return None
    source_ref = {"ads_campaign_id": campaign_id}
    pack = workbench.pack_for_source(conn, org_id, brand_id, assets.PACK_SOURCE_KIND, source_ref)
    briefs_by_ad_id: dict = {}
    if pack is not None:
        for item in workbench.briefs_for_source(
            conn, org_id, brand_id, assets.PACK_SOURCE_KIND, source_ref,
        ):
            ad_id = (item.get("source_ref") or {}).get("ads_ad_id")
            if ad_id:
                briefs_by_ad_id[ad_id] = item

    for group in detail["groups"]:
        for ad in group["ads"]:
            ad["material_assignment"] = handoff_assignment.material_snapshot(
                conn, org_id, brand_id, campaign_id, ad
            )
            ad["copy_text"] = None
            ad["image_prompt_text"] = None
            ad_brief = briefs_by_ad_id.get(ad["id"])
            if ad_brief is None:
                continue
            copy_output = workbench.adopted_output(conn, org_id, brand_id, ad_brief["id"], "copy")
            ad["copy_text"] = _adopted_copy_text(copy_output)
            image_output = workbench.adopted_output(
                conn, org_id, brand_id, ad_brief["id"], "image_prompt",
            )
            ad["image_prompt_text"] = _adopted_image_prompt_text(image_output)
    return detail


def _adopted_copy_text(copy_output: dict | None) -> str | None:
    if copy_output is None:
        return None
    sets = (copy_output.get("body_json") or {}).get("sets")
    if isinstance(sets, list) and sets and isinstance(sets[0], dict):
        return sets[0].get("body")
    return None


def _adopted_image_prompt_text(image_output: dict | None) -> str | None:
    """§5.8：已採用的圖片提示詞列印出來的字——只讀 `text`（品牌視覺規範／風格規範已經
    接在尾巴），不是舊的 `rendered`（F07-I10）。"""
    if image_output is None or not image_output.get("is_adopted"):
        return None
    text = (image_output.get("body_json") or {}).get("text")
    return text if isinstance(text, str) and text else None


_PUBLISH_ERRORS = {
    simulation_mode.MESSAGE: (409, simulation_mode.MESSAGE),
    "simulation_isolation_required": (409, "請到成效頁啟用隔離模擬回收；只限測試品牌。"),
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "adapter_unknown": (400, "找不到這個發布方式。"),
    "no_groups_to_publish": (400, "這個活動還沒有投放組，先採用策略產出投放組再發布。"),
}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/publish")
def get_publish(request: Request, brand_id: str, campaign_id: str, adapter: str = "manual"):
    """F03-I09：發布方式清單 + 選定那個 adapter 的 `describe`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    enriched = _enriched_campaign(web.conn, actor.org_id, brand_id, campaign_id)
    if enriched is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    chosen = adapters.get_adapter(adapter)
    if chosen is None:
        raise web.ApiError(400, "adapter_unknown", "找不到這個發布方式。")
    description = chosen.describe(enriched)
    if adapter == "manual":
        description["content_hash"] = change_control_data.digest(
            change_control_launch.snapshot(web.conn, actor.org_id, brand_id, campaign_id))
    return {"adapters": adapters.ADAPTERS, "adapter": adapter, "describe": description}


class PublishRequest(BaseModel):
    adapter: str = "manual"
    operation_id: str | None = None
    content_hash: str | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/publish")
def publish_campaign(request: Request, brand_id: str, campaign_id: str, body: PublishRequest):
    """F03-I09：決策 1「一般路徑顯示自動發布未接上，進階選單才是手動發布」——這裡只管落地，
    哪個 adapter 由呼叫端選。回傳跟 GET 同一份 `describe`（修正 3：同一條 enrichment 路徑）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    chosen = adapters.get_adapter(body.adapter)
    if chosen is None:
        raise web.ApiError(400, "adapter_unknown", "找不到這個發布方式。")
    try:
        if body.adapter == "simulated":
            reason = simulation_recovery.eligibility(web.conn, actor.org_id, brand_id)
            if reason:
                raise web.ApiError(409, "simulation_unavailable", reason)
            if not simulation_mode.enabled(web.conn, actor.org_id, brand_id):
                raise ValueError("simulation_isolation_required")
        if body.adapter == "manual":
            chosen.publish(web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
                           operation_id=body.operation_id, content_hash=body.content_hash)
        else:
            chosen.publish(web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id))
    except ValueError as exc:
        code = str(exc)
        # 唯一沒進 `_PUBLISH_ERRORS` 的例外碼是 `auto_meta` adapter 保留位置的那個（F03-I09），
        # 這裡不重複那個字面字串（§0：平台名字只准住在 channels.py／adapters/**）——直接問
        # adapter 自己保留的訊息。
        fallback = (409, code) if body.adapter == "manual" else (
            400, adapters.AUTO_META_NOT_CONNECTED_MESSAGE)
        status, message = _PUBLISH_ERRORS.get(code, fallback)
        raise web.ApiError(status, code, message) from exc
    enriched = _enriched_campaign(web.conn, actor.org_id, brand_id, campaign_id)
    if enriched is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    return chosen.describe(enriched)


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/bind")
def bind_campaign(request: Request, brand_id: str, campaign_id: str):
    """F03-I09：手動路徑的「配對」——精準名稱比對，逐節點由上往下（`app/ads/adapters/
    manual.py::bind`）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    manual_adapter = adapters.get_adapter("manual")
    assert manual_adapter is not None  # 這是固定登記過的 key，永遠找得到
    try:
        result = manual_adapter.bind(
            web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _PUBLISH_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    result["campaign"] = _with_readiness(actor, brand_id, result["campaign"])
    return result


# -- F03-I11：成效——Meta 花費灌進來 + 模擬通路補天數，一個 ingest 端點兩邊派工 ------------------

_OUTCOME_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/performance")
def get_performance(request: Request, brand_id: str, campaign_id: str):
    """F03-I11：成效分頁的整包 payload——`app/ads/outcome.py::summary()`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaign = repository.get_campaign(web.conn, actor.org_id, brand_id, campaign_id)
    if campaign and campaign.get("origin") == "imported":
        return {"origin": "imported", "external_view": external_repository.external_view(
            web.conn, actor.org_id, brand_id, campaign_id)}
    try:
        result = outcome.summary(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _OUTCOME_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return result


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/ingest")
def ingest_outcome(request: Request, brand_id: str, campaign_id: str):
    """F03-I11：一個端點，依這個 Campaign 是怎麼發布的派工——模擬通路（`external_id` 帶
    `sim_` 前綴，`app/ads/adapters/simulated.py::_fake_external_id`）補到今天為止缺的天數；
    其餘（含手動配對進來的 Meta 綁定）拉既有每日拉取已經存好的 `meta_entity_spend`，這裡
    不多打一次 Meta（6 小時排程跟更新鈕是 F04）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    campaign = repository.get_campaign(web.conn, actor.org_id, brand_id, campaign_id)
    if campaign is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    try:
        external_id = campaign.get("external_id") or ""
        if external_id.startswith("sim_"):
            simulated.generate_outcomes(web.conn, actor.org_id, brand_id, campaign_id)
        else:
            today = coresettings.today_for_org(web.conn, org_id=actor.org_id)
            start = campaign.get("start_date") or today
            outcome.ingest_meta(
                web.conn, actor.org_id, brand_id, campaign_id, start=start,
                end=today + timedelta(days=1),
            )
        result = outcome.summary(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _OUTCOME_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return result


# -- F03-I12：結案——對自己的成功條件判 verdict，寫一條學習 -----------------------------------


class CloseCampaignRequest(BaseModel):
    reason: str | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/close")
def close_campaign(request: Request, brand_id: str, campaign_id: str,
                    body: CloseCampaignRequest):
    """手動結案——`app/ads/jobs.py` 的排程只監控已結束的活動、從不自動結案（F16-I01：
    移除「end+7d 自動結案」的過時說法），結案永遠得經這裡或人工觸發，都是走
    `app/ads/closeout.py::close()`，寫一樣的 verdict 跟學習。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        closeout.close(
            web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
            reason=body.reason,
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _OUTCOME_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    # 回傳跟 GET 一樣的形狀（campaign_detail + asset_readiness）——`closeout.close` 可以繼續回
    # 陽春的 ads_campaign 列，前端的 CampaignDetail 型別要的是這一份（§0 re-cut correction 1）。
    campaign = repository.campaign_detail(web.conn, actor.org_id, brand_id, campaign_id)
    return {"campaign": _with_readiness(actor, brand_id, campaign)}


# -- F16-I04：每個 Campaign（自建或既有）都要能算出一個目標成本 -----------------------------


class TargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    result_kind: str | None = None
    basis: str | None = None
    value: float | None = None
    product_id: str | None = None
    price: float | None = None
    variable_cost: float | None = None
    # F03-I20：這個檔案裡每個 request model 的欄位都要有預設值，租戶界線才會先於欄位驗證
    # 跑（見上方檔頭那段說明）——`None`（沒填）一律被 `repository.save_campaign_target` 當成
    # 「版本號不對」處理（`type(...) is not int`），不是另開一種缺欄錯誤。`ge=0, strict=True`
    # 比照 `app/ads/month_budget_routes.py:48` 的 `expected_revision`：一份提供時不接受字串
    # 強轉或負數，只是這裡多留了 `None` 當預設值。
    expected_revision: int | None = Field(default=None, ge=0, strict=True)


_TARGET_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "target_conflict": (409, "目標設定已被更新，請重新載入後再試一次。"),
    "target_basis_unknown": (400, "basis 只能是 own／break_even。"),
    "target_value_unknown": (400, "上限必須是大於 0 的數字。"),
    "product_unknown": (400, "這個商品不屬於這個品牌。"),
    "product_economics_unknown": (400, "這個商品還沒有售價可以核對，請先補售價。"),
    # F19-I06: result_kind is a trust-boundary value -- `app/ads/result_kinds.py::LABELS` is the
    # one vocabulary; anything outside it is rejected, never silently stored.
    "result_kind_unknown": (400, "result_kind 不在可選清單裡。"),
}


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/target")
def get_campaign_target(request: Request, brand_id: str, campaign_id: str):
    """F16-I04：這個 Campaign 目前能算出的目標成本——`app/ads/targets.py::resolve()` 的
    純計算結果，外加這個子資源自己的存檔狀態（`result_kind`／商品選擇／own 覆寫／
    `target_revision`）。不掛 `_legacy_campaign_guard`（suffix 不在它的白名單裡，見檔頭
    guard 的註解），自己做租戶界線——既有活動也要能讀這條路由，不像其餘既有 mutation 路由
    整條擋掉。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        target = repository.get_campaign_target(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        code = str(exc)
        status, message = _TARGET_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"target": target}


@router.put("/brands/{brand_id}/campaigns/{campaign_id}/target")
def put_campaign_target(request: Request, brand_id: str, campaign_id: str, body: TargetRequest):
    """F16-I04：`result_kind`／商品選擇／own 覆寫值／樂觀版本號，比照
    `app/ads/month_budget_routes.py::confirm_budget` 的 `expected_revision` 寫法。
    `price`／`variable_cost` 一律轉交 `app.brand_intelligence.repository.save_product_economics`
    這個既有公開寫入路徑，這裡不直接碰 `product_economics` 表。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        target = repository.save_campaign_target(
            web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
            **body.model_dump(),
        )
    except ValueError as exc:
        code = str(exc)
        status, message = _TARGET_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    return {"target": target}
