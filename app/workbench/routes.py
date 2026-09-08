"""app/workbench/routes.py — /api/workbench/*. Private: only app/workbench/__init__.py
imports this (container contract §1); it is only ever loaded via `register()`. Ticket
workbench/03 (docs/contracts/workbench.md "Routes" / "Error shapes").

Shape (container contract §7, this ticket's own quote of it): every handler is
`require_actor` -> (`require_brand`, every route but `/styles`) -> one repository function ->
wrap. Nothing here decides anything: every `ValueError` a repository function raises is looked
up in this file's small per-route tables and turned into `web.ApiError` — that lookup is
translation of an already-made decision, not a new one (the decision happened in
`repository.py`). A handler that also needs the refreshed `BriefDetail` for its reply calls
`repository.brief_detail()` a second time after the one mutating call — that second call is the
"wrap" step assembling the JSON envelope, the same shape `app/schedule/routes.py`'s `_run_*`
helpers use when they finish with `state._brand_response(...)`.
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

import app.shared.web as web
from app.workbench import repository

router = APIRouter(prefix="/api/workbench")

BRIEF_UNKNOWN_MESSAGE = "找不到這張工單。"
_BRIEF_UNKNOWN_ERRORS = {"brief_unknown": (404, BRIEF_UNKNOWN_MESSAGE)}


def _error(exc: ValueError, table: dict) -> web.ApiError:
    """把 repository 丟出來的 `ValueError(code)` 對照成這個端點自己的錯誤表——同一個
    code 在不同端點是不同的 HTTP 狀態碼（例如 `on_image_texts_required` 送出時是 400、
    重跑時是 409，見票面「Literal shapes」上面那張表），所以每支端點自己一張表，不共用
    一張全域表。"""
    code = str(exc)
    status, message = table.get(code, (400, code))
    return web.ApiError(status, code, message)


@router.get("/styles")
def list_styles(request: Request):
    """唯一不吃 `brand_id`、不呼叫 `require_brand` 的端點（票面「What」§1 開頭那句）——
    仍然要登入（`require_actor`），只是不用挑品牌。"""
    web.require_actor(request)
    return {"styles": repository.STYLES}


class NewBriefRequest(BaseModel):
    # 租戶界線先於欄位驗證（`app/schedule/routes.py` 既有慣例，見該檔 `PlanRequest` 檔頭）：
    # 全部給預設值，真正的驗證在 `repository.create_brief()`／`submit_brief()`。
    kind: str = ""
    product_id: str | None = None
    coordinates: dict[str, str | None] | None = None
    visual_tone: str | None = None
    visual_concept: str | None = None
    style_key: str = "ugc"
    request: dict = {}


_CREATE_BRIEF_ERRORS = {
    "kind_unknown": (400, "這個類型不能用這支端點建立。"),
    "style_unknown": (400, "找不到這個風格。"),
    "product_unknown": (404, "找不到這個產品。"),
    "count_out_of_range": (400, "圖片提示詞張數需介於 1 到 30 之間。"),
    "on_image_texts_required": (400, "請填圖上文字（1 到 5 則，每則不超過 27 字）。"),
}


@router.post("/brands/{brand_id}/briefs", status_code=201)
def create_brief(request: Request, brand_id: str, body: NewBriefRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    brief = {
        "kind": body.kind, "source_kind": "manual", "source_ref": {},
        "product_id": body.product_id, "coordinates": body.coordinates,
        "visual_tone": body.visual_tone, "visual_concept": body.visual_concept,
        "style_key": body.style_key, "request": body.request,
    }
    try:
        brief_id = repository.create_brief(
            web.conn, actor.org_id, brand_id, brief, created_by=str(actor.user_id),
        )
    except ValueError as exc:
        raise _error(exc, _CREATE_BRIEF_ERRORS) from exc
    return {"brief": repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)}


_LIST_BRIEFS_ERRORS = {"status_unknown": (400, "status 參數只能是 active／closed／all。")}


@router.get("/brands/{brand_id}/briefs")
def list_briefs(request: Request, brand_id: str, status: str = "active"):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        briefs = repository.list_briefs(web.conn, actor.org_id, brand_id, status)
    except ValueError as exc:
        raise _error(exc, _LIST_BRIEFS_ERRORS) from exc
    return {"briefs": briefs}


@router.get("/brands/{brand_id}/briefs/{brief_id}")
def get_brief(request: Request, brand_id: str, brief_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    detail = repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)
    if detail is None:
        raise web.ApiError(404, "brief_unknown", BRIEF_UNKNOWN_MESSAGE)
    return {"brief": detail}


class RunPartRequest(BaseModel):
    count: int | None = None


_RUN_PART_ERRORS = {
    "brief_unknown": (404, BRIEF_UNKNOWN_MESSAGE),
    "part_unknown": (400, "這個 part 不適用於這張工單的類型。"),
    "count_out_of_range": (400, "圖片提示詞張數需介於 1 到 30 之間。"),
    "brief_closed": (409, "這張工單已經關閉。"),
    "round_running": (409, "上一輪還在跑，請等它跑完再按。"),
    "on_image_texts_required": (409, "沒有圖上文字可用：先產文案，或在工單填圖上文字。"),
}


@router.post("/brands/{brand_id}/briefs/{brief_id}/parts/{part}/run")
def run_part(request: Request, brand_id: str, brief_id: str, part: str, body: RunPartRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        repository.run_part(web.conn, actor.org_id, brand_id, brief_id, part, count=body.count)
    except ValueError as exc:
        raise _error(exc, _RUN_PART_ERRORS) from exc
    return {"brief": repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)}


_ADOPT_ERRORS = {
    "brief_unknown": (404, BRIEF_UNKNOWN_MESSAGE),
    "brief_closed": (409, "這張工單已經關閉。"),
    "output_unknown": (404, "找不到這個產出。"),
}


@router.post("/brands/{brand_id}/briefs/{brief_id}/outputs/{output_id}/adopt")
def adopt_output(request: Request, brand_id: str, brief_id: str, output_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        repository.adopt_output_for_brief(web.conn, actor.org_id, brand_id, brief_id, output_id)
    except ValueError as exc:
        raise _error(exc, _ADOPT_ERRORS) from exc
    return {"brief": repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)}


@router.post("/brands/{brand_id}/briefs/{brief_id}/close")
def close_brief(request: Request, brand_id: str, brief_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        repository.close_brief(web.conn, actor.org_id, brand_id, brief_id)
    except ValueError as exc:
        raise _error(exc, _BRIEF_UNKNOWN_ERRORS) from exc
    return {"brief": repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)}


@router.post("/brands/{brand_id}/briefs/{brief_id}/reopen")
def reopen_brief(request: Request, brand_id: str, brief_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        repository.reopen_brief(web.conn, actor.org_id, brand_id, brief_id)
    except ValueError as exc:
        raise _error(exc, _BRIEF_UNKNOWN_ERRORS) from exc
    return {"brief": repository.brief_detail(web.conn, actor.org_id, brand_id, brief_id)}


@router.delete("/brands/{brand_id}/briefs/{brief_id}")
def delete_brief(request: Request, brand_id: str, brief_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        repository.delete_brief(web.conn, actor.org_id, brand_id, brief_id)
    except ValueError as exc:
        raise _error(exc, _BRIEF_UNKNOWN_ERRORS) from exc
    return Response(status_code=204)
