# -*- coding: utf-8 -*-
"""app/dashboard/routes_jobs_api.py — 全站生成進度單一出口聚合端點（票 B4-warroom 接線，
`.scratch/grill/GRILL-B4-warroom.md`「全站生成進度單一出口（模組邊界定案）」節，型別
逐欄對照 `frontend/src/lib/jobsApi.ts`）。

聚合三處既有 `JobRegistry`（`background_job.JobRegistry.items()`，本票新增的公開列舉
方法）：`routes_library._cv_jobs`、`routes_products._research_jobs`、
`intake.routes_api._JOBS`。單向依賴：本檔認識三個 registry，三個 registry 不認識本檔
（見 background_job.py 檔頭「誰依賴它」）。只讀，不寫任何一個 registry。

只收 status 為 running／waiting（真的還在進行）的條目——done／failed 這類終態通知已經
走 `background_job.notify()` 進收件匣，鈴鐺不重複累積一份永不清除的完成紀錄
（ponytail：三個 registry 都不會自動清除已完成的 entry，見各自檔頭註解；鈴鐺只顯示
「現在還在跑什麼」，跳過終態展示，之後真的需要時再加「已讀」欄位升級）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.brand_intelligence import repository as bi
from app.brand_intelligence.routes_library import _cv_jobs
from app.brand_intelligence.routes_products import _research_jobs
from app.intake.routes_api import _JOBS as _intake_jobs
from app.shared import web

router = APIRouter()

_ACTIVE_STATUSES = ("running", "waiting")


def _brand_name(conn, brand_id: str) -> str:
    brand = bi.get_brand(conn, brand_id)
    return brand["name"] if brand else "（品牌已刪除）"


def _intake_active_jobs(conn) -> list:
    jobs = []
    for brand_id, state in _intake_jobs.items():
        if state.get("status") not in _ACTIVE_STATUSES:
            continue
        jobs.append({
            "brand_id": brand_id, "brand_name": _brand_name(conn, brand_id),
            "kind": state.get("kind", "scan"), "status": state["status"],
            "stage": state.get("stage") or "", "started_at": state.get("started_at") or "",
            "action_url": f"/brands/{brand_id}/intake",
        })
    return jobs


def _product_research_active_jobs(conn) -> list:
    jobs = []
    for product_id, state in _research_jobs.items():
        if state.get("status") not in _ACTIVE_STATUSES:
            continue
        brand_id = state.get("brand_id")
        if not brand_id:
            continue
        jobs.append({
            "brand_id": brand_id, "brand_name": _brand_name(conn, brand_id),
            "kind": "product_research", "status": state["status"],
            "stage": state.get("stage") or "", "started_at": state.get("started_at") or "",
            "action_url": f"/brands/{brand_id}/products/{product_id}",
        })
    return jobs


def _library_convert_active_jobs(conn) -> list:
    jobs = []
    for _job_key, state in _cv_jobs.items():
        if state.get("status") not in _ACTIVE_STATUSES:
            continue
        brand_id = state.get("brand_id")
        if not brand_id:
            continue
        jobs.append({
            "brand_id": brand_id, "brand_name": _brand_name(conn, brand_id),
            "kind": "library_convert", "status": state["status"], "stage": "分析原話中",
            "started_at": state.get("started_at") or "", "action_url": f"/brands/{brand_id}/library",
        })
    return jobs


@router.get("/api/jobs/active")
async def jobs_active():
    conn = web.conn
    jobs = (_intake_active_jobs(conn) + _product_research_active_jobs(conn)
           + _library_convert_active_jobs(conn))
    return {"data": jobs, "generated_at": datetime.now(timezone.utc).isoformat()}
