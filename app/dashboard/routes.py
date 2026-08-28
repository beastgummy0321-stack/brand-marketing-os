"""app/dashboard/routes.py — 儀表板 JSON API（票 02-overview-cards，規格 0001 唯一新接縫）。

只讀、統一回應信封（data／generated_at）；不寫入任何資料表。給票 01 的 React 新殼
首頁（跨品牌總覽）打這支端點取資料。

外殼切片（2026-08-28）：單品牌駕駛艙、數字月報、手動同步三支端點隨 `app/ads/` 一起
刪掉（見 `app/dashboard/repository.py` 檔頭）。只剩 `/overview`。
"""

import os
from datetime import UTC, datetime

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.dashboard import repository as dashboard_repo

router = APIRouter(prefix="/api/dashboard")


def _today_override():
    """測試接縫：BRAND_OS_TODAY 凍結「今天」，未設用真實日期。"""
    return os.environ.get("BRAND_OS_TODAY") or None


@router.get("/overview")
async def overview(request: Request):
    actor = main_mod.require_actor(request)
    return {
        "data": dashboard_repo.overview(
            main_mod.conn, org_id=actor.org_id, today=_today_override()),
        "generated_at": datetime.now(UTC).isoformat(),
    }
