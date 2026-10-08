"""app/dashboard/routes_jobs_api.py — 全站背景工作單一出口聚合端點（票 B4-warroom 接線，
型別逐欄對照 `frontend/src/lib/jobsApi.ts`）。

F29-I05（feature Contract G）：資料來源從「`llm_task` 裡 running 的列」換成 procrastinate
佇列本身（`app.background.queue_snapshot()`）——`llm_task` 只看得到已經在打模型的那一刻，
排隊中的工作、不打模型的工作（同步成效、檢查活動）在那張表裡都不存在，所以鈴鐺以前對
它們是瞎的。現在每一件 todo／doing 的工作都有位置（整條佇列、進行中排最前面），對照表以
**佇列任務名**為鍵（不是 `llm_task.task_type`），每個 `background.ads_*` 都有一句名稱。

租戶邊界照舊（ADR 0038）：工作屬於哪個組織寫在它自己的 args（`org_id`），品牌再用
`bi.get_brand()` 反查、比對 `brand.org_id == actor.org_id` 才列出來。其他組織的工作、
沒有 `brand_id` 的工作（例如每分鐘的排程器、只帶 org 的每日拉取）與品牌已被刪掉的工作
都不列出，只算進 `other_count`，但仍佔位置（同一個 worker）。job 的 args 絕不原樣吐出。

`done_today`／`failed_today`（F50-I07，Contract J）：數的是 procrastinate 今天（組織的一天）
記下的 succeeded／failed。每個 task 都經 `background.register()` 註冊，handler 回
`Failed`、拋 `JobFailed` 或拋任何例外，job 都會是 failed——吞掉的失敗不再算成完成；回
`Empty`（沒有東西要做）算完成。形狀不變。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app import background, workbench
from app.brand_intelligence import repository as bi
from app.core import settings
from app.core.db import now_iso, now_utc
from app.shared import web
from app.shared.web import app_path, require_actor

router = APIRouter()

# 佇列任務名 -> (kind, stage)。kind 的顯示名稱在前端 `ACTIVE_JOB_KIND_LABELS`（接在「正在」
# 後面也要通順）；stage 是列上的固定說明，逐步進度照舊放棄（票 08／09）。
TASK_KINDS: dict[str, tuple[str, str]] = {
    "background.customer_voice_extraction": ("library_convert", "分析原話中"),
    "background.product_scan": ("product_research", "讀取網址中"),
    "background.brand_report": ("brand_report", "正在整理五章"),
    "background.intake_scan": ("scan", "讀取網址中"),
    "background.intake_persona": ("persona", "整理人物誌"),
    "background.intake_product_prefill": ("product_scan", "讀取商品頁中"),
    "background.schedule_plan": ("schedule_plan", "出方案中"),
    "background.schedule_tree": ("schedule_tree", "展開活動樹中"),
    "background.performance_reading": ("schedule_diagnosis", "判讀成效中"),
    "background.workbench_generate": ("workbench_generate", "素材生成中"),
    "background.meta_daily_pull": ("meta_pull", "讀取 Meta 花費中"),
    "background.meta_backfill": ("meta_backfill", "補抓過去的廣告中"),
    "background.ads_external_sync": ("ads_sync", "讀取廣告平台成效中"),
    "background.ads_runtime_campaign": ("ads_runtime", "檢查活動狀態與預算中"),
    "background.ads_close_expired": ("ads_runtime", "檢查活動狀態與預算中"),
    "background.ads_queue_refresh": ("ads_runtime", "整理今天的待辦中"),
    "background.ads_review_round": ("ads_review", "AI 判讀中"),
    "background.ads_angles": ("ads_angles", "AI 整理主打中"),
    "background.ads_user_asset_preview": ("ads_asset_preview", "產生預覽中"),
    "background.ads_user_asset_suggestions": ("ads_asset_suggestions", "AI 看素材中"),
}
_OTHER = ("other", "處理中")
_SCOPE_KEYS = ("campaign_id", "entity_id")


def _action_url(conn, org_id: str, brand_id: str, kind: str, args: dict) -> str:
    base = app_path(f"/brands/{brand_id}")
    campaign = args.get("campaign_id")
    if kind == "product_research":
        return f"{base}/products/{args.get('product_id', '')}"
    if kind in ("library_convert", "persona"):
        return f"{base}/library?tab=customer-voice"
    if kind == "scan":
        return f"{base}/intake"
    if kind == "product_scan":  # F43-I06: the product-page read -> that product's onboarding
        return f"{base}/products/{args.get('product_id', '')}/onboarding"
    if kind == "workbench_generate":
        return workbench.set_action_url(
            conn, org_id, brand_id, args.get("brief_id", ""),
        ) or f"{base}/workbench"
    if kind == "brand_report":
        return f"{base}/report"
    if kind == "ads_sync":
        return f"{base}/ads/connections"
    if campaign and kind.startswith("ads_"):
        return f"{base}/ads/campaigns/{campaign}/detail"
    return f"{base}/ads"


def _since(conn, org_id: str) -> datetime:
    """00:00 today in the org's own timezone (the same "today" every other screen uses)."""
    return settings.org_day_start(conn, org_id=org_id,
                                  day=settings.today_for_org(conn, org_id=org_id))


@router.get("/api/jobs/active")
def jobs_active(request: Request):
    actor = require_actor(request)
    conn = web.conn
    snapshot = background.queue_snapshot(since=_since(conn, actor.org_id))
    # F47 Contract C: stalled = no live worker while this org has queued/running work (any of
    # its jobs, listed below or not — a job without a brand still waits on the same worker).
    worker_alive = bool(snapshot["worker_alive"])
    org_waiting = any(job["org_id"] == actor.org_id for job in snapshot["jobs"])
    brands: dict[str, dict | None] = {}
    jobs = []
    for job in snapshot["jobs"]:
        args = job["args"]
        brand_id = args.get("brand_id")
        if job["org_id"] != actor.org_id or not isinstance(brand_id, str) or not brand_id:
            continue
        if brand_id not in brands:
            brands[brand_id] = bi.get_brand(conn, brand_id)
        brand = brands[brand_id]
        if brand is None or brand["org_id"] != actor.org_id:
            continue
        kind, stage = TASK_KINDS.get(job["task_name"], _OTHER)
        waited = job["waited_seconds"]
        started_at = ""
        if job["status"] == "running" and waited is not None:
            started_at = datetime.fromtimestamp(
                now_utc().timestamp() - waited, UTC).isoformat()
        jobs.append({
            "brand_id": brand_id, "brand_name": brand["name"], "kind": kind,
            "status": job["status"], "stage": stage, "started_at": started_at,
            "action_url": _action_url(conn, actor.org_id, brand_id, kind, args),
            "position": job["position"], "task_name": job["task_name"],
            "scope": {k: args[k] for k in _SCOPE_KEYS if isinstance(args.get(k), str)},
            "waited_seconds": waited,
        })
    return {
        "data": jobs,
        "total": snapshot["total"],
        "other_count": snapshot["total"] - len(jobs),
        "done_today": snapshot["done_today"].get(actor.org_id, 0),
        "failed_today": snapshot["failed_today"].get(actor.org_id, 0),
        "worker_alive": worker_alive,
        "stalled": snapshot["worker_health"]["state"] == "stopped" and org_waiting,
        "worker_health": snapshot["worker_health"],
        "generated_at": now_iso(),
    }
