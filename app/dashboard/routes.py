# -*- coding: utf-8 -*-
"""app/dashboard/routes.py — 儀表板 JSON API（票 02-overview-cards，規格 0001 唯一新接縫）。

只讀、統一回應信封（data／generated_at）；不寫入任何資料表。給票 01 的 React 新殼
首頁（跨品牌總覽）打這支端點取資料。
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import auto_sync as ads_auto_sync
from app.dashboard import repository as dashboard_repo

router = APIRouter(prefix="/api/dashboard")


def _today_override():
    """測試接縫：BRAND_OS_TODAY 凍結「今天」（比照 BRAND_OS_DB 慣例），未設用真實日期。"""
    return os.environ.get("BRAND_OS_TODAY") or None


@router.get("/overview")
async def overview():
    return {
        "data": dashboard_repo.overview(main_mod.conn, today=_today_override()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/brands/{brand_id}/cockpit")
async def cockpit(brand_id: str):
    """單品牌駕駛艙（票 03-cockpit-kpi-chart）：KPI 卡＋主圖時間序列。404 沿用
    既有 `require_brand`（app/shared/web.py），跟舊介面一致的「找不到品牌」回應。"""
    brand = main_mod.require_brand(brand_id)
    data = dashboard_repo.cockpit(main_mod.conn, brand_id, today=_today_override())
    data["brand_id"] = brand["id"]
    data["brand_name"] = brand["name"]
    return {
        "data": data,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/brands/{brand_id}/sync")
async def sync_brand(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    try:
        updated_at = ads_auto_sync.sync_brand_now(main_mod.conn, brand_id, actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return {
        "data": {"updated_at": updated_at},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
