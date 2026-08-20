# -*- coding: utf-8 -*-
"""app/dashboard/routes_jobs_api.py — 全站生成進度單一出口聚合端點（票 B4-warroom 接線，
`.scratch/grill/GRILL-B4-warroom.md`「全站生成進度單一出口（模組邊界定案）」節，型別
逐欄對照 `frontend/src/lib/jobsApi.ts`）。

聚合 intake、產品調研、原話轉換三個模組的公開 `active_jobs()`。各擁有者負責篩選與
正規化自己的工作狀態；本檔只補品牌名稱。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.brand_intelligence import repository as bi
from app.brand_web.routes_library import active_jobs as library_active_jobs
from app.brand_web.routes_products import active_jobs as product_research_active_jobs
from app.brand_web.routes_report_api import active_jobs as brand_report_active_jobs
from app.ads.routes_onboarding_api import active_jobs as onboarding_active_jobs
from app.intake.routes_api import active_jobs as intake_active_jobs
from app.shared import web

router = APIRouter()


def _brand_name(conn, brand_id: str) -> str:
    brand = bi.get_brand(conn, brand_id)
    return brand["name"] if brand else "（品牌已刪除）"


@router.get("/api/jobs/active")
async def jobs_active():
    conn = web.conn
    active = (
        intake_active_jobs() + product_research_active_jobs() + library_active_jobs()
        + brand_report_active_jobs() + onboarding_active_jobs()
    )
    jobs = [{**job, "brand_name": _brand_name(conn, job["brand_id"])} for job in active]
    return {"data": jobs, "generated_at": datetime.now(timezone.utc).isoformat()}
