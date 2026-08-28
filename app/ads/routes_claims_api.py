"""待認領廣告的 JSON API（票 T5-01）。

對外進入點：本檔的 ``router``。
輸入輸出形狀：GET 回 ``{data: {items: list[dict]}, generated_at: str}``；兩個 POST
回 ``{ok: bool, message: str}``，失敗回 ``{detail: str}``。
誰依賴它：只有 ``app/main.py`` 的路由註冊。
不碰：不改 ``app.ads.sync`` 的認領查詢或動作，也不依賴前端或 Jinja 路由。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import sync as ads_sync
from app.shared.web import JSONResponse

router = APIRouter()


def _envelope(data: dict) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _pending_item(row: dict) -> dict:
    """只送出待認領畫面實際會用到、且 list_pending_claims 已回傳的欄位。"""
    return {
        "id": row["id"],
        "campaign_name": row["campaign_name"],
        "platform": row["platform"],
        "first_seen_at": row["first_seen_at"],
        "is_suggested": row["is_suggested"],
    }


@router.get("/api/campaigns/brands/{brand_id}/claims")
async def list_claims(brand_id: str):
    main_mod.require_brand(brand_id)
    pending = ads_sync.list_pending_claims(main_mod.conn, brand_id)
    return _envelope({"items": [_pending_item(row) for row in pending]})


@router.post("/api/campaigns/brands/{brand_id}/claims/{discovered_id}/claim")
async def claim_campaign(request: Request, brand_id: str, discovered_id: str):
    main_mod.require_brand(brand_id)
    try:
        row = ads_sync.claim(main_mod.conn, brand_id, discovered_id, main_mod.require_actor(request))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"ok": True, "message": f"「{row['campaign_name']}」記成這個品牌的了，它的成效數字會算進來。"}


@router.post("/api/campaigns/brands/{brand_id}/claims/{discovered_id}/ignore")
async def ignore_campaign(request: Request, brand_id: str, discovered_id: str):
    main_mod.require_brand(brand_id)
    try:
        ads_sync.ignore(main_mod.conn, brand_id, discovered_id, main_mod.require_actor(request))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"ok": True, "message": "好，這個活動不算這個品牌的。"}
