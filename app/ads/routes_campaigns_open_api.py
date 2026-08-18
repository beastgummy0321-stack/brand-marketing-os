# -*- coding: utf-8 -*-
"""app/ads/routes_campaigns_open_api.py — S8 開檔＋企劃 JSON API（票 B4-warroom 接線，契約
`.scratch/grill/GRILL-B4-warroom.md`＋`GRILL-B4R-performance.md`，型別逐欄對照
`frontend/src/lib/warroomApi.ts`）。

網址 `/api/campaigns/{brand_id}/...`（無字面 "brands" 段，跟 `routes_campaigns_list_api.py`
的區別見該檔檔頭說明）；具名子路徑（`new-context`／`ai-cost-meter`／`{cycle_id}/pacing` 等）
一律排在通用「檔期詳情」`GET /{brand_id}/{cycle_id}` 之前註冊——FastAPI／Starlette 依註冊
順序找第一個符合的路由，具名路徑不先擋住就會被通用兩段式路徑誤吃（同
`mocks/warroomHandlers.ts` 檔頭既有註記）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

import time
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import budget as budget_calc
from app.ads import account_structure
from app.ads import auto_sync as ads_auto_sync
from app.ads import plan as ads_plan
from app.ads import nextcycle
from app.ads import opening_suggestion
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads import simulation
from app.ads import stages
from app.ads import target_cpa
from app.ads import theme_batch
from app.ads.nextcycle import list_pending_rule_cards
from app.ads.routes_common import (
    DURATION_TIER_CONFIG, OBJECTIVES, _crumb, _cycle_view, _duration_suggestion,
    _recommended_objective, _require_cycle, _slider_options, derive_cycle_stage,
)
from app.brand_intelligence import repository as bi
from app.core import settings as core_settings

router = APIRouter()

_STAGE_INDEX_TO_NAME = {1: "plan", 2: "creative", 3: "handoff", 4: "prelaunch", 5: "performance"}

_PLAN_STAGES = [
    ("prep", "整理這期的資料與方法論"),
    ("ask_ai", "請 AI 生成方案"),
    ("save", "把方案存起來"),
]


def _envelope(data) -> dict:
    from datetime import datetime, timezone
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _cycle_json(view: dict) -> dict:
    """`Cycle`（`warroomApi.ts`）逐欄挑出，型別轉換（SQLite 0/1 → bool）。

    `pacing_strategy`／`pacing_reason` 在 TS 型別是必填（非 nullable）——`_cycle_view()`
    對舊資料（票 pacing-curve 上線前開的檔期，`derived_plan_json` 沒有這三個鍵）用 `.get()`
    給 `None`，這裡補一個安全預設（`continuous`，跟 `recommend_pacing_strategy()` 天數不足
    時的既有預設值一致），不把 `None` 傳給前端撞型別假設。
    """
    return {
        "id": view["id"], "brand_id": view["brand_id"], "start_date": view["start_date"],
        "end_date": view["end_date"], "status": view["status"], "phase": view["phase"],
        "objective": view["objective"], "funnel_stage": view.get("funnel_stage"),
        "budget": view["budget"], "duration_days": view.get("duration_days"),
        "daily_budget": view.get("daily_budget"), "background": view.get("background"),
        "pacing_strategy": view.get("pacing_strategy") or "continuous",
        "pacing_reason": view.get("pacing_reason") or "沒有特別理由，先求穩定",
        "archived": bool(view["archived"]), "daily_below_floor": bool(view.get("daily_below_floor")),
    }


def _budget_tier(amount: float, key: str, label: str) -> dict:
    amount = round(max(amount, 1))
    plan = budget_calc.plan_from_pain(amount)
    return {
        "key": key, "label": label, "amount": amount, "amount_label": f"{amount:,}",
        "duration_days": plan.duration_days, "daily_budget": round(plan.daily_budget),
        "daily_budget_label": f"{round(plan.daily_budget):,}", "below_floor": plan.daily_below_floor,
        "note": f"約 {plan.duration_days} 天，日預算約 {round(plan.daily_budget):,} 元。",
    }


def _budget_tiers(pain_suggestion: dict) -> list:
    """S8R.4 修復票：「自己調」展開的三檔預算卡，圍繞 AI 建議值展開（保守／建議／積極）。"""
    base = pain_suggestion["amount"]
    return [
        _budget_tier(base * 0.67, "conservative", "保守"),
        _budget_tier(base, "recommended", "建議"),
        _budget_tier(base * 1.5, "aggressive", "積極"),
    ]


# ---- 開檔（S8.1-11／S8R.1-7） ----

@router.get("/api/campaigns/brands/{brand_id}/opening-suggestion")
async def get_opening_suggestion(brand_id: str):
    main_mod.require_brand(brand_id)
    return opening_suggestion.opening_suggestion(main_mod.conn, brand_id)


@router.post("/api/campaigns/brands/{brand_id}/opening-suggestion/channel-answer")
async def post_opening_suggestion_channel_answer(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    body = await _json_body(request)
    return opening_suggestion.save_channel_answer(
        main_mod.conn, brand_id, actor=main_mod.require_actor(request), answer=body.get("answer")
    )

@router.get("/api/campaigns/{brand_id}/new-context")
async def new_context(brand_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    products = [p for p in bi.list_products(conn, brand_id) if p.get("status") == "active"]
    product_ids = [p["id"] for p in products]
    recommended_objective = _recommended_objective(conn, brand_id, product_ids)
    pain_suggestion = target_cpa.suggest_pain_value(conn, brand_id, recommended_objective, product_ids)
    return _envelope({
        "offer_simulation": simulation.offer_simulation(conn, brand_id),
        "products": [{"id": p["id"], "name": p["name"]} for p in products],
        "slider_options": _slider_options(),
        "budget_tiers": _budget_tiers(pain_suggestion),
        "duration_config": {"min": DURATION_TIER_CONFIG["min"], "max": DURATION_TIER_CONFIG["max"],
                            "min_daily_budget": DURATION_TIER_CONFIG["min_daily_budget"]},
        "duration_suggestion": (lambda d: {"value": d["days"], "basis_label": d["rationale"]})(
            _duration_suggestion(pain_suggestion["amount"])),
        "objectives": OBJECTIVES,
        "recommended_objective": recommended_objective,
        "readiness_notes": ads_repo.check_readiness(conn, brand_id, product_ids),
        "pain_suggestion": pain_suggestion,
    })


@router.get("/api/campaigns/{brand_id}/new-context/direction")
async def new_cycle_direction(brand_id: str):
    """歷來切角讀不到時不擋開檔，前端直接走一般推薦值。"""
    main_mod.require_brand(brand_id)
    try:
        cells = nextcycle.historical_cell_performance(main_mod.conn, brand_id)
    except Exception:  # noqa: BLE001 — 失敗收斂成不擋人的既有推薦路徑
        return _envelope({"status": "unavailable"})
    effective = [
        cell for cell in cells
        if cell.get("creative_angle") and (cell.get("conversions") or 0) > 0
    ]
    if not effective:
        return _envelope({"status": "empty"})
    best = max(effective, key=lambda cell: (cell["conversions"], cell.get("spend") or 0))
    return _envelope({"status": "ready", "direction": best["creative_angle"]})


@router.post("/api/campaigns/{brand_id}")
async def create_cycle(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    body = await _json_body(request)

    product_ids = body.get("product_ids") or []
    budget = body.get("budget")
    objective = str(body.get("objective") or "")
    duration_days = body.get("duration_days")
    background = body.get("background")

    if not isinstance(budget, (int, float)) or budget <= 0:
        return _error(400, "請填一個大於 0 的金額。")
    if not objective:
        return _error(400, "請選一個本期目標。")

    phase = "simulation" if (body.get("simulate") and simulation.offer_simulation(conn, brand_id)) else "normal"
    cycle = ads_repo.create_cycle(conn, brand_id, product_ids=list(product_ids), pain_value=budget,
                                  objective=objective, actor=actor, phase=phase,
                                  duration_days=duration_days, background=background)
    message = ("模擬檔期開好了。接下來的每一步都跟真的一樣，只有最後的成效數字是模擬的。"
              if phase == "simulation" else "檔期已建立，接下來確認這期的計畫。")
    return {"cycle_id": cycle["id"], "message": message}


@router.post("/api/campaigns/{brand_id}/target-cpa-guided")
async def target_cpa_guided(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    body = await _json_body(request)
    try:
        events = float(body.get("events_per_sale") or 0)
        margin = float(body.get("margin_per_sale") or 0)
    except (TypeError, ValueError):
        return _error(400, "請把兩格都填成大於 0 的數字。")
    try:
        result = target_cpa.save_guided_target_cpa(main_mod.conn, brand_id, events_per_sale=events,
                                                    margin_per_sale=margin, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return {"value": result["value"]}


# ---- 右欄 AI 花費儀表 ----

@router.get("/api/campaigns/{brand_id}/ai-cost-meter")
async def ai_cost_meter(brand_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    return _envelope({
        "brand_id": brand_id, "spent": core_settings.brand_llm_spent(conn, brand_id),
        "limit": core_settings.get_intake_budget_limit(conn), "settings_url": "/settings",
    })


# ---- 檔期完整狀態＋封存 ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}")
async def cycle_detail(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    view = _cycle_view(conn, brand_id, cycle)
    stage = "review" if cycle["status"] == "CLOSED" else _STAGE_INDEX_TO_NAME[derive_cycle_stage(conn, brand_id, cycle)]
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    readiness_notes = ads_repo.check_readiness(conn, brand_id, [a["product_id"] for a in allocations])
    return _envelope({"cycle": _cycle_json(view), "stage": stage, "readiness_notes": readiness_notes})


@router.post("/api/campaigns/{brand_id}/{cycle_id}/archive")
async def cycle_archive(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    ads_repo.set_cycle_archived(main_mod.conn, brand_id, cycle_id, archived=not cycle["archived"], actor=actor)
    return JSONResponse(None, status_code=204)


# ---- 企劃（S8.12-22） ----

@router.post("/api/campaigns/{brand_id}/{cycle_id}/plan/generate")
async def plan_generate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    body = await _json_body(request)
    direction = body.get("direction") or None
    key = ads_routes._progress_key("plan", brand_id, cycle_id)

    def work(on_stage):
        return ads_plan.generate_options(conn, brand_id, cycle_id, actor, custom_direction=direction,
                                         on_stage=on_stage)

    ads_routes._progress_start(key, _PLAN_STAGES, work)
    return JSONResponse(None, status_code=204)


@router.get("/api/campaigns/{brand_id}/{cycle_id}/plan/status")
async def plan_status(brand_id: str, cycle_id: str):
    """輪詢端點：沿用舊 Jinja `ads_plan_progress`（routes_plan.py）同一套背景執行緒／逾時
    判斷，只是把「轉址＋帶訊息」換成「JSON 狀態＋人話訊息」——同一個 `_progress_state`
    底層，不是第二套生成邏輯。entry 不存在（從沒生成過或已被消化）一律視為 done，
    這裡本來就是「已經有結果可以看」的意思，不是失敗。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    key = ads_routes._progress_key("plan", brand_id, cycle_id)
    entry = ads_routes._progress_state.get(key)
    if entry is None:
        return _envelope({"status": "done"})
    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(key)
            return _envelope({"status": "failed",
                               "message": "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                                          "可以再試一次，或先跳過這一步。"})
        return _envelope({"status": "running"})
    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(key)
    if outcome_kind == "error":
        return _envelope({"status": "failed", "message": payload})
    ok, err = payload
    if not ok:
        return _envelope({"status": "failed", "message": err})
    return _envelope({"status": "done"})


@router.get("/api/campaigns/{brand_id}/{cycle_id}/plan/options")
async def plan_options(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    options = ads_plan.get_pending_options(conn, brand_id, cycle_id)
    structure = account_structure.recommend(conn, brand_id, ads_repo.derived_plan(cycle)["daily_budget"])
    dissents = ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
    return _envelope({
        "options": options,
        "account_structure": {
            "tier": structure.tier, "tier_label": structure.tier_label,
            "structure_label": structure.structure_label,
            "groups": [{"role": g.role, "label": g.label, "ratio": g.ratio,
                       "daily_budget": g.daily_budget, "below_floor": g.below_floor}
                      for g in structure.groups],
            "note": structure.note,
        },
        "dissents": [{"id": d["id"], "target_type": d["target_type"], "suggestion": d["suggestion"],
                     "reason": d["reason"]} for d in dissents],
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/plan/select")
async def plan_select(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    body = await _json_body(request)
    try:
        ads_plan.select_option(main_mod.conn, brand_id, cycle_id, actor, option_id=body.get("option_id"))
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/dissents/{dissent_id}/decide")
async def dissent_decide(request: Request, brand_id: str, cycle_id: str, dissent_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    body = await _json_body(request)
    decision = "adopted" if body.get("accepted") else "rejected"
    try:
        ads_repo.decide_dissent(main_mod.conn, brand_id, cycle_id, dissent_id, decision, actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/plan/approve")
async def plan_approve(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    try:
        ads_plan.approve(conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return _error(400, str(exc))
    theme_batch.generate_preselected_batch(conn, brand_id, cycle_id, actor=actor)
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/pacing")
async def pacing_update(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    body = await _json_body(request)
    strategy = str(body.get("pacing_strategy") or "")
    reason = str(body.get("pacing_reason") or "")
    try:
        ads_repo.set_cycle_pacing(main_mod.conn, brand_id, cycle_id, strategy=strategy, reason=reason, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return JSONResponse(None, status_code=204)


@router.get("/api/campaigns/{brand_id}/{cycle_id}/rule-cards-learned")
async def rule_cards_learned(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    rows = list_pending_rule_cards(main_mod.conn, brand_id)
    return _envelope([{"text": r["proposed_rule_text"]} for r in rows])


# ---- 企劃排期到期提醒（S8R.9-11） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/schedule-reminder")
async def schedule_reminder(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    today = date.today().isoformat()
    reminder = ads_auto_sync.check_schedule_reminder(conn, brand_id, cycle_id, today)
    conn.commit()
    return _envelope(reminder)
