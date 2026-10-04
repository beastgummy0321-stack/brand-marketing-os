"""app/dashboard/routes.py — 儀表板 JSON API（票 02-overview-cards，規格 0001 唯一新接縫）。

只讀、統一回應信封（data／generated_at）；不寫入任何資料表。給票 01 的 React 新殼
首頁（跨品牌總覽）打這支端點取資料。

外殼切片（2026-08-28）：單品牌駕駛艙、數字月報、手動同步三支端點隨 `app/ads/` 一起
刪掉（見 `app/dashboard/repository.py` 檔頭）。票 06 補回品牌頁的本月花費／營收／毛利／
ROAS 併桌：`/brands/{brand_id}/month`。
"""


from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.core import settings as coresettings
from app.core.config import settings
from app.core.db import now_iso
from app.dashboard import repository as dashboard_repo

router = APIRouter(prefix="/api/dashboard")


def _today(org_id: str) -> str:
    """組織行事曆上的今天（F50 Contract K：`today_for_org`，不是機器的日期）。
    測試接縫：BRAND_OS_TODAY 凍結「今天」，設了就用它。"""
    return settings().brand_os_today or coresettings.today_for_org(
        main_mod.conn, org_id=org_id).isoformat()


@router.get("/overview")
def overview(request: Request):
    actor = main_mod.require_actor(request)
    return {
        "data": dashboard_repo.overview(
            main_mod.conn, org_id=actor.org_id, today=_today(actor.org_id)),
        "generated_at": now_iso(),
    }


@router.get("/brands/{brand_id}/month")
def brand_month(request: Request, brand_id: str):
    """票 06：品牌頁本月花費／營收／毛利／ROAS 併桌。"""
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return {
        "data": dashboard_repo.brand_month_money(
            main_mod.conn, org_id=actor.org_id, brand_id=brand_id, today=_today(actor.org_id)),
        "generated_at": now_iso(),
    }
