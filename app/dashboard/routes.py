# -*- coding: utf-8 -*-
"""app/dashboard/routes.py — 儀表板 JSON API（票 02-overview-cards，規格 0001 唯一新接縫）。

只讀、統一回應信封（data／generated_at）；不寫入任何資料表。給票 01 的 React 新殼
首頁（跨品牌總覽）打這支端點取資料。
"""

from datetime import datetime, timezone

from fastapi import APIRouter

import app.shared.web as main_mod
from app.dashboard import repository as dashboard_repo

router = APIRouter(prefix="/api/dashboard")


@router.get("/overview")
async def overview():
    return {
        "data": dashboard_repo.overview(main_mod.conn),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
