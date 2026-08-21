# -*- coding: utf-8 -*-
"""app/ads/routes_plan.py — 打法生成進度頁（第 8 刀從 app/ads/routes.py 拆出；T4 廣告
模組 Jinja 大清倉又刪掉本檔其餘全部 Jinja 舊頁與表單）。

本檔現在只剩這一條路由：
- `/brands/{b}/ads/{cycle}/plan/progress`       打法生成進度頁（背景執行＋冪等閘＋逾時，
  test_ads_progress_background.py 直打這條路由，逐一驗證三件事：不同步等生成跑完、
  F5 冪等、逾時放棄；redirect 目的地 `/plan/select` 這串子字串也被斷言，但那個頁本身
  的 GET 已隨 T4 刪除，純轉址字串，不影響）。

T4 一併刪除：開新檔期（`/ads/new`）、封存／恢復（`/{cycle}/archive`）、永久刪除
（`/{cycle}/delete`）、檔期內頁（`/{cycle}` 萬用路由）、選方案頁（`/plan/select`）、
異議拍板（`/dissents/{id}/decide`）、關卡一確認（`/plan/approve`）、開素材資料夾
（`/{cycle}/creative-folder`）、目標 CPA 引導（`/new/target-cpa-guided`）、排期策略更新
（`/{cycle}/pacing`）——全部被 `/api/campaigns/...` 等價端點取代（routes_campaigns_
open_api.py 等，不在本票範圍），測試與 React 都已不再打這批舊路徑。

背景進度引擎在 app/ads/routes_progress.py，本檔的 ads_plan_progress 一律 `ads_routes.`
開頭即時查值，理由見該檔檔頭說明。
"""

import time
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import plan as ads_plan
from app.ads import routes as ads_routes
from app.llm import providers as llm_providers
from app.ads.routes_common import _require_cycle

router = APIRouter()

_PLAN_STAGES = [
    ("prep", "整理這期的資料與方法論"),
    ("ask_ai", "請 AI 生成方案"),
    ("save", "把方案存起來"),
]


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
