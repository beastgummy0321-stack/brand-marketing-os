"""app/dashboard/routes_pinned_views_api.py — 駕駛艙成效釘選區 JSON API（票 B4R-cockpit-pins
接線，契約 `.scratch/grill/GRILL-B4R-performance.md` 第一節）。獨立成檔（不併進
`routes.py`）：`routes.py` 檔頭明文「只讀、不寫入任何資料表」，本檔的 POST 端點會寫
`app_setting`，混進去會讓那句話變假話。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.dashboard import pinned_views
from app.shared.web import JSONResponse

router = APIRouter(prefix="/api/dashboard")


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _config(conn, brand_id: str) -> dict:
    return {"catalog": pinned_views.PINNED_VIEW_CATALOG, "pinned": pinned_views.get_pinned_views(conn, brand_id)}


@router.get("/brands/{brand_id}/pinned-views")
async def pinned_views_get(request: Request, brand_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    return _envelope(_config(main_mod.conn, brand_id))


@router.post("/brands/{brand_id}/pinned-views")
async def pinned_views_post(request: Request, brand_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    conn = main_mod.conn
    try:
        body = await request.json()
    except Exception:
        body = {}
    views = body.get("views") if isinstance(body, dict) else None
    valid_keys = {c["key"] for c in pinned_views.PINNED_VIEW_CATALOG}
    if not isinstance(views, list) or not all(isinstance(v, str) and v in valid_keys for v in views):
        return JSONResponse({"error": "釘選清單格式不對。"}, status_code=400)
    if len(views) > pinned_views.PINNED_VIEW_LIMIT:
        return JSONResponse(
            {"error": f"最多只能釘選 {pinned_views.PINNED_VIEW_LIMIT} 個視圖，先取消一個才能再選。"},
            status_code=400,
        )
    pinned_views.set_pinned_views(conn, brand_id, views)
    conn.commit()
    return _envelope(_config(conn, brand_id))


@router.get("/brands/{brand_id}/performance-view/{view_key}")
async def performance_view_get(request: Request, brand_id: str, view_key: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    valid_keys = {c["key"] for c in pinned_views.PINNED_VIEW_CATALOG}
    if view_key not in valid_keys:
        return JSONResponse({"error": "沒有這個視圖。"}, status_code=404)
    return _envelope(pinned_views.build_performance_view(main_mod.conn, brand_id, view_key))
