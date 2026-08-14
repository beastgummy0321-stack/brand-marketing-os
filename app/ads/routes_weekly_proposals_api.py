# -*- coding: utf-8 -*-
"""週提案 JSON API：舊檔期端點與 T1 品牌層行動卡端點。"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import reading as ads_reading
from app.ads import routes as ads_routes
from app.ads import weekly_reports
from app.ads import weekly_proposals
from app.ads.routes_common import _require_cycle
from app.core import interrupts as core_interrupts
from app.core.db import new_id

router = APIRouter()

_REJUDGE_STAGES = [("weekly_reading", "判讀本週資料")]


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(_envelope({"error": message}), status_code=status_code)


def _current_cycle(brand_id: str):
    return weekly_proposals.current_cycle(main_mod.conn, brand_id)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _brand_view(brand_id: str, cycle_id: str) -> dict:
    result = weekly_proposals.view(main_mod.conn, brand_id, cycle_id)
    return {"cycle_id": cycle_id, **result}


@router.get("/api/campaigns/brands/{brand_id}/weekly/report")
async def weekly_report_get(brand_id: str):
    main_mod.require_brand(brand_id)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _envelope({"status": "empty"})
    report = weekly_reports.assemble(main_mod.conn, brand_id, cycle["id"], today=datetime.now().date().isoformat())
    if report is None:
        return _envelope({"status": "incomplete"})
    return _envelope({"status": "ready", **report})


@router.get("/api/campaigns/{brand_id}/{cycle_id}/weekly-proposals")
async def weekly_proposals_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    weekly_proposals.generate(main_mod.conn, brand_id, cycle_id)
    return _envelope(weekly_proposals.view(main_mod.conn, brand_id, cycle_id))


@router.post("/api/campaigns/{brand_id}/{cycle_id}/weekly-proposals/approve")
async def weekly_proposals_approve(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    actor = main_mod.require_actor(request)
    try:
        result = weekly_proposals.approve(main_mod.conn, brand_id, cycle_id, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return _envelope(result)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/weekly-proposals/{recommendation_id}/complete")
async def weekly_proposal_complete(
        request: Request, brand_id: str, cycle_id: str, recommendation_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    actor = main_mod.require_actor(request)
    try:
        result = weekly_proposals.complete(
            main_mod.conn, brand_id, cycle_id, recommendation_id, actor=actor)
    except ValueError as exc:
        return _error(400, str(exc))
    return _envelope(result)


# ---------------------------------------------------------------------------
# T1 批次 A：駕駛艙品牌層週提案與背景重判
# ---------------------------------------------------------------------------

@router.get("/api/campaigns/brands/{brand_id}/weekly/proposals")
async def weekly_action_proposals_get(brand_id: str):
    main_mod.require_brand(brand_id)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _envelope({"cycle_id": None, "proposals": [], "execution_checklist": []})
    return _envelope(_brand_view(brand_id, cycle["id"]))


@router.post("/api/campaigns/brands/{brand_id}/weekly/proposals/{recommendation_id}/approve")
async def weekly_action_proposal_approve(
        request: Request, brand_id: str, recommendation_id: str):
    main_mod.require_brand(brand_id)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _error(400, "目前沒有可判讀的檔期")
    actor = main_mod.require_actor(request)
    body = await _json_body(request)
    try:
        approved = weekly_proposals.approve_card(
            main_mod.conn,
            brand_id,
            cycle["id"],
            recommendation_id,
            actor=actor,
            confirmed_amount=body.get("confirmed_amount"),
        )
    except ValueError as exc:
        return _error(400, str(exc))
    result = _brand_view(brand_id, cycle["id"])
    result["approved"] = approved
    return _envelope(result)


@router.post("/api/campaigns/brands/{brand_id}/weekly/proposals/{recommendation_id}/skip")
async def weekly_action_proposal_skip(
        request: Request, brand_id: str, recommendation_id: str):
    main_mod.require_brand(brand_id)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _error(400, "目前沒有可判讀的檔期")
    actor = main_mod.require_actor(request)
    try:
        weekly_proposals.skip(
            main_mod.conn, brand_id, cycle["id"], recommendation_id, actor=actor,
        )
    except ValueError as exc:
        return _error(400, str(exc))
    result = _brand_view(brand_id, cycle["id"])
    result["skipped_id"] = recommendation_id
    return _envelope(result)


@router.post("/api/campaigns/brands/{brand_id}/weekly/proposals/approve-all")
async def weekly_action_proposals_approve_all(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _error(400, "目前沒有可判讀的檔期")
    actor = main_mod.require_actor(request)
    try:
        result = weekly_proposals.approve(
            main_mod.conn, brand_id, cycle["id"], actor=actor,
        )
    except ValueError as exc:
        return _error(400, str(exc))
    return _envelope({"cycle_id": cycle["id"], **result})


def _queue_rejudge_notice(brand_id: str, cycle_id: str, *, ok: bool) -> None:
    core_interrupts.enqueue(
        main_mod.conn,
        category="weekly_rejudge_done",
        dedupe_key=f"weekly_rejudge_done:{new_id('run')}",
        message="本週判讀完成，回駕駛艙看看。" if ok else "本週判讀未完成，回駕駛艙看看。",
        brand_id=brand_id,
        campaign_cycle_id=cycle_id,
        action_url=f"/app/brands/{brand_id}",
    )
    main_mod.conn.commit()


@router.post("/api/campaigns/brands/{brand_id}/weekly/rejudge")
async def weekly_rejudge_start(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    cycle = _current_cycle(brand_id)
    if cycle is None:
        return _error(400, "目前沒有可判讀的檔期")
    cycle_id = cycle["id"]
    key = ads_routes._progress_key("weekly_rejudge", brand_id, "_")

    def work(_on_stage):
        try:
            ok, err = ads_reading.run(
                main_mod.conn, brand_id, cycle_id, actor=actor,
            )
            if ok:
                weekly_proposals.generate(
                    main_mod.conn, brand_id, cycle_id, enqueue_ready=False,
                )
        except Exception:
            _queue_rejudge_notice(brand_id, cycle_id, ok=False)
            raise
        _queue_rejudge_notice(brand_id, cycle_id, ok=ok)
        return ok, err

    ads_routes._progress_start(key, _REJUDGE_STAGES, work)
    return _envelope({"status": "running"})


@router.get("/api/campaigns/brands/{brand_id}/weekly/rejudge/status")
async def weekly_rejudge_status(brand_id: str):
    main_mod.require_brand(brand_id)
    key = ads_routes._progress_key("weekly_rejudge", brand_id, "_")
    entry = ads_routes._progress_state.get(key)
    if entry is None:
        return _envelope({"status": "done"})
    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(key)
            return _envelope({"status": "failed", "message": "判讀逾時了，可以再試一次。"})
        return _envelope({"status": "running"})

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(key)
    if outcome_kind == "error":
        return _envelope({"status": "failed", "message": payload})
    ok, err = payload
    if not ok:
        return _envelope({"status": "failed", "message": err})
    return _envelope({"status": "done"})
