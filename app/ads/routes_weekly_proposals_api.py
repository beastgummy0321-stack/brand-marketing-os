# -*- coding: utf-8 -*-
"""週提案 JSON API：卡片、一鍵核可與保守檔執行清單。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import weekly_proposals
from app.ads.routes_common import _require_cycle

router = APIRouter()


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


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
