"""app/dashboard/routes_jobs_api.py — 全站生成進度單一出口聚合端點（票 B4-warroom 接線，
`.scratch/grill/GRILL-B4-warroom.md`「全站生成進度單一出口（模組邊界定案）」節，型別
逐欄對照 `frontend/src/lib/jobsApi.ts`）。

聚合 intake、產品調研、品牌智庫、顧問報告四個模組的公開 `active_jobs()`。各擁有者負責篩選與
正規化自己的工作狀態；本檔只補品牌名稱。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.brand_intelligence import repository as bi
from app.brand_web.routes_library import active_jobs as library_active_jobs
from app.brand_web.routes_products import active_jobs as product_research_active_jobs
from app.brand_web.routes_report_api import active_jobs as brand_report_active_jobs
from app.intake.routes_api import active_jobs as intake_active_jobs
from app.shared import web
from app.shared.web import require_actor

router = APIRouter()


@router.get("/api/jobs/active")
def jobs_active(request: Request):
    """票 03-1 r1 defect 2：四個 registry 是行程內記憶體、沒有 org_id 可查——過濾改在這裡
    做，每個 job 的 brand_id 反查一次 brand 列（本來就要查來補 brand_name），比對
    `brand["org_id"] == actor.org_id` 才留下。品牌已被刪掉的 job 直接丟棄（不再算得出
    是哪個組織的，「（品牌已刪除）」這個標籤這裡不再出現）。"""
    actor = require_actor(request)
    conn = web.conn
    active = (
        intake_active_jobs() + product_research_active_jobs() + library_active_jobs()
        + brand_report_active_jobs()
    )
    jobs = []
    for job in active:
        brand = bi.get_brand(conn, job["brand_id"])
        if brand is None or brand["org_id"] != actor.org_id:
            continue
        jobs.append({**job, "brand_name": brand["name"]})
    return {"data": jobs, "generated_at": datetime.now(UTC).isoformat()}
