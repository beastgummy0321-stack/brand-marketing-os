"""顧問分析報告的 React JSON API 與背景生成工作。

對外進入點：本檔的 router、active_jobs()。
輸入輸出：GET 回 {report, job}；POST 回 {ok, message} 或 HTTP 400 detail；
active_jobs() 回六欄背景工作列。
誰依賴它：app.main、app.dashboard.routes_jobs_api、React 顧問分析報告頁。
不碰什麼：不 import app.brand_web.routes，不修改舊 Jinja 路由或 app.brand_intelligence.report。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.brand_intelligence import background_job
from app.brand_intelligence import repository as repo
from app.brand_web import report_service
from app.core.db import new_id
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, require_actor, require_brand

router = APIRouter()
_report_jobs = background_job.JobRegistry()
_STALE_MESSAGE = "品牌資料在報告生成後又更新過，內容可能已經不準。"


def active_jobs() -> list[dict]:
    """回傳進行中的報告生成工作，供 dashboard 聚合；不洩漏 registry 狀態。"""
    return [
        {
            "brand_id": state["brand_id"],
            "kind": "brand_report",
            "status": state["status"],
            "stage": state.get("stage") or "",
            "started_at": state.get("started_at") or "",
            "action_url": f"/app/brands/{state['brand_id']}/report",
        }
        for _brand_id, state in _report_jobs.items()
        if state.get("status") in ("running", "waiting") and state.get("brand_id")
    ]


def _job_state(brand_id: str) -> dict:
    return _report_jobs.get(brand_id, {"status": "idle"})


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
    state = _job_state(brand_id)
    if state.get("status") == "running":
        return {
            "status": "running",
            "stage": state.get("stage") or "正在整理五章",
            "started_at": state.get("started_at") or "",
        }
    if state.get("status") == "failed":
        return {"status": "failed", "message": state.get("message") or "報告生成失敗。"}
    return {"status": "idle"}


def _notify(brand_id: str, message: str) -> None:
    background_job.notify(
        web.conn, brand_id, category="brand_report_done", dedupe_key=new_id("rptjob"),
        message=message, action_url=f"/app/brands/{brand_id}/report",
    )


def _run_report(brand_id: str, actor: str) -> None:
    try:
        ok, message = report_service.generate(web.conn, brand_id, actor)
    except Exception as exc:  # noqa: BLE001 — 背景執行緒不可讓例外憑空消失
        ok, message = False, f"背景執行發生未預期錯誤：{exc}"

    started_at = _job_state(brand_id).get("started_at", datetime.now(UTC).isoformat())
    if ok:
        _notify(brand_id, "顧問分析報告已生成。")
        _report_jobs.set(brand_id, {
            "status": "done", "stage": "完成", "started_at": started_at, "brand_id": brand_id,
        })
        return

    error = message or "報告生成失敗。"
    _notify(brand_id, f"顧問分析報告生成失敗：{error}")
    _report_jobs.set(brand_id, {
        "status": "failed", "stage": "正在整理五章", "started_at": started_at,
        "brand_id": brand_id, "message": error,
    })


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
    if _job_state(brand_id).get("status") == "running":
        raise HTTPException(status_code=400, detail="這個品牌的報告正在生成中。")
    if report_service.recent(brand_id):
        raise HTTPException(status_code=400, detail="剛剛才生成過，兩分鐘後再試。")

    started_at = datetime.now(UTC).isoformat()
    _report_jobs.start(
        brand_id,
        {"status": "running", "stage": "正在整理五章", "started_at": started_at, "brand_id": brand_id},
        _run_report,
        (brand_id, str(actor.user_id)),
        idempotent=True,
    )
    return {"ok": True, "message": "報告生成中，好了會通知你。"}
