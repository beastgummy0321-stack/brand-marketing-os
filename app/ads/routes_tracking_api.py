# -*- coding: utf-8 -*-
"""R5/R6 追蹤鏈兩支 JSON API；回應逐欄對齊 frontend/src/lib/warroomApi.ts。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import tracking
from app.ads.routes_common import _require_cycle

router = APIRouter()


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/api/campaigns/{brand_id}/{cycle_id}/tracking-chain")
async def tracking_chain_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return _envelope(tracking.tracking_chain(main_mod.conn, brand_id, cycle_id))


@router.post("/api/campaigns/{brand_id}/{cycle_id}/tracking-chain/mapping/confirm")
async def tracking_mapping_confirm(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    actor = main_mod.require_actor(request)
    try:
        tracking.confirm_suggested_mapping(main_mod.conn, brand_id, cycle_id, actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    tracking.run_post_sync_checks(main_mod.conn, brand_id)
    return JSONResponse(None, status_code=204)
