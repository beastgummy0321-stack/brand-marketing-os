"""Persona API (人物誌; the library's `PersonaSection` reads it); included by routes_api.router,
does not touch app/main.py. F42-I14 removed the truth-card and photo-product-card routes that
used to live here."""


from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.brand_intelligence import personas
from app.core.db import now_iso
from app.intake import persona_generation
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()
CONFIRMED_BY = "使用者"


def _envelope(data) -> dict:
    return {"data": data, "generated_at": now_iso()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _body(request: Request) -> dict:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


@router.get("/api/intake/brands/{brand_id}/personas")
def persona_list(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _envelope({
        "personas": personas.list_personas(web.conn, brand_id),
        "generation": persona_generation.generation_state(brand_id),
    })


@router.put("/api/intake/brands/{brand_id}/personas/{persona_id}")
async def persona_update(request: Request, brand_id: str, persona_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    try:
        personas.update_persona(web.conn, brand_id, persona_id, await _body(request), actor=CONFIRMED_BY)
    except LookupError as exc:
        return _error(404, str(exc))
    except ValueError as exc:
        return _error(400, str(exc))
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/personas/regenerate")
def persona_regenerate(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    persona_generation.start_generation(actor.org_id, brand_id)
    return JSONResponse(
        {"generation": persona_generation.generation_state(brand_id)}, status_code=202,
    )
