"""app/intake/routes_tools_api.py — 精靈第 4 步「接工具」JSON API（F05-I08）。

不新做 Meta 的東西：權杖與綁定沿用既有的 `app/meta/routes.py`（POST /api/meta/token、
GET /api/meta/accounts、POST /api/meta/brands/{b}/accounts/{a}），前端直接打
`frontend/src/lib/metaApi.ts`。本檔只加兩支這一步自己的端點：讀「目前狀態」與寫「成效目標」。

成效目標值域是既有的 `app.brand_intelligence.repository.CONVERSION_GOALS`
＋`app.core.vocab.CONVERSION_GOAL_LABELS`（兩份既有真相，不開第三份）；寫入沿用
`bi_repo.set_brand_switches`——那支一次寫 `market_region`＋`conversion_goal` 兩欄，
所以這裡要先把品牌目前的 `market_region` 讀出來原樣傳回去，否則會被洗成 NULL。

對外進入點：本檔的 `router`，由 `app/intake/routes_api.py` 檔尾比照 `t2_router` 併入。
"""

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn
from app.core.vocab import CONVERSION_GOAL_LABELS
from app.intake import state
from app.meta import repository as meta_repo
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/api/intake/brands/{brand_id}/tools")
def tools_get(request: Request, brand_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    bound_account_ids = meta_repo.bound_account_ids_for_brand(web.conn, actor.org_id, brand_id)
    goal_options = [
        {"key": key, "label": CONVERSION_GOAL_LABELS.get(key, key)}
        for key in bi_repo.CONVERSION_GOALS
    ]
    return _envelope({
        "conversion_goal": brand["conversion_goal"],
        "conversion_goal_options": goal_options,
        "bound_account_ids": bound_account_ids,
    })


@router.post("/api/intake/brands/{brand_id}/conversion-goal")
async def conversion_goal_post(request: Request, brand_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    body = await _json_body(request)
    conversion_goal = str(body.get("conversion_goal") or "")
    if conversion_goal not in bi_repo.CONVERSION_GOALS:
        return _error(400, "請選擇有效的成效目標。")
    conn = cast(Conn, web.conn)
    bi_repo.set_brand_switches(
        conn, brand_id,
        market_region=brand["market_region"], conversion_goal=conversion_goal,
        actor=str(actor.user_id),
    )
    # F42-I04: the tools step is step 6; a completed brand (no open draft) just saves the goal.
    draft = state.get_draft(brand_id, conn=conn)
    if draft is not None and draft["step"] < 6:
        state.touch(draft, f"/brands/{brand_id}/intake/tools", 6, conn=conn)
    return Response(status_code=204)
