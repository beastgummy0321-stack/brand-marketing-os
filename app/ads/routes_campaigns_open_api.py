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

import json
import time
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import budget as budget_calc
from app.ads import account_structure
from app.ads import auto_sync as ads_auto_sync
from app.ads import carry_forward
from app.ads import handoff as ads_handoff
from app.ads import offer as offer_mod
from app.ads import plan as ads_plan
from app.ads import nextcycle
from app.ads import opening_suggestion
from app.ads import proposal
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads import simulation
from app.ads import stages
from app.ads import target_cpa
from app.ads import theme_batch
from app.ads.nextcycle import list_pending_rule_cards
from app.llm import gateway
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


def _plan_generate_ceiling_seconds() -> int:
    """B0-45 缺陷 A：`_PROGRESS_TIMEOUT_SECONDS`（90 秒）是給等待頁「通常等多久」用的
    首版初值，比 `ads_plan.generate_options()` 實際呼叫 `gateway.run_task()` 時後端自己
    願意等的時間還短——`gateway.run_task()` 用 `TaskOptions` 預設值（`timeout_s=120`、
    `max_retries=1`），也就是 `max_attempts = 1 + max_retries` 次嘗試、每次最多等
    `timeout_s` 秒，全部落空前後端自己都還在正常等，天花板是 240 秒，不是 90 秒。

    跟 `_proposal_generate_ceiling_seconds()`（本檔上方）同樣的算法：這裡直接讀
    `gateway.TaskOptions()` 的預設值算出這一次合法等待的秒數，不是把
    `_PROGRESS_TIMEOUT_SECONDS` 這顆 tracking／weekly 共用的常數整顆調大——那兩邊
    （routes_tracking_api.py、routes_weekly_proposals_api.py）不在這張票的範圍內。
    """
    opts = gateway.TaskOptions()
    return int(opts.timeout_s * (1 + max(opts.max_retries, 0)))


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


_OFFER_TYPE_LABELS = dict(offer_mod.TYPES)


def _offer_json(offer) -> "dict | None":
    """`Offer`（`warroomApi.ts`）逐欄挑出——PUT `.../offer` 的 200 回應跟 `_cycle_json()`
    的 `offer` 鍵是同一個形狀（票 V1-01，容器契約第 4 條：mock 形狀＝進入點回傳形狀）。"""
    if offer is None:
        return None
    return {
        "id": offer["id"], "name": offer["name"], "offer_type": offer["offer_type"],
        "offer_type_label": _OFFER_TYPE_LABELS.get(offer["offer_type"], offer["offer_type"]),
        "terms": offer["terms"], "valid_from": offer["valid_from"], "valid_to": offer["valid_to"],
    }


def _cycle_json(view: dict, offer=None) -> dict:
    """`Cycle`（`warroomApi.ts`）逐欄挑出，型別轉換（SQLite 0/1 → bool）。

    `pacing_strategy`／`pacing_reason` 在 TS 型別是必填（非 nullable）——`_cycle_view()`
    對舊資料（票 pacing-curve 上線前開的檔期，`derived_plan_json` 沒有這三個鍵）用 `.get()`
    給 `None`，這裡補一個安全預設（`continuous`，跟 `recommend_pacing_strategy()` 天數不足
    時的既有預設值一致），不把 `None` 傳給前端撞型別假設。

    `offer`：呼叫端已經查好（沒掛就是 None），這裡只負責塞進去、不回頭查 DB（票 V1-01）。
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
        "plan_version": int(view["plan_version"] or 0), "offer": _offer_json(offer),
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
async def get_opening_suggestion(brand_id: str, from_cycle: str | None = None):
    main_mod.require_brand(brand_id)
    return opening_suggestion.opening_suggestion(main_mod.conn, brand_id, from_cycle=from_cycle)


@router.post("/api/campaigns/brands/{brand_id}/opening-suggestion/channel-answer")
async def post_opening_suggestion_channel_answer(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    body = await _json_body(request)
    return opening_suggestion.save_channel_answer(
        main_mod.conn, brand_id, actor=main_mod.require_actor(request), answer=body.get("answer"),
        from_cycle=body.get("from_cycle"),
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


_NO_QUALIFIED_WINNER_LABEL = "沿用上期設定"  # 票 F10：歷史切角存在但沒有誠實贏家
# （樣本不足／算不出 ROAS）時的畫面文字——不掛角名、不掛假數字，見票內契約。


@router.get("/api/campaigns/{brand_id}/new-context/direction")
async def new_cycle_direction(brand_id: str):
    """歷來切角讀不到時不擋開檔，前端直接走一般推薦值。

    票 F10：改用 `carry_forward.prior_winners()`（F7 的誠實門檻——樣本不足、虧本、算不出
    ROAS 的切角一律不算贏家）挑方向，不再直接對歷史切角取轉換數最大值；後者會把
    `experiment_cell.creative_angle` 的原始內部代號（例如驗收資料的 `normal_1`）原封不動
    顯示給品牌主看，鐵則 12 不許畫面出現內部代號。
    """
    main_mod.require_brand(brand_id)
    try:
        cells = nextcycle.historical_cell_performance(main_mod.conn, brand_id)
    except Exception:  # noqa: BLE001 — 失敗收斂成不擋人的既有推薦路徑
        return _envelope({"status": "unavailable"})
    if not cells:
        return _envelope({"status": "empty"})
    winners = carry_forward.prior_winners(main_mod.conn, brand_id)
    if not winners:
        return _envelope({"status": "ready", "label": _NO_QUALIFIED_WINNER_LABEL})
    best = winners[0]
    label = f"沿用上期贏家：{best['angle']}（ROAS {best['roas']:.2f}）"
    return _envelope({
        "status": "ready", "direction": best["angle"], "roas": best["roas"], "label": label,
    })


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
    offer_body = body.get("offer")

    if not isinstance(budget, (int, float)) or budget <= 0:
        return _error(400, "請填一個大於 0 的金額。")
    if not objective:
        return _error(400, "請選一個本期目標。")

    # 檔期長度範圍與型別驗證，照抄舊頁 routes_plan.py ads_new_post 那段（決策：這道防呆
    # 要保留，非工程背景的使用者需要白話錯誤訊息擋掉不合理天數）。
    duration_value = None
    if duration_days not in (None, ""):
        try:
            duration_value = int(duration_days)
        except (TypeError, ValueError):
            return _error(400, "檔期長度請填數字。")
        if not (budget_calc.MIN_DURATION_DAYS <= duration_value <= budget_calc.MAX_DURATION_DAYS):
            return _error(400, f"檔期長度請填 {budget_calc.MIN_DURATION_DAYS}"
                                f"–{budget_calc.MAX_DURATION_DAYS} 天之間。")

    # 開期表單順帶帶優惠（票 V1-01）：先驗證、驗證失敗不建檔期——所以放在 create_cycle()
    # 之前，跟金額／目標／天數同一批「還沒寫任何東西」的檢查。
    offer_fields = None
    if offer_body is not None:
        offer_fields, err = offer_mod.validate(offer_body)
        if err:
            return _error(400, err)

    phase = "simulation" if (body.get("simulate") and simulation.offer_simulation(conn, brand_id)) else "normal"
    # 「今天」只讀一次，接著同時餵給優惠與檔期。兩邊各喊一次 date.today() 的話，請求正好
    # 跨過午夜就會差一天，優惠的有效期跟檔期起訖對不上（審查提點，票 V1-01）。
    start = date.today()
    offer_id = None
    if offer_fields is not None:
        # offer 表沒有反向掛 campaign_cycle 的 FK，所以能先建這筆、再把 id 傳給
        # create_cycle()（呼叫順序見票面決策）。天數用同一顆 plan_from_pain 重算——檔期
        # 那時還不存在，沒有現成的 row 可以讀。
        plan_duration = duration_value or budget_calc.plan_from_pain(budget).duration_days
        end = start + timedelta(days=plan_duration - 1)
        offer_id = offer_mod.create(
            conn, brand_id, product_scope_json=json.dumps(list(product_ids), ensure_ascii=False),
            valid_from=start.isoformat(), valid_to=end.isoformat(), fields=offer_fields)
    cycle = ads_repo.create_cycle(conn, brand_id, product_ids=list(product_ids), pain_value=budget,
                                  objective=objective, actor=actor, phase=phase,
                                  start_date=start.isoformat(),
                                  duration_days=duration_value, background=background,
                                  offer_id=offer_id)
    proposal.seed_channel_plans(conn, brand_id, cycle["id"])
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

@router.get("/api/campaigns/brands/{brand_id}/cycles/{cycle_id}/proposal")
async def proposal_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    result = proposal.proposal(conn, brand_id, cycle_id)
    # 票 13 驗收 4：核可前把預估花費一起帶出去，跟矩陣頁同一個 cost_ceiling 天花板
    # （theme_batch.estimated_batch_cost，見該函式檔頭），不是另外編一個數字。同時帶出
    # 背景生成的逾時天花板（見下面 _proposal_generate_ceiling_seconds），讓前端輪詢的
    # 放棄時間點不會比伺服器自己判定逾時還早（付費手測抓到的第二層缺陷：前端原本寫死
    # 180 秒，8 次生成時伺服器天花板是 720 秒，前端會先喊「花比較久」，其實生成明明
    # 快成功了）。只有 ready 狀態才有 approval 這個鍵可以附加（assembling／failed 是
    # 空 dict）。
    #
    # 獨立審查抓到的最後一個 blocker：畫面上「AI 正在生成素材」的等待文案原本寫死抄
    # 單次生成慣例的「40 到 90 秒」，但這條路線一次跑 N 次序列生成（生成次數＝這裡
    # 附帶的 generation_count），套在整批上會偏離實際等待時間好幾倍。前端要能講出跟
    # 這批實際規模相稱的等待時間，就得知道這個數字——直接沿用同一個計數
    # （theme_batch.generation_count，跟上面花費預估／逾時天花板同一份），不是另外編
    # 第三個計數器，也不是讓前端自己猜。
    if result["status"] == "ready":
        result["approval"]["estimated_generation_cost"] = theme_batch.estimated_batch_cost(
            conn, brand_id, cycle_id)
        result["approval"]["estimated_generation_timeout_seconds"] = \
            _proposal_generate_ceiling_seconds(conn, brand_id, cycle_id)
        result["approval"]["generation_count"] = theme_batch.generation_count(
            conn, brand_id, cycle_id)
    return result


# 核可提案書後、背景生成預選素材用的階段清單（票 13）——只有一個實際階段，跟
# `_PLAN_STAGES` 同樣的「(key, 人話標籤)」形狀，供 `_progress_definition_rows` 共用。
_PROPOSAL_GENERATE_STAGES = [("generate", "AI 正在生成核可後的預選素材")]


def _proposal_generate_ceiling_seconds(conn, brand_id: str, cycle_id: str) -> int:
    """票 13 付費手測缺陷 1 的算式：`_PROGRESS_TIMEOUT_SECONDS`（90 秒）是給「一次生成」
    用的常數；`llm_task` 實測 task_type="creative_theme" 每次生成 23～31 秒，這次核准
    若跑 8 次、序列執行，全批約 215 秒，套用單次生成的 90 秒常數一定提早逾時。天花板要
    跟著這次核准實際會跑幾次生成走：`theme_batch.generation_count()`（跟 D3 花費預估
    同一個計數）乘上「每次生成的允許時間」——直接沿用 `_PROGRESS_TIMEOUT_SECONDS`
    當這個每次生成的允許值，比實測最慢 31 秒還有近 3 倍餘裕。`max(1, ...)` 保底：確保
    這裡算出來的天花板不會比原本單次生成用的 90 秒常數還短。

    `proposal_approve_status`（逾時判斷）與 `proposal_get`（告知前端該等多久，見上面）
    共用這同一個算式，不各寫一份。
    """
    count = theme_batch.generation_count(conn, brand_id, cycle_id)
    return max(1, count) * ads_routes._PROGRESS_TIMEOUT_SECONDS


@router.post("/api/campaigns/brands/{brand_id}/cycles/{cycle_id}/proposal/approve")
async def proposal_approve(request: Request, brand_id: str, cycle_id: str):
    """核可（`proposal.approve()`）維持同步、語意不變（D2）；核可後的預選素材生成改走
    跟 `plan_generate`／`plan_status`（本檔下方）同一套 `app.ads.routes_progress` 背景
    引擎（D1）——這支請求核可一落地就回應，不再同步等
    `theme_batch.generate_preselected_batch` 跑完八次生成（票 13 驗收 1）。生成本身若
    失敗，由下面 `proposal_approve_status` 回報，不回頭撤銷已經生效的核可（D2，驗收 3）。
    """
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    try:
        proposal.approve(conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return _error(400, str(exc))
    key = ads_routes._progress_key("proposal_generate", brand_id, cycle_id)

    def work(on_stage):
        return theme_batch.generate_preselected_batch(conn, brand_id, cycle_id, actor=actor)

    ads_routes._progress_start(key, _PROPOSAL_GENERATE_STAGES, work)
    return JSONResponse(None, status_code=204)


@router.get("/api/campaigns/brands/{brand_id}/cycles/{cycle_id}/proposal/approve-status")
async def proposal_approve_status(brand_id: str, cycle_id: str):
    """輪詢端點（票 13）：核可提案書後背景生成預選素材的進度。跟 `plan_status`
    （本檔下方）同一套 `_progress_state` 底層，只是 key 換成 "proposal_generate"這個
    kind——不會跟企劃出方案那份進度互相踩到。entry 不存在一律視為 done，沿用
    `plan_status` 既有慣例：這裡本來就是「已經有結果可以看」的意思，不是失敗。

    生成失敗只回報 failed，不影響核可本身：核可（`proposal.approve()`）已經在
    `proposal_approve()` 同步完成並回應過，這支只回報「之後」的生成進度（D2）。

    票 13 第三審查 blocker：`generate_preselected_batch()` 的回傳 dict
    （`{"themes"/"budget_stopped"/"errors"}`）之前被整批丟掉——work() 沒丟例外就回
    「done」，即使實際上一份都沒生出來（`_budget_blocked()` 在每次生成前都會查一次，
    AI 花費一開始就頂到上限時可以整批 0 產出）。使用者核可前才被告知「這一步會用 AI
    產素材，預估花費 US$X」，核可後卻無聲收場——正是這張票要殺的「花錢不告知」，只是
    晚一步發生。跟 `plan_status`（上面）拆自己 payload（`ok, err = payload`）同一個道理，
    這裡也要拆 `generate_preselected_batch()` 的 payload，分岔成三種語意，不是「沒丟
    例外＝done」一種：
      - 全部照計畫生成完成 → 沿用既有 "done"，不嚇使用者；
      - `budget_stopped`＝AI 花費撞到設定頁上限、整批提早收手 → "partial"，講清楚是
        撞到上限、做出了幾份、可以去設定頁調高上限（沿用
        `coresettings.budget_exceeded_message` 的用詞習慣，不是另編一套說法）；
      - `errors` 非空＝個別生成本身出狀況（AI 沒回、格式讀不成），跟花費無關 →
        "partial"，講成功幾份、失敗幾份，不把底層例外原文丟給非技術使用者看。
    這三種都不影響已經生效的核可（D2）——approve() 早在 `proposal_approve()` 就同步
    完成了，這裡只是把「後續生成做了多少」講清楚。
    """
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    key = ads_routes._progress_key("proposal_generate", brand_id, cycle_id)
    entry = ads_routes._progress_state.get(key)
    if entry is None:
        return _envelope({"status": "done"})
    if entry["status"] != "done":
        # 票 13 付費手測抓到的缺陷：固定 90 秒的單次生成常數套在整批八次生成上，正常
        # 成功的批次一定還沒跑完就先被判定逾時。天花板改成跟這次核准實際會跑幾次生成走，
        # 算式見 `_proposal_generate_ceiling_seconds`（跟 `proposal_get` 告知前端的是同一個
        # 數字），大幅降低誤判逾時的機率；B0-28 再補一層：即使真的撞到天花板，逾時分支也
        # 不再用 `_progress_clear()` 把 entry 整個拔掉（那樣會讓還在跑的背景執行緒事後把
        # 剛做好的 partial／budget_stopped 資訊憑空丟掉，下一次輪詢反而看到「done」——使用
        # 者被騙說失敗了，還可能因此重按一次而多花一次 AI 額度）。改用 `_progress_fail()`
        # 把 entry 標成終局的 failed 但留著，`_progress_start()` 之後靠這個狀態安全接回
        # 還在跑的舊執行緒，不重打一次（見兩支函式各自的 docstring）。
        ceiling_seconds = _proposal_generate_ceiling_seconds(conn, brand_id, cycle_id)
        if time.time() - entry["started_at"] > ceiling_seconds:
            message = ("AI 這次沒有在時間內回應。核可已經生效、資料都還在，"
                       "沒有掉。可以先去素材工作檯看看做出來的部分，或稍後再試一次。")
            ads_routes._progress_fail(key, message)
            return _envelope({"status": "failed", "message": message})
        return _envelope({"status": "running"})
    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(key)
    if outcome_kind == "error":
        return _envelope({"status": "failed", "message": payload})
    # outcome_kind == "ok"：work() 正常返回（沒有丟例外）。payload 是
    # generate_preselected_batch() 的回傳 dict，見上方 docstring 的三種分岔。
    themes_made = len(payload["themes"])
    if payload["budget_stopped"]:
        limit = core_settings.get_intake_budget_limit(conn)
        made_clause = f"先做出 {themes_made} 份就停下，其餘還沒生成" if themes_made \
            else "一份都還沒開始生成就先停下了"
        return _envelope({
            "status": "partial",
            "message": (f"AI 花費已經到設定頁目前的 US$ {limit:.2f} 上限，這次核可的素材生成"
                        f"{made_clause}。可以到「設定」頁調高上限，"
                        f"剩下的之後在素材工作檯手動補生成。"),
        })
    if payload["errors"]:
        failed_count = len(payload["errors"])
        return _envelope({
            "status": "partial",
            "message": (f"這次核可的素材生成，{themes_made} 份做出來了，{failed_count} 份"
                        f"沒有成功（AI 生成過程本身的問題，不是花費超支）。可以到素材工作檯"
                        f"查看，沒成功的部分再手動生成一次。"),
        })
    return _envelope({"status": "done"})


@router.post("/api/campaigns/brands/{brand_id}/cycles/{cycle_id}/proposal/return")
async def proposal_return(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    proposal.return_to_opening(main_mod.conn, brand_id, cycle_id, actor)
    return JSONResponse(None, status_code=204)

@router.get("/api/campaigns/{brand_id}/{cycle_id}")
async def cycle_detail(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    view = _cycle_view(conn, brand_id, cycle)
    stage = "review" if cycle["status"] == "CLOSED" else _STAGE_INDEX_TO_NAME[derive_cycle_stage(conn, brand_id, cycle)]
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    readiness_notes = ads_repo.check_readiness(conn, brand_id, [a["product_id"] for a in allocations])
    offer = offer_mod.get(conn, brand_id, view["offer_id"]) if view.get("offer_id") else None
    return _envelope({"cycle": _cycle_json(view, offer), "stage": stage, "readiness_notes": readiness_notes})


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
    底層，不是第二套生成邏輯。entry 不存在（從沒生成過、或成功結果已被上一次讀取消化）
    一律視為 done，這裡本來就是「已經有結果可以看」的意思，不是失敗。

    B0-28 根因：逾時分支以前呼叫 `_progress_clear()`，把 entry 整個拔掉——但背景執行緒
    （`ads_plan.generate_options()`）殺不掉，逾時當下它常常還在等 LLM 回應（`_USUAL_RANGE`
    寫的 30-60 秒是常態，撞到 `llm/gateway.py` 120 秒逾時＋一次重試時遠不只 90 秒）。entry
    一被拔掉，這支執行緒事後真的跑完、想寫回結果時找不到地方寫，成果安靜消失；下一次
    問狀態又落回「entry 不存在＝done」這條，變成「done 但沒有任何方案內容」——使用者看不到
    半句錯誤，AI 額度卻已經真的扣了。改叫 `_progress_fail()`：entry 留著、標成終局的
    failed，讓晚到的真結果事後寫得回來，也讓使用者不管問幾次都看到同一句失敗訊息，不會
    後面一問就悄悄變成看似正常的「done」。使用者按「重試」時，`_progress_start()` 會看
    entry 裡記的那條舊執行緒是否還活著：活著就安靜接回去等它，不重打一次 AI（不重複扣費）；
    真的已經死了才安心開一條新的。

    B0-45 根因修復：
    A. 逾時天花板不再用 `_PROGRESS_TIMEOUT_SECONDS`（tracking／weekly 共用的 90 秒），
       改用 `_plan_generate_ceiling_seconds()`（見本檔上方）算出這次出方案自己允許等的
       秒數——跟 `_proposal_generate_ceiling_seconds()` 同樣的道理：共用常數是給「通常
       等多久」的等待頁文案用的，逾時判定要對齊後端真正願意等的時間，不然會在自己還
       在合法等待範圍內的工作上宣告逾時。
    B. entry 一旦被判成終局的 `failed`（不管是這裡的逾時、還是下面業務失敗／背景例外），
       就直接把留在 entry 裡的訊息原樣回傳，不再往下走逾時重判那段——否則第二次讀取
       時 `entry["started_at"]` 還是那個舊時間戳，早就超過天花板，會被誤判成「又逾時了」
       而蓋掉真正的失敗訊息。業務失敗／背景例外原本讀一次就 `_progress_clear()`，第二次
       再問就落回「entry 不存在＝done」；改成跟逾時分支一樣呼叫 `_progress_fail()` 留著
       entry，讓攔下訊息撐過重整／元件重掛載。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    key = ads_routes._progress_key("plan", brand_id, cycle_id)
    entry = ads_routes._progress_state.get(key)
    if entry is None:
        return _envelope({"status": "done"})
    if entry["status"] == "failed":
        # 終局失敗：訊息已經留在 entry["result"] 裡（逾時或下面的業務失敗／例外都經過
        # _progress_fail 寫成統一的 ("error", 訊息) 形狀），原樣回傳，不重新判逾時。
        _, message = entry["result"]
        return _envelope({"status": "failed", "message": message})
    if entry["status"] != "done":
        if time.time() - entry["started_at"] > _plan_generate_ceiling_seconds():
            message = ("AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                       "可以再試一次，或先跳過這一步。")
            ads_routes._progress_fail(key, message)
            return _envelope({"status": "failed", "message": message})
        return _envelope({"status": "running"})
    outcome_kind, payload = entry["result"]
    if outcome_kind == "error":
        ads_routes._progress_fail(key, payload)
        return _envelope({"status": "failed", "message": payload})
    ok, err = payload
    if not ok:
        ads_routes._progress_fail(key, err)
        return _envelope({"status": "failed", "message": err})
    ads_routes._progress_clear(key)
    return _envelope({"status": "done"})


@router.get("/api/campaigns/{brand_id}/{cycle_id}/plan/options")
async def plan_options(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    options = ads_plan.get_pending_options(conn, brand_id, cycle_id)
    structure = account_structure.recommend(conn, brand_id, ads_repo.derived_plan(cycle)["daily_budget"])
    dissents = ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
    # cells／angle_locked（票 04-angle-rename 一.3）：`options` 選定後就是 plan_json 的舊快照
    # （campaign_plan_option 選定當下已清空，見 select_option()），角度名稱改過就跟不上；
    # 這裡另外附一份切角格現名，提案書畫面顯示切角要以這份為準，不改 options 本身形狀。
    return _envelope({
        "options": options,
        "cells": ads_plan.list_cell_angles(conn, brand_id, cycle_id),
        "angle_locked": ads_handoff.has_publishing_package(conn, brand_id, cycle_id),
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


@router.patch("/api/campaigns/{brand_id}/{cycle_id}/cells/{cell_id}/angle")
async def rename_cell_angle(request: Request, brand_id: str, cycle_id: str, cell_id: str):
    """切角改名（票 04-angle-rename 決議）：只改名，不動 schema、不重生已生成的素材。回應
    形狀是這張票給的固定契約（`{"ok", "creative_angle"}` 成功；`{"detail": "..."}` 400/404）
    ——不套本檔其餘路由用的 `_envelope()`／`_error()`，兩種錯誤 envelope 前端本就雙欄兼容
    （見 warroomApi.ts getJson 註解）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    conn = main_mod.conn
    cell = ads_plan.get_cell(conn, brand_id, cycle_id, cell_id)
    if cell is None:
        raise main_mod.NotFoundKind("切角格")

    body = await _json_body(request)
    try:
        creative_angle = ads_plan.rename_angle(
            conn, brand_id, cycle_id, cell, body.get("creative_angle", ""), actor)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"ok": True, "creative_angle": creative_angle}


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


@router.put("/api/campaigns/{brand_id}/{cycle_id}/offer")
async def offer_save(request: Request, brand_id: str, cycle_id: str):
    """開期後補填、或編輯這期的優惠（票 V1-01）。create-or-update：檔期已經掛了 offer
    就地改，沒有就新開一筆——`offer.save_for_cycle()` 判斷，這裡只管驗證跟轉形狀。
    不重算 `derived_plan_json`（票面決策：後補優惠不動使用者已經看過的日預算數字）。"""
    main_mod.require_brand(brand_id)
    cycle = _require_cycle(brand_id, cycle_id)
    body = await _json_body(request)
    fields, err = offer_mod.validate(body)
    if err:
        return _error(400, err)
    offer = offer_mod.save_for_cycle(main_mod.conn, brand_id, cycle, fields)
    return _envelope(_offer_json(offer))


@router.delete("/api/campaigns/{brand_id}/{cycle_id}/offer")
async def offer_clear(brand_id: str, cycle_id: str):
    """清掉這期的優惠：NULL 掉 `campaign_cycle.offer_id`、刪掉 offer row（票 V1-01）。
    同樣不重算 `derived_plan_json`。"""
    main_mod.require_brand(brand_id)
    cycle = _require_cycle(brand_id, cycle_id)
    offer_mod.clear_for_cycle(main_mod.conn, brand_id, cycle)
    return _envelope({"cleared": True})


@router.get("/api/campaigns/{brand_id}/{cycle_id}/rule-cards-learned")
async def rule_cards_learned(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    rows = list_pending_rule_cards(main_mod.conn, brand_id)
    return _envelope([{"id": r["id"], "text": r["proposed_rule_text"]} for r in rows])


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
