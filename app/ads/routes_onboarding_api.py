"""資料上線 React JSON API 與背景回填工作。

對外進入點：本檔的 ``router``、``active_jobs()``。
輸入輸出：GET 回 ``{data: {checklist, progress, maturity, jobs}, generated_at}``；
POST 回 ``{ok, message}`` 或 HTTP 400 的 ``detail``；``active_jobs()`` 回六欄工作列。
誰依賴它：app.main、app.dashboard.routes_jobs_api、資料上線 React 頁。
不碰什麼：不 import 舊 Jinja 路由或等待頁，不重寫 Meta／GA4 同步。
"""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.ads import data_onboarding, ga4_sync
from app.ads import sync as ads_sync
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as bi
from app.core import db as coredb
from app.core.db import new_id
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, require_actor, require_brand

router = APIRouter()
BACKFILL_MONTHS = 12
_jobs = background_job.JobRegistry()

_JOB_DETAILS = {
    "meta_backfill": {"stage": "正在回填 Meta 成效", "label": "Meta 成效"},
    "ga4_backfill": {"stage": "正在回填 GA4 資料", "label": "GA4 資料"},
    "ga4_sync": {"stage": "正在同步 GA4", "label": "GA4"},
}


def _key(kind: str, brand_id: str) -> str:
    return f"{kind}:{brand_id}"


def _state(kind: str, brand_id: str) -> dict:
    return _jobs.get(_key(kind, brand_id), {"status": "idle"})


def _job_shape(kind: str, brand_id: str) -> dict:
    state = _state(kind, brand_id)
    status = state.get("status", "idle")
    if status == "failed":
        return {"status": "failed", "message": state.get("message") or "背景工作失敗。"}
    if status in ("running", "done"):
        return {
            "status": status,
            "stage": state.get("stage") or _JOB_DETAILS[kind]["stage"],
            "started_at": state.get("started_at") or "",
        }
    return {"status": "idle"}


def active_jobs() -> list[dict]:
    """供全站工作鈴鐺聚合的六欄工作列。"""
    return [
        {
            "brand_id": state["brand_id"],
            "kind": state["kind"],
            "status": state["status"],
            "stage": state.get("stage") or "",
            "started_at": state.get("started_at") or "",
            "action_url": f"/app/brands/{state['brand_id']}/data-onboarding",
        }
        for _job_key, state in _jobs.items()
        if state.get("status") == "running" and state.get("brand_id")
    ]


def _notify(brand_id: str, message: str) -> None:
    background_job.notify(
        web.conn,
        brand_id,
        category="data_onboarding_done",
        dedupe_key=new_id("onboardjob"),
        message=message,
        action_url=f"/app/brands/{brand_id}/data-onboarding",
    )


def _finish(kind: str, brand_id: str, started_at: str, error: str | None) -> None:
    if error:
        _notify(brand_id, f"{_JOB_DETAILS[kind]['label']}處理失敗：{error}")
        _jobs.set(_key(kind, brand_id), {
            "status": "failed", "stage": _JOB_DETAILS[kind]["stage"],
            "started_at": started_at, "brand_id": brand_id, "kind": kind, "message": error,
        })
        return
    _notify(brand_id, f"{_JOB_DETAILS[kind]['label']}已完成。")
    _jobs.set(_key(kind, brand_id), {
        "status": "done", "stage": "完成", "started_at": started_at,
        "brand_id": brand_id, "kind": kind,
    })


def _run_meta_backfill(brand_id: str, actor: str) -> None:
    kind = "meta_backfill"
    started_at = _state(kind, brand_id).get("started_at", datetime.now(UTC).isoformat())
    try:
        since, until, _actual_months = ads_sync.backfill_range(BACKFILL_MONTHS)
        # bi.get_brand() 的 conn 參數明確標了型別 Conn；web.conn 是 ConnProxy（每次呼叫轉發
        # 到這個背景工作綁定的連線，見 app/core/db.py），這裡改成一開始就拿 coredb.current()
        # 拿到的那個真正的 Conn 實例——跟 ConnProxy 轉發的目標完全一樣，只是型別對得上。
        conn = coredb.current()
        brand = bi.get_brand(conn, brand_id)
        assert brand is not None, f"找不到品牌：{brand_id}"
        org_id = brand["org_id"]
        result = ads_sync.sync_account(conn, actor, org_id=org_id, since=since, until=until)
        error = result.error
    except Exception as exc:  # noqa: BLE001 - 背景例外必須回到頁面與收件匣
        error = f"背景執行發生未預期錯誤：{exc}"
    _finish(kind, brand_id, started_at, error)


def _run_ga4_backfill(brand_id: str, actor: str) -> None:
    kind = "ga4_backfill"
    started_at = _state(kind, brand_id).get("started_at", datetime.now(UTC).isoformat())
    try:
        until = datetime.now(UTC).date().isoformat()
        since = ads_sync.months_before(until, BACKFILL_MONTHS)
        result = ga4_sync.sync_brand(web.conn, brand_id, actor, since=since, until=until)
        error = result.error
    except Exception as exc:  # noqa: BLE001 - 背景例外必須回到頁面與收件匣
        error = f"背景執行發生未預期錯誤：{exc}"
    _finish(kind, brand_id, started_at, error)


def _run_ga4_sync(brand_id: str, actor: str) -> None:
    kind = "ga4_sync"
    started_at = _state(kind, brand_id).get("started_at", datetime.now(UTC).isoformat())
    try:
        result = ga4_sync.sync_brand(web.conn, brand_id, actor)
        error = result.error
    except Exception as exc:  # noqa: BLE001 - 背景例外必須回到頁面與收件匣
        error = f"背景執行發生未預期錯誤：{exc}"
    _finish(kind, brand_id, started_at, error)


def _start(kind: str, brand_id: str, actor: str, target: Callable[[str, str], None]) -> dict:
    if _state(kind, brand_id).get("status") == "running":
        raise HTTPException(status_code=400, detail="這個品牌的回填正在進行中。")
    started_at = datetime.now(UTC).isoformat()
    _jobs.start(
        _key(kind, brand_id),
        {"status": "running", "stage": _JOB_DETAILS[kind]["stage"], "started_at": started_at,
         "brand_id": brand_id, "kind": kind},
        target,
        (brand_id, actor),
        idempotent=True,
    )
    return {"ok": True}


@router.get("/api/campaigns/brands/{brand_id}/data-onboarding")
async def onboarding_get(brand_id: str, request: Request):
    try:
        require_brand(brand_id, require_actor(request))
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    checklist = data_onboarding.build_checklist(web.conn, brand_id)
    maturity = data_onboarding.maturity_report(web.conn, brand_id)
    return {
        "data": {
            "checklist": checklist,
            "progress": data_onboarding.completion(checklist),
            "maturity": {"rows": maturity, "all_met": all(row["met"] for row in maturity)},
            "jobs": {kind: _job_shape(kind, brand_id) for kind in _JOB_DETAILS},
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/api/campaigns/brands/{brand_id}/backfill/meta")
async def meta_backfill(request: Request, brand_id: str):
    actor = require_actor(request)
    try:
        require_brand(brand_id, actor)
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    if not ads_sync.is_configured(web.conn, org_id=actor.org_id):
        raise HTTPException(status_code=400, detail="還沒連上 Meta，先去設定頁連線。")
    result = _start("meta_backfill", brand_id, str(actor.user_id), _run_meta_backfill)
    return {**result, "message": "開始回填近 12 個月的 Meta 成效，好了會通知你。"}


@router.post("/api/campaigns/brands/{brand_id}/backfill/ga4")
async def ga4_backfill(request: Request, brand_id: str):
    actor = require_actor(request)
    try:
        require_brand(brand_id, actor)
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    if not ga4_sync.is_configured(web.conn, org_id=actor.org_id):
        raise HTTPException(status_code=400, detail="還沒連上 GA4，先去設定頁連線。")
    result = _start("ga4_backfill", brand_id, str(actor.user_id), _run_ga4_backfill)
    return {**result, "message": "開始回填近 12 個月的 GA4 資料，好了會通知你。"}


@router.post("/api/campaigns/brands/{brand_id}/sync/ga4")
async def ga4_sync_now(request: Request, brand_id: str):
    actor = require_actor(request)
    try:
        require_brand(brand_id, actor)
    except NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    if not ga4_sync.is_configured(web.conn, org_id=actor.org_id):
        raise HTTPException(status_code=400, detail="還沒連上 GA4，先去設定頁連線。")
    result = _start("ga4_sync", brand_id, str(actor.user_id), _run_ga4_sync)
    return {**result, "message": "開始同步 GA4，好了會通知你。"}
