"""顧問分析報告的 React JSON API 與背景生成工作。

對外進入點：本檔的 router。
輸入輸出：GET 回 {report, job}；POST 回 {ok, message} 或 HTTP 400 detail。
誰依賴它：app.main、React 顧問分析報告頁。
不碰什麼：不 import app.brand_web.routes，不修改舊 Jinja 路由或 app.brand_intelligence.report。

票 08：報告生成從行程內 dict＋thread 搬上 `app.background` 佇列（見
docs/contracts/background.md）——三個搬上佇列的 kind 裡最貼近 `app/schedule/routes.py`
範本的一個：一個品牌同時只有一次在跑，狀態直接讀這個品牌 task_type='brand_report'
最新一列 llm_task，不必像品牌智庫抽原話（job_key）或產品調研（product_id）額外存一個
關聯鍵。`active_jobs()`（原本供 dashboard 聚合）已刪：這三個 kind 現在由
`app/dashboard/routes_jobs_api.py` 直接讀佇列彙總，見該檔——那個檔案原本繞過
`register()` 直接 import 這裡的 `active_jobs`（`docs/contracts/brand_web.md` 記錄的
違規），這個函式一刪，那個違規對這個 kind 也就不存在了。
"""

from fastapi import APIRouter, HTTPException, Request

from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as repo
from app.brand_web import report_service
from app.core.db import connection as core_db_connection
from app.core.db import new_id
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, require_actor, require_brand

router = APIRouter()
_STALE_MESSAGE = "品牌資料在報告生成後又更新過，內容可能已經不準。"
ALREADY_GENERATING_MESSAGE = "這個品牌的報告正在生成中。"


def _latest_report_task_row(conn, brand_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = 'brand_report' "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _report_staleness(report: dict, brand: dict) -> str | None:
    if brand["knowledge_version"] > report["brand_version"]:
        return _STALE_MESSAGE
    return None


def _report_shape(report: dict, brand: dict) -> dict:
    cost_row = None
    if report["llm_task_id"]:
        cost_row = web.conn.execute(
            "SELECT cost FROM llm_task WHERE id = %s", (report["llm_task_id"],)
        ).fetchone()
    return {
        "generated_at": report["generated_at"],
        "brand_version": report["brand_version"],
        "model": report["model"],
        "source_fact_count": report["source_fact_count"],
        "cost": cost_row["cost"] if cost_row else None,
        "staleness": _report_staleness(report, brand),
        "thin_data": report["source_fact_count"] < 5,
        "sections": report_service.sections(report),
    }


def _job_shape(brand_id: str) -> dict:
    """讀 llm_task 最新一列取代讀行程內 dict（票 08）——跟 `app/schedule/state.py`
    `_display_task_row()` 同一個讀法，套到單一 task_type：一個品牌同時只有一次報告
    在跑，不必分「還在跑」與「上一次成功」兩層顯示。"""
    row = _latest_report_task_row(web.conn, brand_id)
    if row is None or row["status"] == "succeeded":
        return {"status": "idle"}
    if row["status"] == "running":
        return {"status": "running", "stage": "正在整理五章", "started_at": row["started_at"]}
    return {"status": "failed", "message": row["error"] or "報告生成失敗。"}


def _notify(brand_id: str, message: str) -> None:
    background_job.notify(
        web.conn, brand_id, category="brand_report_done", dedupe_key=new_id("rptjob"),
        message=message, action_url=f"/app/brands/{brand_id}/report",
    )


def background_brand_report(org_id: str, brand_id: str, actor: str) -> None:
    """procrastinate task body（`background.brand_report`）——worker 執行，自己開一條
    連線（worker 不繼承 request 的連線）。"""
    with core_db_connection() as conn:
        try:
            ok, message = report_service.generate(conn, brand_id, actor)
        except Exception as exc:  # noqa: BLE001 — worker 最後一道防線，不能讓例外憑空消失
            ok, message = False, f"背景執行發生未預期錯誤：{exc}"
        if ok:
            _notify(brand_id, "顧問分析報告已生成。")
        else:
            _notify(brand_id, f"顧問分析報告生成失敗：{message or '報告生成失敗。'}")


@router.get("/api/brands/{brand_id}/report")
def report_get(request: Request, brand_id: str):
    actor = require_actor(request)
    try:
        brand = require_brand(brand_id, actor)
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    report = repo.get_latest_brand_report(web.conn, brand_id)
    return {"report": _report_shape(report, brand) if report else None, "job": _job_shape(brand_id)}


@router.post("/api/brands/{brand_id}/report/generate")
def report_generate(request: Request, brand_id: str):
    actor = require_actor(request)
    try:
        require_brand(brand_id, actor)
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    lock = f"brand_report:{brand_id}"
    if background_is_active(lock):
        raise HTTPException(status_code=400, detail=ALREADY_GENERATING_MESSAGE)
    if report_service.recent(brand_id):
        raise HTTPException(status_code=400, detail="剛剛才生成過，兩分鐘後再試。")

    if not background_enqueue(
        "background.brand_report", org_id=actor.org_id, lock=lock,
        brand_id=brand_id, actor=str(actor.user_id),
    ):
        raise HTTPException(status_code=400, detail=ALREADY_GENERATING_MESSAGE)
    return {"ok": True, "message": "報告生成中，好了會通知你。"}
