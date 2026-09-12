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
from app import workbench
from app.ads import adapters, assets, brief, plan, repository, strategy

router = APIRouter(prefix="/api/ads")

CAMPAIGN_UNKNOWN_MESSAGE = "找不到這個 Campaign。"
GROUP_UNKNOWN_MESSAGE = "找不到這個投放組。"
AD_UNKNOWN_MESSAGE = "找不到這支廣告。"


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
    # F03-I08：素材 tab 跟發布畫面共用同一組 ready_count/total（§0）。
    campaign["asset_readiness"] = assets.readiness_summary(
        assets.readiness(web.conn, actor.org_id, brand_id, campaign_id),
    )
    return {"campaign": campaign}


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
    return {"campaign": campaign}


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
    name: str
    role: str
    daily_budget: float
    start_date: str | None = None
    end_date: str | None = None


@router.post("/brands/{brand_id}/campaigns/{campaign_id}/groups")
def create_group(
    request: Request, brand_id: str, campaign_id: str, body: CreateGroupRequest,
):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
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
}


class CreateAdRequest(BaseModel):
    group_id: str
    name: str
    coordinates: dict


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
    return {"assets": rows, **assets.readiness_summary(rows)}


class AssetReadyRequest(BaseModel):
    ready: bool


@router.post("/brands/{brand_id}/ads/{ad_id}/asset-ready")
def set_asset_ready(request: Request, brand_id: str, ad_id: str, body: AssetReadyRequest):
    """F03-I08：手動勾／取消勾「素材已就位」。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
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
            ad["copy_text"] = None
            ad["image_prompt_text"] = None
            ad_brief = briefs_by_ad_id.get(ad["id"])
            if ad_brief is None:
                continue
            copy_output = workbench.adopted_output(conn, org_id, brand_id, ad_brief["id"], "copy")
            if copy_output is not None:
                sets = (copy_output.get("body_json") or {}).get("sets")
                if isinstance(sets, list) and sets and isinstance(sets[0], dict):
                    ad["copy_text"] = sets[0].get("body")
            image_output = workbench.adopted_output(
                conn, org_id, brand_id, ad_brief["id"], "image_prompt",
            )
            if image_output is not None:
                rendered = (image_output.get("body_json") or {}).get("rendered")
                if isinstance(rendered, str):
                    ad["image_prompt_text"] = rendered
                elif isinstance(rendered, list) and rendered:
                    first = rendered[0]
                    if isinstance(first, str):
                        ad["image_prompt_text"] = first
                    elif isinstance(first, dict):
                        ad["image_prompt_text"] = first.get("prompt")
    return detail


_PUBLISH_ERRORS = {
    "campaign_unknown": (404, CAMPAIGN_UNKNOWN_MESSAGE),
    "adapter_unknown": (400, "找不到這個發布方式。"),
    "auto_meta_not_connected": (400, adapters.AUTO_META_NOT_CONNECTED_MESSAGE),
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
    return {
        "adapters": adapters.ADAPTERS, "adapter": adapter, "describe": chosen.describe(enriched),
    }


class PublishRequest(BaseModel):
    adapter: str = "manual"


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
        chosen.publish(web.conn, actor.org_id, brand_id, campaign_id, actor=str(actor.user_id))
    except ValueError as exc:
        code = str(exc)
        status, message = _PUBLISH_ERRORS.get(code, (400, code))
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
    return result
