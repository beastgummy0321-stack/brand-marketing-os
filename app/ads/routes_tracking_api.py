# -*- coding: utf-8 -*-
"""R5/R6 追蹤鏈兩支 JSON API＋票 T0 品牌層追蹤健檢 JSON API；回應逐欄對齊
frontend/src/lib/warroomApi.ts（追蹤鏈部分）與 .scratch/grill/t0-tracking-wireframe.html
（健檢部分）。

品牌層健檢用 `/api/campaigns/brands/{brand_id}/...`（字面 "brands" 段），不用
`/api/campaigns/{brand_id}/...`——後者兩段式會被 routes_campaigns_open_api.py 的
通用「檔期詳情」`GET /{brand_id}/{cycle_id}` 萬用路由當成 cycle_id 吃掉（同
routes_campaigns_list_api.py 檔頭說明的既有解法）。背景「重新檢查全部」與輪詢沿用
app/ads/routes.py 既有的 `_progress_state` 引擎（同 routes_campaigns_open_api.py
plan_generate／plan_status 那組寫法），不新造第二套背景框架。
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from app.shared.web import JSONResponse

import app.shared.web as main_mod
from app.ads import routes as ads_routes
from app.ads import tracking
from app.ads.routes_common import _require_cycle

router = APIRouter()

_RECHECK_STAGES = [("check_website", "檢查官網追蹤碼")]


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/api/campaigns/{brand_id}/{cycle_id}/tracking-chain")
async def tracking_chain_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return _envelope(tracking.tracking_chain(main_mod.conn, brand_id, cycle_id))


@router.post("/api/campaigns/{brand_id}/{cycle_id}/tracking-chain/mapping/confirm")
async def tracking_mapping_confirm(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    actor = main_mod.require_actor(request)
    try:
        tracking.confirm_suggested_mapping(main_mod.conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    tracking.run_post_sync_checks(main_mod.conn, brand_id)
    return JSONResponse(None, status_code=204)


# ---------------------------------------------------------------------------
# 票 T0：品牌層追蹤健檢（契約 1.1-1.8／2.1／2.4／2.6）
# ---------------------------------------------------------------------------

@router.get("/api/campaigns/brands/{brand_id}/tracking-health")
async def tracking_health_get(brand_id: str):
    main_mod.require_brand(brand_id)
    return _envelope(tracking.tracking_health(main_mod.conn, brand_id))


@router.post("/api/campaigns/brands/{brand_id}/tracking-health/recheck")
async def tracking_health_recheck_start(brand_id: str):
    """重新檢查全部（契約 1.7）：背景執行。實際會動網路的只有官網 GA4／Pixel 偵測——
    其餘四路每次 GET tracking-health 本來就是即時查，沒有可快取的網路呼叫要重跑。"""
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    key = ads_routes._progress_key("tracking_recheck", brand_id, "_")

    def work(_on_stage):
        tracking.check_website_now(conn, brand_id)
        return True, None

    ads_routes._progress_start(key, _RECHECK_STAGES, work)
    return JSONResponse(None, status_code=204)


@router.get("/api/campaigns/brands/{brand_id}/tracking-health/recheck/status")
async def tracking_health_recheck_status(brand_id: str):
    """輪詢端點，沿用 routes_campaigns_open_api.py `plan_status` 同一套讀法。"""
    main_mod.require_brand(brand_id)
    key = ads_routes._progress_key("tracking_recheck", brand_id, "_")
    entry = ads_routes._progress_state.get(key)
    if entry is None:
        return _envelope({"status": "done"})
    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            message = "檢查逾時了，可以再試一次。"
            ads_routes._progress_fail(key, message)
            return _envelope({"status": "failed", "message": message})
        return _envelope({"status": "running"})
    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(key)
    if outcome_kind == "error":
        return _envelope({"status": "failed", "message": payload})
    ok, err = payload
    return _envelope({"status": "done"} if ok else {"status": "failed", "message": err})


@router.post("/api/campaigns/brands/{brand_id}/tracking-health/website/check")
async def tracking_health_website_check(brand_id: str):
    """精靈頁 2.4「我裝好了，幫我檢查」：單獨重跑官網偵測，同步（fetch_raw_html 10 秒
    逾時），失敗不擋人——回應一律 200，狀態燈自己會誠實反映抓不到／沒裝的結果。"""
    main_mod.require_brand(brand_id)
    return _envelope(tracking.check_website_now(main_mod.conn, brand_id))


async def _hidden_body(request: Request) -> bool:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return bool(isinstance(body, dict) and body.get("hidden"))


@router.post("/api/campaigns/brands/{brand_id}/tracking-health/{channel_key}/hidden")
async def tracking_health_hidden_set(request: Request, brand_id: str, channel_key: str):
    main_mod.require_brand(brand_id)
    if channel_key not in tracking.TRACKING_CHANNEL_KEYS:
        return JSONResponse({"error": f"不認得的通路：{channel_key}"}, status_code=404)
    hidden = await _hidden_body(request)
    tracking.set_channel_hidden(main_mod.conn, brand_id, channel_key, hidden)
    return JSONResponse(None, status_code=204)
