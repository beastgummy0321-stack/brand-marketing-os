"""app/dashboard/routes_jobs_api.py — 全站生成進度單一出口聚合端點（票 B4-warroom 接線，
`.scratch/grill/GRILL-B4-warroom.md`「全站生成進度單一出口（模組邊界定案）」節，型別
逐欄對照 `frontend/src/lib/jobsApi.ts`）。

聚合 intake（仍是行程內 registry，票 09 的範圍）與品牌智庫抽原話／產品調研／顧問報告
三個已經搬上 `app.background` 佇列的 kind（票 08：`docs/contracts/brand_web.md` 記錄的
「本檔直接 import 三個路由檔的 `active_jobs`」違規，隨這三個 kind 搬上佇列一起解除——
那三個檔案已經沒有 `active_jobs()` 可以 import，本檔改直接讀佇列的資料來源
`llm_task`）。intake 那個 registry 沒有 org_id 可查，過濾仍在這裡做。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.brand_intelligence import repository as bi
from app.intake.routes_api import active_jobs as intake_active_jobs
from app.shared import web
from app.shared.web import require_actor

router = APIRouter()

# task_type -> (kind, 固定顯示的 stage 文字)。三個搬上佇列的 kind 逐步進度已經放棄
# （票 08 明文決定），running 一律回同一句固定字串，跟這三個 kind 自己 POST 端點
# 剛送出時的初始 stage 文字一致，不是隨便挑的佔位字。
_QUEUE_JOB_KINDS = {
    "customer_voice_extraction": ("library_convert", "分析原話中"),
    "product_scan": ("product_research", "讀取網址中"),
    "brand_report": ("brand_report", "正在整理五章"),
}


def _queue_active_jobs(conn) -> list[dict]:
    """回傳三個已搬上佇列的 kind 目前 running 的工作，直接讀 `llm_task`（票 08）——
    `docs/contracts/background.md`：這張表沒有專屬模組，任何模組都能讀（已有
    `app/schedule/state.py`／`app/brand_web/routes_report_api.py` 先例）。"""
    rows = conn.execute(
        "SELECT brand_id, task_type, started_at, context_scope_json FROM llm_task "
        "WHERE status = 'running' AND task_type = ANY(%s)",
        (list(_QUEUE_JOB_KINDS),),
    ).fetchall()
    jobs = []
    for row in rows:
        kind, stage = _QUEUE_JOB_KINDS[row["task_type"]]
        brand_id = row["brand_id"]
        scope = row["context_scope_json"] or {}
        if kind == "product_research":
            action_url = f"/app/brands/{brand_id}/products/{scope.get('product_id', '')}"
        elif kind == "library_convert":
            action_url = f"/app/brands/{brand_id}/library"
        else:
            action_url = f"/app/brands/{brand_id}/report"
        jobs.append({
            "brand_id": brand_id, "kind": kind, "status": "running", "stage": stage,
            "started_at": row["started_at"].isoformat() if row["started_at"] else "",
            "action_url": action_url,
        })
    return jobs


@router.get("/api/jobs/active")
def jobs_active(request: Request):
    """票 03-1 r1 defect 2：intake 的 registry 是行程內記憶體、沒有 org_id 可查——過濾
    改在這裡做，每個 job 的 brand_id 反查一次 brand 列（本來就要查來補 brand_name），
    比對 `brand["org_id"] == actor.org_id` 才留下。品牌已被刪掉的 job 直接丟棄（不再
    算得出是哪個組織的，「（品牌已刪除）」這個標籤這裡不再出現）。"""
    actor = require_actor(request)
    conn = web.conn
    active = intake_active_jobs() + _queue_active_jobs(conn)
    jobs = []
    for job in active:
        brand = bi.get_brand(conn, job["brand_id"])
        if brand is None or brand["org_id"] != actor.org_id:
            continue
        jobs.append({**job, "brand_name": brand["name"]})
    return {"data": jobs, "generated_at": datetime.now(UTC).isoformat()}
