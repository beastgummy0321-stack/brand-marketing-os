# -*- coding: utf-8 -*-
"""T2 建檔精靈後端 API；由 routes_api.router 掛載，不碰 app/main.py。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.brand_intelligence import personas
from app.intake import persona_generation
from app.intake import repository as ir
from app.intake import state, truth_card
from app.shared import web
from app.shared.web import require_brand


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


@router.get("/api/intake/brands/{brand_id}/truth-card")
async def truth_card_get(brand_id: str):
    require_brand(brand_id)
    draft = state.require_draft_or_just_completed(brand_id)
    return _envelope(truth_card.split_items(ir.list_items(web.conn, brand_id, draft["id"])))


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


@router.post("/api/intake/brands/{brand_id}/personas/regenerate")
async def persona_regenerate(brand_id: str):
    require_brand(brand_id)
    persona_generation.start_generation(web.conn, brand_id)
    return JSONResponse(
        {"generation": persona_generation.generation_state(brand_id)}, status_code=202,
    )
