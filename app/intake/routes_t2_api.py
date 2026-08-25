# -*- coding: utf-8 -*-
"""T2 建檔精靈後端 API；由 routes_api.router 掛載，不碰 app/main.py。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.brand_intelligence import personas
from app.intake import ai, persona_generation
from app.intake import repository as ir
from app.intake import state, truth_card
from app.shared import web
from app.shared.web import JSONResponse, require_brand


router = APIRouter()
CONFIRMED_BY = "使用者"


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _body(request: Request) -> dict:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


@router.post("/api/intake/brands/{brand_id}/scan/products/retry")
async def photo_product_retry(request: Request, brand_id: str):
    require_brand(brand_id)
    draft = state.require_draft(brand_id)
    source_photo_token = str((await _body(request)).get("source_photo_token") or "").strip()
    if not source_photo_token:
        return _error(400, "缺少照片識別碼，請重新整理後再試。")
    try:
        card = ai.retry_photo_product(web.conn, draft, source_photo_token)
    except ValueError as exc:
        return _error(404, str(exc))
    return {"card": card}


@router.post("/api/intake/brands/{brand_id}/scan/products/skip")
async def photo_product_skip(request: Request, brand_id: str):
    require_brand(brand_id)
    draft = state.require_draft(brand_id)
    source_photo_token = str((await _body(request)).get("source_photo_token") or "").strip()
    if not source_photo_token:
        return _error(400, "缺少照片識別碼，請重新整理後再試。")
    card = next((item for item in draft.get("product_card_drafts") or []
                 if item.get("source_photo_token") == source_photo_token), None)
    if card is None:
        return _error(404, "找不到這張照片產品卡。")
    card["status"] = "skipped"
    state.save(draft, conn=web.conn)
    return Response(status_code=204)


@router.get("/api/intake/brands/{brand_id}/truth-card")
async def truth_card_get(brand_id: str):
    require_brand(brand_id)
    draft = state.require_draft_or_just_completed(brand_id)
    return _envelope(truth_card.split_items(
        ir.list_truth_card_items(web.conn, brand_id, draft["id"]),
    ))


@router.post("/api/intake/brands/{brand_id}/truth-card/items/{i}/move")
async def truth_card_item_move(request: Request, brand_id: str, i: int):
    require_brand(brand_id)
    draft = state.require_draft_or_just_completed(brand_id)
    item = next((row for row in ir.list_truth_card_items(web.conn, brand_id, draft["id"])
                 if row["i"] == i), None)
    if item is None:
        return _error(404, "找不到這一筆。")
    target = str((await _body(request)).get("target") or "").strip()
    if target not in ("accepted", "needs_confirmation", "forbidden"):
        return _error(400, "搬格目標不正確。")
    if target == "accepted" and item["outcome"] == "pending" and truth_card.answer_kind(item):
        return _error(400, "這條請在卡上作答")
    current = truth_card.bucket_name(item)
    if current == target and not (target == "accepted" and item["outcome"] == "pending"):
        return _error(400, "這條已經在這一格。")
    try:
        ir.move_truth_card_item(
            web.conn, brand_id, item["id"], processed_by=CONFIRMED_BY, target=target,
        )
    except ValueError as exc:
        return _error(400, str(exc))
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/truth-card/confirm")
async def truth_card_confirm(request: Request, brand_id: str):
    require_brand(brand_id)
    draft = state.require_draft_or_just_completed(brand_id)
    pending = ir.list_pending_items(web.conn, brand_id, draft["id"])
    body = await _body(request)
    answers = truth_card.answers_by_item(body.get("answers"))

    missing = []
    normalized = {}
    for item in pending:
        kind = truth_card.answer_kind(item)
        if kind == "price":
            normalized[item["id"]] = truth_card.price_answer(answers.get(item["id"]))
        elif kind == "claim_permission":
            normalized[item["id"]] = truth_card.claim_answer(answers.get(item["id"]))
        if kind and normalized[item["id"]] is None:
            missing.append(item["title"])
    if missing:
        return _error(400, "還有這些內容等你回答：" + "、".join(missing) + "。")
    # 交接包在品牌沒產品時會叫外部 AI 只填「整個品牌」；產品事實掛在整個品牌落檔會炸
    # ValueError（repository._ensure_product），所以在任何一列寫入前先擋成 400。
    unscoped = [item["title"] for item in pending
                if item["kind"] == "產品事實" and item["scope"] == "整個品牌"]
    if unscoped:
        return _error(400, "這些產品事實要掛在一個真正的產品上，不能是「整個品牌」，請按「改」"
                      "把適用範圍填成產品名稱：" + "、".join(unscoped) + "。")

    for item in pending:
        kind = truth_card.answer_kind(item)
        edits = None
        if kind == "price":
            edits = {"content": normalized[item["id"]]}
        elif kind == "claim_permission":
            edits = {"category": normalized[item["id"]]}
        ir.resolve_item(
            web.conn, brand_id, item["id"], "confirmed",
            processed_by=CONFIRMED_BY, edits=edits,
        )

    if not ir.list_pending_items(web.conn, brand_id, draft["id"]):
        state.complete_draft(draft)
        persona_generation.start_generation(web.conn, brand_id)
    return Response(status_code=204)


@router.get("/api/intake/brands/{brand_id}/personas")
async def persona_list(brand_id: str):
    require_brand(brand_id)
    return _envelope({
        "personas": personas.list_personas(web.conn, brand_id),
        "generation": persona_generation.generation_state(brand_id),
    })


@router.put("/api/intake/brands/{brand_id}/personas/{persona_id}")
async def persona_update(request: Request, brand_id: str, persona_id: str):
    require_brand(brand_id)
    try:
        personas.update_persona(web.conn, brand_id, persona_id, await _body(request), actor=CONFIRMED_BY)
    except LookupError as exc:
        return _error(404, str(exc))
    except ValueError as exc:
        return _error(400, str(exc))
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/personas/regenerate")
async def persona_regenerate(brand_id: str):
    require_brand(brand_id)
    persona_generation.start_generation(web.conn, brand_id)
    return JSONResponse(
        {"generation": persona_generation.generation_state(brand_id)}, status_code=202,
    )
