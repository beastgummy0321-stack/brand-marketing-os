"""app/workbench/routes.py — /api/workbench/*. Private: only app/workbench/__init__.py
imports this (container contract §1); it is only ever loaded via `register()`.

F02-I03 (ARCHITECTURE.md §5.1-§5.5, `.work/features/F02.md` "API surface"): the brief-shaped
endpoints (`/briefs`, `/briefs/{id}/outputs/{output_id}/adopt`, ...) are **replaced**, not kept
in parallel — their only consumer was the retired `.workspace-split` page. This file now
speaks 任務包 (pack) → 素材組 (set) → 產物 (product) → 版本 (version).

F07-I08 adds `/brands/{brand_id}/visual-spec` (ARCHITECTURE.md §5.9's 品牌事實 negatives
warning): same actor/brand guard as every other brand route, no set/pack involved.

Shape (container contract §7, unchanged): every handler is `require_actor` -> `require_brand`
-> one repository function -> wrap. Nothing here decides anything:
every `ValueError` a repository function raises is looked up in this file's small per-route
tables and turned into `web.ApiError` — that lookup is translation of an already-made decision,
not a new one (the decision happened in `repository.py`).
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.workbench import free_parse, identity, repository, visual

router = APIRouter(prefix="/api/workbench")

PACK_UNKNOWN_MESSAGE = "找不到這個任務包。"
SET_UNKNOWN_MESSAGE = "找不到這個素材組。"
_PACK_UNKNOWN_ERRORS = {"pack_unknown": (404, PACK_UNKNOWN_MESSAGE)}


def _error(exc: ValueError, table: dict) -> web.ApiError:
    """把 repository 丟出來的 `ValueError(code)` 對照成這個端點自己的錯誤表——同一個
    code 在不同端點是不同的 HTTP 狀態碼，所以每支端點自己一張表，不共用一張全域表
    （沿用票 03 原本的規則，見 git 歷史那份檔頭）。"""
    code = str(exc)
    status, message = table.get(code, (400, code))
    return web.ApiError(status, code, message)


@router.get("/brands/{brand_id}/visual-spec")
def get_visual_spec(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    spec_text = identity.brand_spec_text(web.conn, brand_id)
    return {"warnings": visual.spec_warnings(brand_id, spec_text)}


# -- 任務包（PackCard／PackDetail） -----------------------------------------------------

_LIST_PACKS_ERRORS = {
    "status_unknown": (400, "status 參數只能是 all／pending／running／awaiting_approval／done。"),
    "sort_unknown": (400, "sort 參數只能是 updated／created／progress。"),
}


@router.get("/brands/{brand_id}/packs")
def list_packs(request: Request, brand_id: str, status: str = "all", q: str | None = None,
                sort: str = "updated"):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        packs = repository.list_packs(web.conn, actor.org_id, brand_id, status=status, q=q,
                                       sort=sort)
    except ValueError as exc:
        raise _error(exc, _LIST_PACKS_ERRORS) from exc
    return {"packs": packs}


@router.get("/brands/{brand_id}/packs/{pack_id}")
def get_pack(request: Request, brand_id: str, pack_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    pack = repository.pack_detail(web.conn, actor.org_id, brand_id, pack_id)
    if pack is None:
        raise web.ApiError(404, "pack_unknown", PACK_UNKNOWN_MESSAGE)
    return {"pack": pack}


class NewFreePackRequest(BaseModel):
    # 租戶界線先於欄位驗證（既有慣例）：全部給預設值，真正的驗證在
    # `repository.create_free_pack()`／`submit_pack()`。`source_kind` 不是這個請求的欄位
    # ——伺服器端強制 `"free_job"`（票面「自由創作 only」）。
    name: str | None = None
    free_text: str | None = None
    product_id: str | None = None
    style_key: str | None = None
    sets: list[dict] = []
    summary: dict = {}
    context: dict = {}


_CREATE_FREE_PACK_ERRORS = {
    "sets_unknown": (400, "請至少加入一個素材組。"),
    "required_outputs_unknown": (400, "每個素材組至少要選一種要生成的內容。"),
    "part_retired": (400, "free 已經退休，自由創作不能用它當必要產出。"),
    "parts_unknown": (400, "必要產出只能是文案／圖片／腳本。"),
    "count_out_of_range": (400, "需要選定的版本數必須是至少 1 的整數。"),
}


@router.post("/brands/{brand_id}/packs", status_code=201)
def create_free_pack(request: Request, brand_id: str, body: NewFreePackRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        pack = repository.create_free_pack(web.conn, actor.org_id, brand_id, body.model_dump())
    except ValueError as exc:
        raise _error(exc, _CREATE_FREE_PACK_ERRORS) from exc
    return {"pack": pack}


class CompletionRequest(BaseModel):
    # 租戶界線先於欄位驗證（既有慣例）：全部給預設值，真正的驗證在下面的 handler／
    # `repository.set_pack_completion()`。
    key: str | None = None
    checked: bool | None = None


_COMPLETION_ERRORS = {
    "key_unknown": (400, "不認得這個完成條件。"),
    "pack_unknown": (404, PACK_UNKNOWN_MESSAGE),
}


@router.post("/brands/{brand_id}/packs/{pack_id}/completion")
def set_pack_completion(request: Request, brand_id: str, pack_id: str, body: CompletionRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    if body.checked is None:
        raise web.ApiError(400, "checked_invalid", "請指定要勾選或取消。")
    try:
        pack = repository.set_pack_completion(
            web.conn, actor.org_id, brand_id, pack_id, body.key or "", body.checked,
        )
    except ValueError as exc:
        raise _error(exc, _COMPLETION_ERRORS) from exc
    return {"pack": pack}


_APPROVE_ERRORS = {
    "pack_unknown": (404, PACK_UNKNOWN_MESSAGE),
    "completion_incomplete": (409, "還有完成條件沒有滿足。"),
}


@router.post("/brands/{brand_id}/packs/{pack_id}/approve")
def approve_pack(request: Request, brand_id: str, pack_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        pack = repository.approve_pack(web.conn, actor.org_id, brand_id, pack_id)
    except ValueError as exc:
        raise _error(exc, _APPROVE_ERRORS) from exc
    return {"pack": pack}


@router.post("/brands/{brand_id}/packs/{pack_id}/close")
def close_pack(request: Request, brand_id: str, pack_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        pack = repository.close_pack(web.conn, actor.org_id, brand_id, pack_id)
    except ValueError as exc:
        raise _error(exc, _PACK_UNKNOWN_ERRORS) from exc
    return {"pack": pack}


class ParseFreeTextRequest(BaseModel):
    # 租戶界線先於欄位驗證（既有慣例）：全部給預設值，真正的驗證在下面的 handler。
    free_text: str | None = None
    defaults: dict = {}


@router.post("/brands/{brand_id}/parse")
def parse_free_text(request: Request, brand_id: str, body: ParseFreeTextRequest):
    """F02-I06：自由創作「AI 解析結果」——使用者按「建立自由工作」時打的那**一次**
    `gateway.run_task`。永不 500：失敗、逾時、非 JSON 或形狀不合都在 `free_parse.parse()`
    內部回退成 `parsed: false` + 使用者填的 `defaults`，這裡沒有例外要接。"""
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    free_text = body.free_text or ""
    if not free_text or len(free_text) > 1000:
        raise web.ApiError(400, "free_text_invalid", "請輸入 1～1000 字的描述。")
    parsed = free_parse.parse(
        web.conn, brand_id=brand_id, free_text=free_text, defaults=body.defaults,
    )
    return {"parse": parsed}


# -- 素材組（SetDetail）／產物／版本 -----------------------------------------------------

@router.get("/brands/{brand_id}/sets/{set_id}")
def get_set(request: Request, brand_id: str, set_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    detail = repository.set_detail(web.conn, actor.org_id, brand_id, set_id)
    if detail is None:
        raise web.ApiError(404, "set_unknown", SET_UNKNOWN_MESSAGE)
    return {"set": detail}


class RunProductRequest(BaseModel):
    count: int | None = None


_RUN_PRODUCT_ERRORS = {
    "brief_unknown": (404, SET_UNKNOWN_MESSAGE),
    "part_unknown": (400, "這個產物類型不適用於這個素材組。"),
    "count_out_of_range": (400, "版本張數超出範圍。"),
    "brief_closed": (409, "這個素材組已經關閉。"),
    "round_running": (409, "上一輪還在跑，請等它跑完再按。"),
    "pack_approved": (409, repository.PACK_APPROVED_MESSAGE),
}


@router.post("/brands/{brand_id}/sets/{set_id}/products/{part}/run")
def run_product(request: Request, brand_id: str, set_id: str, part: str,
                 body: RunProductRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        result = repository.run_product(
            web.conn, actor.org_id, brand_id, set_id, part, count=body.count,
        )
    except ValueError as exc:
        raise _error(exc, _RUN_PRODUCT_ERRORS) from exc
    return {"set": result}


_SELECT_ERRORS = {
    # `output_unknown` now also covers a `version_id` that exists but belongs to a different
    # `set_id` in the URL — `select_version_for_set()`/`deselect_version_for_set()` check
    # containment before any write (planner review, 2026-09-12).
    "output_unknown": (404, "找不到這個版本。"),
    "brief_closed": (409, "這個素材組已經關閉。"),
    "pack_approved": (409, repository.PACK_APPROVED_MESSAGE),
}


@router.post("/brands/{brand_id}/sets/{set_id}/versions/{version_id}/select")
def select_version(request: Request, brand_id: str, set_id: str, version_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        detail = repository.select_version_for_set(
            web.conn, actor.org_id, brand_id, set_id, version_id,
        )
    except ValueError as exc:
        raise _error(exc, _SELECT_ERRORS) from exc
    return {"set": detail}


@router.delete("/brands/{brand_id}/sets/{set_id}/versions/{version_id}/select")
def deselect_version(request: Request, brand_id: str, set_id: str, version_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    try:
        detail = repository.deselect_version_for_set(
            web.conn, actor.org_id, brand_id, set_id, version_id,
        )
    except ValueError as exc:
        raise _error(exc, _SELECT_ERRORS) from exc
    return {"set": detail}
