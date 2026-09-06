"""app/dashboard/routes_jobs_api.py — 全站生成進度單一出口聚合端點（票 B4-warroom 接線，
`.scratch/grill/GRILL-B4-warroom.md`「全站生成進度單一出口（模組邊界定案）」節，型別
逐欄對照 `frontend/src/lib/jobsApi.ts`）。

票 09：最後四個 kind（建檔初掃／出題／貼回修格式、人物誌生成）搬上 `app.background`
佇列，本檔對 `app/intake/routes_api.py` 的 `active_jobs` 直接 import（`docs/contracts/
brand_web.md` 記錄的違規在票 08 已經拿掉三個，這是最後一個倖存者）隨之拿掉——七個 kind
現在全部經同一條路徑讀 `llm_task`，沒有第二個機制。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.brand_intelligence import repository as bi
from app.shared import web
from app.shared.web import require_actor

router = APIRouter()

# task_type -> (kind, 固定顯示的 stage 文字)。逐步進度全部放棄（票 08／09 明文
# 決定），running 一律回同一句固定字串，跟各自 POST 端點剛送出時的初始 stage 文字一致，
# 不是隨便挑的佔位字。
_QUEUE_JOB_KINDS = {
    "customer_voice_extraction": ("library_convert", "分析原話中"),
    "product_scan": ("product_research", "讀取網址中"),
    "brand_report": ("brand_report", "正在整理五章"),
    "intake_scan": ("scan", "讀取網址中"),
    "intake_question": ("question", "正在準備下一題"),
    "intake_paste_fix": ("paste_fix", "正在請 AI 整理格式"),
    "intake_persona": ("persona", "整理人物誌"),
    # issue jobs-bell-blind-to-schedule-jobs（2026-09-06 演練）：產品裡最慢的三個工作
    # （實測出方案 43–53 秒、展開 46–59 秒、產素材 73–110 秒）本來一個都不在這份對照表裡，
    # 排程頁自己有行內進度，全站這顆鈴鐺對它們是瞎的——按下「產素材」的同時，右上角寫著
    # 「目前沒有進行中的背景工作」。stage 文字跟排程頁自己那句等待字對齊，不另編一句。
    "schedule_plan": ("schedule_plan", "出方案中"),
    "schedule_tree": ("schedule_tree", "展開活動樹中"),
    "schedule_creative": ("schedule_creative", "產素材中"),
}


def _queue_active_jobs(conn) -> list[dict]:
    """回傳這十個 kind 目前 running 的工作，直接讀 `llm_task`（票 08／09）——
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
        elif kind in ("library_convert", "persona"):
            action_url = f"/app/brands/{brand_id}/library"
        elif kind in ("scan", "question", "paste_fix"):
            action_url = f"/app/brands/{brand_id}/intake"
        elif kind in ("schedule_plan", "schedule_tree", "schedule_creative"):
            action_url = f"/app/brands/{brand_id}/schedule"
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
    """每個 job 的 `brand_id` 反查一次 brand 列（本來就要查來補 `brand_name`），比對
    `brand["org_id"] == actor.org_id` 才留下——過濾在這裡做，不是 `llm_task` 自己的查詢
    條件（票 03-1 r1 defect 2 遺留的做法，票 09 起七個 kind 統一沿用）。品牌已被刪掉的
    job 直接丟棄。"""
    actor = require_actor(request)
    conn = web.conn
    active = _queue_active_jobs(conn)
    jobs = []
    for job in active:
        brand = bi.get_brand(conn, job["brand_id"])
        if brand is None or brand["org_id"] != actor.org_id:
            continue
        jobs.append({**job, "brand_name": brand["name"]})
    return {"data": jobs, "generated_at": datetime.now(UTC).isoformat()}
