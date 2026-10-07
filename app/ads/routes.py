"""app/ads/routes.py — /api/ads/*. Private: only app/ads/__init__.py imports this (container
contract §1); it is only ever loaded via `register()`.

F03-I01: read-only — the list and the workspace payload.
F03-I03: `POST .../campaigns` (one sentence -> draft Campaign, `app/ads/brief.py::create_draft`)
and `PATCH .../campaigns/{id}` (plain field edits on a draft — never an `ads_action`).
Shape (container contract §7): every handler is `require_actor` -> `require_brand` -> one
repository/brief function -> wrap.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

import app.shared.web as web
from app import workbench
from app.ads import (
    adapters,
    assets,
    brief,
    budget,
    busy,
    change_control_data,
    change_control_launch,
    channels,
    closeout,
    experiment_routes,
    external_models,
    external_repository,
    handoff_assignment,
    judgment,
    learning,
    manual_settings,
    manual_settings_routes,
    materials_in_hand,
    month_budget,
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
    wizard_options,
)
from app.brand_intelligence import repository as bi_repo


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
            "strategy", "plan", "groups", "ads", "pack", "publish", "ingest", "close",
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
    # F42-I02：策略分頁「這期會用：…」讀的品牌手上素材（優惠＋支撐句、證據、素材能力）；
    # 既有 Campaign 不是這套規劃出來的，固定 None（形狀不變）。
    campaign["materials"] = (
        None if campaign.get("origin") == "imported" else materials_in_hand.read(
            web.conn, actor.org_id, brand_id,
            (campaign.get("context_json") or {}).get("product_ids") or [],
        )
    )
    # F48-I06: this period's coordinate menu and the capacity line (Contracts P, C).
    campaign.update(plan.served(web.conn, actor.org_id, brand_id, campaign))
    # F50 Contract J (R7 B4): a planner call still running for this campaign survives a reload.
    campaign["busy"] = busy.busy_state(web.conn, actor.org_id, brand_id, campaign["id"])
    # F51 Contract F: the closeout sentence the ledger stored, served (null before closeout).
    campaign["learning_sentence"] = learning.closed_sentence(campaign)
    return campaign


def _refused(exc: plan.PlannerRefused, failed_message: str) -> web.ApiError:
    """F50 Contract J (R7 B3): a planner refusal's 502 -- `code` stays the module's `…_failed`,
    `message` = its failed sentence + 「（{reason}）」, `details` names the rule."""
    return web.ApiError(
        502, str(exc), f"{failed_message}（{exc.reason}）",
        {"refusal": exc.code, "reason": exc.reason},
    )


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


@router.get("/brands/{brand_id}/new-campaign/options")
def get_new_campaign_options(request: Request, brand_id: str):
    """F30-I04 (Contract B): the products and objectives the new-campaign wizard can pick."""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return wizard_options.options(web.conn, actor.org_id, brand_id)


class CreateCampaignRequest(BaseModel):
    goal_text: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    constraints: dict = {}
    # F30-I04 (Contract D): the wizard's structured picks. Typed `Any` so a wrong type is
    # answered by the domain check with its own 400 code, after the tenant checks (F03-I20).
    product_ids: Any = None
    objective: Any = None
    budget: Any = None
    # F40-I04: values a new campaign may state up front, accepted on the picks path and the
    # sentence path alike (F43-I04: on a structured create, what is not stated comes from the
    # picked sell-way). `customer_group_ids` is the picks path's audience override.
    platform: Any = None
    audience_hint: Any = None
    cap: Any = None
    landing_url: Any = None
    customer_group_ids: Any = None


LANDING_URL_INVALID_MESSAGE = "落地頁請填完整的 http 或 https 網址，不可包含密碼。"
LANDING_URL_UNKNOWN_MESSAGE = "落地頁網址要是文字。"

_CREATE_CAMPAIGN_ERRORS = {
    "goal_text_required": (400, "請輸入這次投放的目標句子。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "end_before_start": (400, brief.END_BEFORE_START_MESSAGE),
    "objective_unavailable": (400, "這個目標尚未開放，請選其他目標。"),
    "objective_unknown": (400, "請選一個想要的結果。"),
    "budget_invalid": (400, "「這個活動最多花」請填大於 0 的數字。"),
    "products_required": (400, "請選一個商品。"),
    # F43-I04: only a finished sell-way of this brand is pickable.
    "product_unknown": (400, "這個賣法不能選：不屬於這個品牌、已下架，或商品還沒建完。"),
    "platform_unknown": (400, "這個平台不在通路清單裡。"),
    "audience_hint_unknown": (400, "受眾方向要是文字。"),
    "target_value_unknown": (400, "上限必須是大於 0 的數字。"),
    "landing_url_unknown": (400, LANDING_URL_UNKNOWN_MESSAGE),
    "landing_url_invalid": (400, LANDING_URL_INVALID_MESSAGE),
    "customer_group_unknown": (400, "受眾只能選這個賣法的顧客群。"),
    "campaign_busy": (409, busy.BUSY_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns")
def create_campaign(request: Request, brand_id: str, body: CreateCampaignRequest):
    """F03-I03：一句話 -> 一列 `status='draft'` 的 Campaign。永不 500：AI 解析失敗一樣寫得出
    可用的草稿，`app/ads/brief.py::create_draft` 內部處理，這裡沒有多餘的例外要接（除了輸入
    本身不合法）。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    # F30-I04: any structured pick present -> the wizard's create (Contract D); otherwise the
    # original one-sentence create. F40-I04: platform / audience_hint / cap / landing_url ride
    # along on both paths (`brief.create_draft` decides "structured" from the three picks).
    picks = {
        "product_ids": body.product_ids, "objective": body.objective, "budget": body.budget,
        "platform": body.platform, "audience_hint": body.audience_hint, "cap": body.cap,
        "landing_url": body.landing_url, "customer_group_ids": body.customer_group_ids,
    }
    try:
        # F50 Contract J: a second create while this brand's parse runs is refused (no campaign
        # exists yet, so the lock is the brand's).
        with busy.claim(web.conn, brand_id, "brief"):
            campaign = brief.create_draft(
                web.conn, actor.org_id, brand_id, goal_text=body.goal_text or "",
                start_date=body.start_date or "", end_date=body.end_date or "",
                constraints=body.constraints, actor=str(actor.user_id), picks=picks,
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
    audience_hint: str | None = None
    # F40-I04 (2b): the brief page edits the campaign-level landing URL (string or null).
    landing_url: str | None = None
    # F43-I18: the fold's audience -- this sell-way's group ids; `[]` = every group. `Any` so a
    # malformed value is `customer_group_unknown` (the create rule), not a pydantic 422.
    customer_group_ids: Any = None


RETIRED_GOAL_MESSAGE = "成功條件已改成一個上限（每筆成果成本），請在策略頁設定上限。"

_PATCH_CAMPAIGN_ERRORS = {
    external_models.IMPORTED_REASON: (409, external_models.IMPORTED_REASON),
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "name_unknown": (400, "名稱不能是空白。"),
    "objective_unknown": (400, "請從清單選一個目標。"),
    "objective_unavailable": (400, "這個目標尚未開放，請選其他目標。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "end_before_start": (400, brief.END_BEFORE_START_MESSAGE),
    "campaign_bound": (
        400,
        "這個 Campaign 已經跟平台配對過了，名稱／投放期間要改的話請走異動流程，"
        "才會留下異動紀錄。",
    ),
    "product_unknown": (400, "這個商品不屬於這個品牌。"),
    "audience_hint_unknown": (400, "受眾方向要是文字。"),
    "landing_url_unknown": (400, LANDING_URL_UNKNOWN_MESSAGE),
    "landing_url_invalid": (400, LANDING_URL_INVALID_MESSAGE),
    "customer_group_unknown": (400, "受眾只能選這個賣法的顧客群。"),
    # F48 Contract M: the plan's money was split for this period／sell-way／audience／platform.
    "plan_already_adopted": (
        409, "這個 Campaign 已經展開過投放結構，投放期間、商品、受眾和平台不能再改。",
    ),
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
    # F40-I04 (2b): the campaign-level landing URL lives in `context_json.landing_url` and is
    # written by `brief.set_landing_url` (the create path's owner of that key), after the
    # same tenant / imported-campaign refusals `update_campaign` applies to the other fields.
    edit_landing_url = "landing_url" in updates
    landing_url = updates.pop("landing_url", None)
    # F43-I18: `context_json.customer_group_ids` is `brief.set_customer_groups`'s (the create
    # path's rule), checked against the sell-way *after* this PATCH's `product_ids` is written;
    # a sell-way change without groups in the same PATCH resets them to the new sell-way's.
    # F48 Contract M: the key stays in `updates` so `update_campaign` refuses it after adoption.
    pick_groups = "customer_group_ids" in updates
    group_ids = updates.get("customer_group_ids")
    try:
        repository.update_campaign(web.conn, actor.org_id, brand_id, campaign_id, updates)
        if edit_landing_url:
            brief.set_landing_url(web.conn, actor.org_id, brand_id, campaign_id, landing_url)
        if pick_groups or "product_ids" in updates:
            brief.set_customer_groups(web.conn, actor.org_id, brand_id, campaign_id, group_ids,
                                      picked=pick_groups)
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
    "campaign_busy": (409, busy.BUSY_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy")
def generate_strategy(request: Request, brand_id: str, campaign_id: str):
    """F03-I05：組 context、打模型、套預算情境，整包寫進 `budget_basis_json`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        with busy.claim(web.conn, campaign_id, "strategy"):
            campaign = strategy.generate(
                web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
            )
    except plan.PlannerRefused as exc:
        raise _refused(exc, strategy.STRATEGY_FAILED_MESSAGE) from exc
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
    "total_below_one_per_day": (400, "總預算太少：每天不到 1 元"),
    # F48 decision 8: a new total after adoption re-splits only unbound ad sets.
    "campaign_bound": (409, "投放組已上架，改預算要走變更清單。"),
    "budget_exceeds_approval": (400, plan.BUDGET_EXCEEDS_APPROVAL_MESSAGE),
}


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/strategy/scenario")
def select_strategy_scenario(
    request: Request, brand_id: str, campaign_id: str, body: SelectScenarioRequest,
):
    """F03-I05：採用其中一個情境，或手打一個總額——寫 `budget_planned`。F28-I03：超過預算
    上限要帶 `confirm_over_cap: true`，否則 409 `over_cap_unconfirmed`，訊息寫出超出多少。
    F48 裁決 8：已展開（`ready`、投放組都還沒上架）時重新分配每個投放組的日預算，回應帶
    `resplit`；任何投放組已上架 → 409 `campaign_bound`。"""
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
            f"這個預算 NT${budget.whole(exc.total):,} 超出你設的預算上限 NT${exc.cap:,}，"
            f"多了 NT${exc.over:,}。確定要超出，請再確認一次。",
            {"total": exc.total, "cap": exc.cap, "over": exc.over},
        ) from exc
    except ValueError as exc:
        code = str(exc)
        status, message = _SELECT_SCENARIO_ERRORS.get(code, (400, code))
        raise web.ApiError(status, code, message) from exc
    # F48 decision 8: `resplit` names each ad set's daily before／after when an adopted plan's
    # total changed (`null` on a draft).
    resplit = campaign.pop("resplit", None)
    return {"campaign": _with_readiness(actor, brand_id, campaign), "resplit": resplit}


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
    "strategy_confirmation_required": (409, "請重新產生策略並確認每則廣告的安排。"),
    "strategy_changed": (409, "策略或依據已改變，請重新載入後確認。"),
    "strategy_infeasible": (409, "這份策略目前無法完整採用，請調整預算或安排。"),
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "plan_already_adopted": (400, "這個 Campaign 已經展開過投放結構，不能重新展開。"),
    "strategy_not_adopted": (400, "請先採用一個預算情境，才能展開投放結構。"),
    "dates_required": (400, brief.DATES_REQUIRED_MESSAGE),
    "budget_exceeds_approval": (400, plan.BUDGET_EXCEEDS_APPROVAL_MESSAGE),
    "delivery_plan_failed": (502, plan.PLAN_FAILED_MESSAGE),
    "campaign_busy": (409, busy.BUSY_MESSAGE),
}


class AdoptStrategyRequest(BaseModel):
    expected_revision: str | None = None
    operation_id: str | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/plan")
def adopt_strategy(request: Request, brand_id: str, campaign_id: str,
                   body: AdoptStrategyRequest | None = None):
    """F03-I06：把已採用的策略角色分配展開成投放組／廣告，草稿 -> `ready`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        with busy.claim(web.conn, campaign_id, "plan"):
            campaign = plan.adopt_strategy(
                web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id),
                expected_revision=body.expected_revision if body else None,
                operation_id=body.operation_id if body else None,
            )
    except plan.StrategyConflict as exc:
        status, message = _PLAN_ERRORS[str(exc)]
        raise web.ApiError(status, str(exc), message,
                           details={"reasons": exc.reasons}) from exc
    except plan.PlannerRefused as exc:
        raise _refused(exc, plan.PLAN_FAILED_MESSAGE) from exc
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
    "dates_reversed": (400, "結束日不能早於開始日。"),
    "date_invalid": (400, "日期格式不對，請用日曆選一天。"),
    "budget_exceeds_approval": (400, plan.BUDGET_EXCEEDS_APPROVAL_MESSAGE),
    "group_bound": (400, "這個投放組已經綁定平台，不能直接刪除。"),
    "last_group": (409, "至少要留一個投放組；想換掉請先新增再刪。"),
}


def _group_edit_error(exc: ValueError) -> web.ApiError:
    """`_GROUP_EDIT_ERRORS`, plus F50-I05's ad-set dates refusal naming the campaign window."""
    code = str(exc)
    if isinstance(exc, plan.GroupDatesOutside):
        return web.ApiError(400, code, exc.sentence)
    status, message = _GROUP_EDIT_ERRORS.get(code, (400, code))
    return web.ApiError(status, code, message)


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
        raise _group_edit_error(exc) from exc
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
        raise _group_edit_error(exc) from exc
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


def _ad_edit_error(exc: ValueError) -> web.ApiError:
    """`_AD_EDIT_ERRORS`, plus the two F48-I06 refusals that name what was refused."""
    code = str(exc)
    if isinstance(exc, plan.CoordinateUnavailable):
        return web.ApiError(400, code, f"這期不能用這個{exc.dimension_label}：{exc.reason}")
    if isinstance(exc, plan.NameForbidden):
        return web.ApiError(400, code, f"廣告名稱寫了「{exc.term}」，這是你標了不能講的話")
    status, message = _AD_EDIT_ERRORS.get(code, (400, code))
    return web.ApiError(status, code, message)


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
        raise _ad_edit_error(exc) from exc
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
        raise _ad_edit_error(exc) from exc
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
    # F48 Contract K: every ad already holds last period's creative -> no pack, nothing to do.
    return {"pack_id": pack_id, "nothing_to_prepare": pack_id is None}


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
    # F29 Contract I (`launch_settings_malformed` never reaches publish: only the settings PUT).
    "launch_settings_invalid": (409, "投放設定還有要改的地方（例如 UTM 格式），改好再核准。"),
    "no_groups_to_publish": (400, "這個活動還沒有投放組，先採用策略產出投放組再發布。"),
    # F30: a campaign and its ad sets alone are not a launch.
    "launch_no_ready_ads": (
        409, "還沒有任何一則廣告的素材就緒；至少一則素材確認後才能核准上架。"),
}


def _drop_deferred(conn, org_id: str, brand_id: str, campaign_id: str, enriched: dict) -> dict:
    """Project every approvable checklist field from the one hashed launch snapshot.

    Enrichment supplies view-time hints and post-build notes, not another approval revision.
    The snapshot also selects the ready batch, so deferred ads never appear in the checklist.
    """
    content = change_control_launch.snapshot(conn, org_id, brand_id, campaign_id)
    enriched.update({key: value for key, value in content.items()
                     if key not in {"groups", "manual_settings"}})
    groups = {group["id"]: group for group in enriched["groups"]}
    projected = []
    for node in content["groups"] or []:
        previous = groups.get(node["id"], {})
        ads = {ad["id"]: ad for ad in previous.get("ads") or []}
        group = {**previous, **node}
        group["ads"] = []
        for ad in node["ads"]:
            assignment = ad["strategy_assignment"]
            group["ads"].append({
                **ads.get(ad["id"], {}), **ad,
                "customer_group_id": assignment["customer_group_id"],
                **{f"{dimension}_key": value
                   for dimension, value in assignment["coordinates"].items()},
            })
        # The hint needs the actual plan role, which is retained in each ad's assignment.
        if node["ads"]:
            group["role"] = node["ads"][0]["strategy_assignment"]["role"]
        projected.append(group)
    enriched["groups"] = projected
    context = dict(enriched.get("context_json") or {})
    records = context.get("manual_delivery") or {}
    plan_keys = {field["key"] for field in manual_settings.FIELDS
                 if field["section"] != "上架紀錄"}
    context["manual_delivery"] = {
        record["id"]: {
            **(records.get(record["id"]) or {}),
            "values": {
                **{key: value for key, value in ((records.get(record["id"]) or {}).get(
                    "values") or {}).items() if key not in plan_keys},
                **record["values"],
            },
        } for record in content["manual_settings"] or []
    }
    # The snapshot has already resolved campaign landing-URL defaults into group values.
    context["landing_url"] = None
    enriched["context_json"] = context
    return content


@router.get("/brands/{brand_id}/campaigns/{campaign_id}/publish")
def get_publish(request: Request, brand_id: str, campaign_id: str, adapter: str = "manual"):
    """F03-I09：發布方式清單 + 選定那個 adapter 的 `describe`。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if repository.get_campaign(web.conn, actor.org_id, brand_id, campaign_id) is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    chosen = adapters.get_adapter(adapter)
    if chosen is None:
        raise web.ApiError(400, "adapter_unknown", "找不到這個發布方式。")
    content = None
    if adapter == "manual":
        from app.ads import launch_settings

        # Initialization can wait for a platform read. Read displayed content afterwards,
        # so edits completed during that wait are also in the checklist, not only its hash.
        launch_settings.initialize(web.conn, actor.org_id, brand_id, campaign_id)
    enriched = _enriched_campaign(web.conn, actor.org_id, brand_id, campaign_id)
    if enriched is None:
        raise web.ApiError(404, "campaign_unknown", CAMPAIGN_UNKNOWN_MESSAGE)
    if adapter == "manual":
        content = _drop_deferred(web.conn, actor.org_id, brand_id, campaign_id, enriched)
    description = chosen.describe(enriched)
    if content is not None:
        description["content_hash"] = change_control_data.digest(content)
        description["launch_settings"] = content["launch_settings"]
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
    except month_budget.MonthBudgetBlocked as exc:
        # F51 Contract C: the manual launch's month-budget refusal has its own code (it used to
        # answer the sentence as the code through the generic path below).
        raise web.ApiError(409, "month_budget_blocked", str(exc), {"reason": exc.code}) from exc
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
    if body.adapter == "manual":
        _drop_deferred(web.conn, actor.org_id, brand_id, campaign_id, enriched)
    return chosen.describe(enriched)


# -- F03-I11：成效——Meta 花費灌進來 + 模擬通路補天數，一個 ingest 端點兩邊派工 ------------------

_OUTCOME_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    # F49 Contract L (planning #19): a draft has no period on a platform to close.
    "campaign_not_launched": (409, "這個活動還沒上架，沒有可以結案的一期。"),
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


# -- F03-I12：結案——對自己的成功條件判 verdict，寫一條學習 -----------------------------------


class CloseCampaignRequest(BaseModel):
    reason: str | None = None
    skip_missing: bool = False


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
            reason=body.reason, skip_missing=body.skip_missing,
        )
    except closeout.CoverageMissing as exc:
        # F37 Contract Q: the envelope's `details` carries the days and whether the skip is open
        # (same shape as `over_cap_unconfirmed` above).
        payload = exc.payload
        message = (
            "這個活動還沒讀過平台資料，先重新讀取平台。" if payload["never_synced"]
            else f"有 {len(payload['missing_days'])} 天還沒讀到平台資料，先重新讀取平台。"
        )
        raise web.ApiError(409, "coverage_missing", message, payload) from exc
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
