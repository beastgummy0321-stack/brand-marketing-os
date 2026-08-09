# -*- coding: utf-8 -*-
"""app/ads/routes_plan.py — 開新檔期、封存／刪除、檔期內頁、打法規劃與選擇（第 8 刀從
app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/new`                         開新檔期
- `/brands/{b}/ads/{cycle}/archive`             封存／恢復檔期
- `/brands/{b}/ads/{cycle}/delete`              永久刪除檔期
- `/brands/{b}/ads/{cycle}`                     單一檔期頁（萬用路由，要掛在最後）
- `/brands/{b}/ads/{cycle}/plan/progress`       打法生成進度頁
- `/brands/{b}/ads/{cycle}/plan/select`         選方案
- `/brands/{b}/ads/{cycle}/dissents/{id}/decide` AI 具名異議拍板
- `/brands/{b}/ads/{cycle}/plan/approve`        關卡一：計畫確認

背景進度引擎留在 app/ads/routes.py，本檔的 ads_plan_progress 一律 `ads_routes.`
開頭即時查值，理由見 routes_sync.py 檔頭說明。
"""

import time
from datetime import date
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Form, Request

import app.shared.web as main_mod
from app.ads import account_structure
from app.ads import budget as budget_calc
from app.ads import creative as ads_creative
from app.ads import handoff as ads_handoff
from app.ads import nextcycle
from app.ads import onboarding
from app.ads import performance as ads_performance
from app.ads import plan as ads_plan
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads import simulation
from app.ads import target_cpa
from app.ads import theme_batch
from app.ads.routes_common import (
    DEFAULT_STEP_INDEX, DURATION_TIER_CONFIG, OBJECTIVES, OBJECTIVE_LABELS, SLIDER_STEPS,
    _crumb, _cycle_progress_items, _cycle_view, _duration_suggestion, _recommended_objective,
    _require_cycle, _slider_options,
)
from app.brand_intelligence import repository as bi
from app.core import creative_assets
from app.llm import providers as llm_providers

router = APIRouter()

_PLAN_STAGES = [
    ("prep", "整理這期的資料與方法論"),
    ("ask_ai", "請 AI 生成方案"),
    ("save", "把方案存起來"),
]


def _new_page_ctx(request: Request, conn, brand: dict, brand_id: str, *, selected: list,
                  errors: dict, form: dict, recommended_objective: str) -> dict:
    """開新檔期頁的共用 context（GET 首次載入、POST 驗證失敗回顯都走這裡，避免兩份漂移）。"""
    products = [p for p in bi.list_products(conn, brand_id) if p.get("status") == "active"]
    amount = form.get("_amount") or SLIDER_STEPS[DEFAULT_STEP_INDEX]
    current_objective = form.get("objective") or recommended_objective
    weekly_budget = round(budget_calc.plan_from_pain(amount).daily_budget * 7, 2)
    return main_mod.ctx(
        request, brand=brand, nav_current='ads', products=products,
        slider_options=_slider_options(), default_index=DEFAULT_STEP_INDEX,
        objectives=OBJECTIVES, recommended_objective=recommended_objective,
        duration_suggestion=_duration_suggestion(amount),
        duration_tier_config=DURATION_TIER_CONFIG,
        default_start_date=date.today().isoformat(),
        readiness_notes=ads_repo.check_readiness(conn, brand_id, selected),
        offer_simulation=simulation.offer_simulation(conn, brand_id),
        # 目標 CPA 三層鏈＋投放量護欄＋三檔預算卡（票 21）：跟其餘欄位一樣，只在 GET 首次
        # 載入／POST 驗證失敗回顯時算一次，使用者切換 radio／checkbox 不會即時重算
        # ——readiness_notes 也是同一套規則，兩邊一致。
        target_cpa_view=target_cpa.guardrail_view(
            conn, brand_id, objective=current_objective, product_ids=selected,
            weekly_budget=weekly_budget),
        breadcrumb_items=_crumb(brand, ("開新檔期", None)),
        errors=errors, form=form,
    )


@router.get("/brands/{brand_id}/ads/new")
async def ads_new_get(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    product_ids = [p["id"] for p in bi.list_products(conn, brand_id)
                  if p.get("status") == "active"]
    return main_mod.templates.TemplateResponse(
        request, "ads_new.html",
        _new_page_ctx(request, conn, brand, brand_id, selected=product_ids, errors={}, form={},
                     recommended_objective=_recommended_objective(conn, brand_id, product_ids)),
    )


@router.post("/brands/{brand_id}/ads/new")
async def ads_new_post(request: Request, brand_id: str,
                       product_ids: Optional[List[str]] = Form(None),
                       slider_index: str = Form(""),
                       custom_amount: str = Form(""),
                       objective: str = Form(""),
                       duration_days: str = Form(""),
                       start_date: str = Form(""),
                       background: str = Form(""),
                       mode: str = Form("real")):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    actor = main_mod.require_actor(request)

    selected = product_ids or []
    # 「我知道要投多少」展開後直接填的金額優先於滑桿（決策 0022 第 10 點）
    amount, amount_ok = main_mod.parse_number(custom_amount)
    if amount is None:
        try:
            amount = SLIDER_STEPS[int(slider_index)]
        except (ValueError, IndexError):
            amount = SLIDER_STEPS[DEFAULT_STEP_INDEX]

    errors = {}
    if not amount_ok or (amount is not None and amount <= 0):
        errors["amount"] = "請填一個大於 0 的金額。"
    if objective not in OBJECTIVE_LABELS:
        errors["objective"] = "請選一個本期目標。"

    duration_value = None
    duration_text = duration_days.strip()
    if duration_text:
        try:
            duration_value = int(duration_text)
        except ValueError:
            errors["duration_days"] = "檔期長度請填數字。"
        else:
            if not (budget_calc.MIN_DURATION_DAYS <= duration_value <= budget_calc.MAX_DURATION_DAYS):
                errors["duration_days"] = (f"檔期長度請填 {budget_calc.MIN_DURATION_DAYS}"
                                            f"–{budget_calc.MAX_DURATION_DAYS} 天之間。")

    start_date_text = start_date.strip()
    if start_date_text:
        try:
            date.fromisoformat(start_date_text)
        except ValueError:
            errors["start_date"] = "開始日期格式不對。"

    form = {"product_ids": selected, "custom_amount": custom_amount, "objective": objective,
            "duration_days": duration_days, "start_date": start_date, "background": background,
            "_amount": amount if amount_ok and amount else None}

    if errors:
        return main_mod.templates.TemplateResponse(
            request, "ads_new.html",
            _new_page_ctx(request, conn, brand, brand_id, selected=selected, errors=errors,
                         form=form, recommended_objective=objective or _recommended_objective(
                             conn, brand_id, selected)),
            status_code=400,
        )

    # 模擬期只有這個品牌一期都還沒跑過時才成立，避免熟手誤開（或表單被動手腳）
    phase = "simulation" if (mode == "simulation"
                             and simulation.offer_simulation(conn, brand_id)) else "normal"
    cycle = ads_repo.create_cycle(conn, brand_id, product_ids=selected, pain_value=amount,
                                  objective=objective, actor=actor, phase=phase,
                                  start_date=start_date_text or None,
                                  duration_days=duration_value, background=background)
    message = ("模擬檔期開好了。接下來的每一步都跟真的一樣，只有最後的成效數字是模擬的。"
               if phase == "simulation" else "檔期已建立，接下來確認這期的計畫。")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle['id']}", message)


@router.post("/brands/{brand_id}/ads/new/target-cpa-guided")
async def ads_new_target_cpa_guided(request: Request, brand_id: str,
                                    events_per_sale: str = Form(""),
                                    margin_per_sale: str = Form("")):
    """目標 CPA 引導推算表單送出（票 21 第 3 層）：跟開新檔期共用同一個表單頁面，用
    formaction 送到這支獨立路由，存完導回原頁——這一步可跳過，不擋主表單送出。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back_url = f"/brands/{brand_id}/ads/new"
    events, events_ok = main_mod.parse_number(events_per_sale)
    margin, margin_ok = main_mod.parse_number(margin_per_sale)
    if not events_ok or not margin_ok or not events or not margin:
        return main_mod.redirect_with_message(
            back_url, "請把兩格都填成大於 0 的數字，或直接跳過這一步不用管它。", kind="warn",
            anchor="target-cpa")
    try:
        target_cpa.save_guided_target_cpa(main_mod.conn, brand_id, events_per_sale=events,
                                          margin_per_sale=margin, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back_url, str(exc), kind="warn", anchor="target-cpa")
    return main_mod.redirect_with_message(
        back_url, "已存好推算的目標 CPA，下面的護欄提醒會用這個數字。", anchor="target-cpa")


def _cycle_label(cycle: dict) -> str:
    """檔期沒有名稱欄位，畫面與刪除確認一律用日期範圍當識別文字。"""
    return f"{cycle['start_date']} ～ {cycle['end_date']}"


@router.post("/brands/{brand_id}/ads/{cycle_id}/archive")
async def ads_cycle_archive(request: Request, brand_id: str, cycle_id: str):
    """封存／恢復檔期（GitHub issue #28）。任何狀態（進行中、已結束）都能封存。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    new_archived = not cycle["archived"]
    ads_repo.set_cycle_archived(main_mod.conn, brand_id, cycle_id, archived=new_archived,
                                actor=actor)
    msg = (f"已封存 {_cycle_label(cycle)} 這期檔期。" if new_archived
           else f"已恢復 {_cycle_label(cycle)} 這期檔期。")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}", msg)


def _cycle_delete_counts(brand_id: str, cycle_id: str) -> list:
    """刪除確認頁要列的「會一起消失的資料」，只留有東西的項目（比照產品刪除）。"""
    rows = ads_repo.count_cycle_data(main_mod.conn, brand_id, cycle_id)
    return [(label, n) for label, n in rows if n > 0]


@router.get("/brands/{brand_id}/ads/{cycle_id}/delete")
async def ads_cycle_delete_get(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    cycle = _require_cycle(brand_id, cycle_id)
    if not cycle["archived"]:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "要先把檔期封存，才能永久刪除。", kind="warn")
    return main_mod.templates.TemplateResponse(
        request, "ads_cycle_delete.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=cycle, cycle_label=_cycle_label(cycle),
                     counts=_cycle_delete_counts(brand_id, cycle_id), error=None,
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             ("永久刪除檔期", None))),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/delete")
async def ads_cycle_delete_post(request: Request, brand_id: str, cycle_id: str,
                                confirm_name: str = Form("")):
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    if not cycle["archived"]:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "要先把檔期封存，才能永久刪除。", kind="warn")

    label = _cycle_label(cycle)
    if main_mod.clean(confirm_name) != label:
        return main_mod.templates.TemplateResponse(
            request, "ads_cycle_delete.html",
            main_mod.ctx(request, brand=brand, nav_current='ads', cycle=cycle, cycle_label=label,
                         counts=_cycle_delete_counts(brand_id, cycle_id),
                         error="輸入的檔期名稱跟上面顯示的不一樣，請照著再打一次。",
                         breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                         f"/brands/{brand_id}/ads/{cycle_id}"),
                                                 ("永久刪除檔期", None))),
            status_code=400,
        )

    main_mod.corebackup.snapshot(f"before-delete-{cycle_id}")
    ads_repo.delete_cycle(main_mod.conn, brand_id, cycle_id, actor=actor)
    # 素材圖檔資料夾一起刪（決策 0008 的例外：系統平常不自動刪圖，刪檔期時才刪）。
    # 排在 DB 刪完之後：圖救不回來，DB 有刪除前備份，先刪救得回來的那個。
    warn = creative_assets.delete_folder(main_mod.conn, brand_id, cycle_id)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads",
        f"已永久刪除 {label} 這期檔期。刪除前的備份已存進 backups 資料夾。{warn}")


@router.post("/brands/{brand_id}/ads/{cycle_id}/creative-folder")
async def ads_cycle_creative_folder_post(request: Request, brand_id: str, cycle_id: str):
    """開這期的素材圖檔資料夾：沒有就建，然後叫出檔案總管（決策 0008，圖不進系統）。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    path = creative_assets.open_folder(main_mod.conn, brand_id, cycle_id)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}",
        f"已開啟素材資料夾：{path}。把生圖工具下載的圖直接貼進去，檔名不用改。")


@router.get("/brands/{brand_id}/ads/{cycle_id}")
async def ads_cycle(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)

    view = _cycle_view(conn, brand_id, cycle)
    allocations = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
    plan_row = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
    pending_options = (ads_plan.get_pending_options(conn, brand_id, cycle_id)
                       if cycle["status"] == "PLAN_SELECT" else [])
    creatives = ads_creative.list_variants(conn, brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    creative_dir = creative_assets.cycle_dir(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_cycle.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=view, allocations=allocations,
                     plan_row=plan_row, plan=plan_row["plan"] if plan_row else None,
                     pending_option_count=len(pending_options),
                     audience_tier_labels=ads_plan.AUDIENCE_TIER_LABELS,
                     audience_tier_order=ads_plan.AUDIENCE_TIERS,
                     rule_cards=nextcycle.list_pending_rule_cards(conn, brand_id),
                     forecast=onboarding.forecast_snapshot(cycle),
                     diff=onboarding.diff_with_previous(conn, brand_id, cycle_id),
                     # 兌現預言卡出口(b)：第二期檔期內頁頂部常駐卡（票 F5，決策 0039 第 15 條），
                     # 讀「上一期」的快照與實際結果，不是這期自己的——只有上一期存過快照
                     # （目前只有校準期會存）prediction 才非 None，自然只在第二期出現。
                     prediction=ads_reading.prediction_settlement(
                         conn, brand_id, onboarding.previous_cycle(conn, brand_id, cycle)),
                     plan_cost=_plan_cost(conn, plan_row),
                     has_creatives=bool(creatives), creative_count=len(creatives),
                     has_adopted=any(v["decision"] and v["decision"]["decision"] == "adopted"
                                     for v in creatives),
                     package_count=len(packages),
                     activated_count=sum(1 for p in packages if p["mapping"]),
                     # 素材圖檔資料夾（決策 0008）：路徑與現在佔多少 MB 都是即時算的，
                     # 圖不進系統、DB 也不記，使用者在檔案總管裡加減檔案這裡就會跟著變。
                     creative_dir=str(creative_dir),
                     creative_mb=creative_assets.size_mb(creative_dir),
                     snapshot_count=len(ads_performance.list_snapshots(conn, brand_id, cycle_id)),
                     is_simulation=simulation.is_simulation(cycle),
                     readiness_notes=ads_repo.check_readiness(
                         conn, brand_id, [a["product_id"] for a in allocations]),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期", None)),
                     # 生成按鈕旁「本次會用」選單（票 #27）：模型清單沿用設定頁同一份，
                     # 思考等級固定五檔；預設值＝這個任務目前真的會用到的模型／思考等級
                     # （不帶覆寫時的 resolve 結果），不是憑空寫死。
                     model_choices=main_mod.MODEL_CHOICES,
                     thinking_choices=[(code, llm_providers.THINKING_LEVEL_LABELS[code])
                                       for code in llm_providers.THINKING_LEVEL_ORDER],
                     plan_default_model=llm_providers.resolve_model(
                         task_type="campaign_plan", conn=conn),
                     plan_default_thinking=llm_providers.resolve_thinking(task_type="campaign_plan"),
                     creative_default_model=llm_providers.resolve_model(
                         task_type="creative_batch", conn=conn),
                     creative_default_thinking=llm_providers.resolve_thinking(
                         task_type="creative_batch"),
                     **main_mod.banner_ctx(request)),
    )


def _plan_cost(conn, plan_row: Optional[dict]):
    """這份計畫花了多少錢（誠實揭露，比照顧問報告頁）。"""
    if not plan_row:
        return None
    task_id = plan_row["plan"].get("llm_task_id")
    if not task_id:
        return None
    row = conn.execute("SELECT cost FROM llm_task WHERE id = ?", (task_id,)).fetchone()
    return row["cost"] if row else None
@router.get("/brands/{brand_id}/ads/{cycle_id}/plan/progress")
def ads_plan_progress(request: Request, brand_id: str, cycle_id: str,
                      run: Optional[str] = None, direction: Optional[str] = None,
                      model: Optional[str] = None, thinking: Optional[str] = None):
    """生成方案要 30–60 秒。修憲落地 M3：生成丟背景執行緒跑，這條路由只讀進度狀態，
    完成時才 303——不再讓瀏覽器在 ?run=1 那次導航整個凍住。

    direction 有值＝老闆在方案選擇頁自己寫了方向，要求重新生成一批（票 4：自由輸入框）。
    model／thinking：生成按鈕旁「本次會用」選單的當場覆寫（票 #27），經 query string
    帶過第一跳 meta-refresh；只有真正啟動生成的那次呼叫會採用（見 _progress_start 的
    冪等閘：後續重整就算網址還帶著這兩個參數，也不會再影響已經在跑的那次呼叫）。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}"
    select_url = f"{result_url}/plan/select"
    was_selecting = cycle["status"] == "PLAN_SELECT"  # 這次是「重新生成」而不是第一次生成
    leave_url = select_url if was_selecting else result_url
    progress_key = ads_routes._progress_key("plan", brand_id, cycle_id)

    if run != "1":
        entry = ads_routes._progress_touch(progress_key, _PLAN_STAGES)
        run_url = f"{request.url.path}?run=1"
        if direction:
            run_url += f"&direction={quote(direction)}"
        if model:
            run_url += f"&model={quote(model)}"
        if thinking:
            run_url += f"&thinking={quote(thinking)}"
        return ads_routes._render_wait_page(
            request, brand, heading="正在規劃這期的打法", lede="這次會出 2 到 4 個方案讓你選。",
            run_url=run_url, leave_url=leave_url, breadcrumb_tail="規劃中",
            progress_rows=ads_routes._progress_definition_rows(_PLAN_STAGES, "plan", entry))

    def work(on_stage):
        with llm_providers.request_overrides(model=model, thinking=thinking):
            return ads_plan.generate_options(
                main_mod.conn, brand_id, cycle_id, actor, custom_direction=direction,
                on_stage=on_stage)

    entry = ads_routes._progress_start(progress_key, _PLAN_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                leave_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                          "可以再試一次，或先跳過這一步。", kind="warn")
        return ads_routes._render_wait_page(
            request, brand, heading="正在規劃這期的打法", lede="這次會出 2 到 4 個方案讓你選。",
            run_url=f"{request.url.path}?run=1", leave_url=leave_url, breadcrumb_tail="規劃中",
            progress_rows=ads_routes._progress_definition_rows(_PLAN_STAGES, "plan", entry))

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(leave_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(leave_url, err, kind="warn")
    return main_mod.redirect_with_message(select_url, "這期的方案準備好了，選一個或自己寫方向。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/plan/select")
async def ads_plan_select_page(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    options = ads_plan.get_pending_options(conn, brand_id, cycle_id)
    if not options:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", "這期還沒有可選的方案。", kind="warn")
    structure = account_structure.recommend(conn, ads_repo.derived_plan(cycle)["daily_budget"])
    dissents = ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
    return main_mod.templates.TemplateResponse(
        request, "ads_plan_select.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     options=options,
                     audience_tier_labels=ads_plan.AUDIENCE_TIER_LABELS,
                     audience_tier_order=ads_plan.AUDIENCE_TIERS,
                     methodology_missing=options[0].get("methodology_missing") or [],
                     structure=structure,
                     dissents=dissents,
                     dissent_target_labels=ads_plan.DISSENT_TARGET_LABELS,
                     breadcrumb_items=_crumb(brand, ("選方案", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/dissents/{dissent_id}/decide")
async def ads_dissent_decide(request: Request, brand_id: str, cycle_id: str, dissent_id: str,
                             decision: str = Form(...)):
    """老闆對一筆 AI 具名異議拍板：採納或不採納（決策 0023 第 14、25 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back_url = f"/brands/{brand_id}/ads/{cycle_id}/plan/select"
    try:
        ads_repo.decide_dissent(main_mod.conn, brand_id, cycle_id, dissent_id, decision, actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back_url, str(exc), kind="warn")
    label = "採納" if decision == "adopted" else "不採納"
    return main_mod.redirect_with_message(back_url, f"已記錄：{label}這條異議。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/plan/select")
async def ads_plan_select_submit(request: Request, brand_id: str, cycle_id: str,
                                 option_id: Optional[str] = Form(None)):
    """老闆選定一個方案，落地成正式計畫（沿用既有版本機制），接著走既有關卡一。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}"
    try:
        ads_plan.select_option(main_mod.conn, brand_id, cycle_id, actor,
                               option_id=option_id or None)
    except ValueError as exc:
        return main_mod.redirect_with_message(f"{result_url}/plan/select", str(exc), kind="warn")
    return main_mod.redirect_with_message(result_url, "方案選好了，看一下再決定要不要照做。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/plan/approve")
async def ads_plan_approve(request: Request, brand_id: str, cycle_id: str):
    """關卡一：計畫確認。這是三道人工關卡的第一道，不可由系統自動代按。

    核准成功後立刻觸發預選格批次生成（票 09-preselect-autogen，app/ads/theme_batch.py）：
    核准本身是已經發生的資料庫異動，批次生成是核准後的最佳努力動作——批次內部已經把
    「AI 沒回」「費用超過上限」都收成錯誤清單／budget_stopped 旗標，不會拋例外讓這支路由
    500，即使一個主題都沒生出來，使用者仍看得到「計畫確認了」，矩陣頁那些格維持灰卡，
    可以再手動點生成。批次生成放在 plan.py 之外（不是 plan.approve() 內部）是刻意的：
    theme_batch → brief_assembler → plan 已經是一條 import 鏈，plan.py 不能反過來 import
    theme_batch，否則兩者互相 import 形成環（app/tests/test_architecture_boundaries.py
    ImportCycleScanTest 這條防線設計上就是要擋這個，只是它只掃跨層 import，這裡先手動避開）。
    """
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_plan.approve(main_mod.conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}", str(exc), kind="warn")
    theme_batch.generate_preselected_batch(main_mod.conn, brand_id, cycle_id, actor=actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}", "計畫確認了，接下來做素材。")
