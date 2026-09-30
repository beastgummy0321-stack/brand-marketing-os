"""app/intake/routes_onboarding_api.py — brand onboarding JSON API (F42-I04).

The HTTP contract of the seven brand-onboarding screens (`#/b1`–`#/b7`), all under
`/api/intake/brands/{brand_id}/onboarding`. Logic lives in `app/intake/onboarding.py`; this file
only authenticates (`require_brand` tenant check on every route), parses the body and maps a
`ValueError` to 400 `{"error": 〈Chinese message〉}`. Reads are wrapped in the usual
`{data, generated_at}` envelope; PUTs return the step's fresh GET shape the same way.

Entry point: this file's `router`, included at the end of `app/intake/routes_api.py`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request

from app.core.db import Conn
from app.intake import onboarding
from app.meta import repository as meta_repo
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()

_BASE = "/api/intake/brands/{brand_id}/onboarding"


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


def _conn() -> Conn:
    return cast(Conn, web.conn)


def _read(request: Request, brand_id: str, reader: Callable[[Conn, str], dict]) -> dict:
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _envelope(reader(_conn(), brand_id))


async def _write(request: Request, brand_id: str, writer: Callable[..., dict]):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    try:
        data = writer(_conn(), brand_id, body, actor=str(actor.user_id))
    except ValueError as exc:
        return _error(400, str(exc))
    return _envelope(data)


@router.get(_BASE)
def onboarding_status(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.status)


@router.post(_BASE + "/complete")
def onboarding_complete(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.complete)


@router.get(_BASE + "/basics")
def basics_get(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.get_basics)


@router.put(_BASE + "/basics")
async def basics_put(request: Request, brand_id: str):
    return await _write(request, brand_id, onboarding.put_basics)


@router.get(_BASE + "/identity")
def identity_get(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.get_identity)


@router.put(_BASE + "/identity")
async def identity_put(request: Request, brand_id: str):
    return await _write(request, brand_id, onboarding.put_identity)


@router.get(_BASE + "/evidence")
def evidence_get(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.get_evidence)


@router.put(_BASE + "/evidence")
async def evidence_put(request: Request, brand_id: str):
    return await _write(request, brand_id, onboarding.put_evidence)


@router.get(_BASE + "/media")
def media_get(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.get_media)


@router.put(_BASE + "/media")
async def media_put(request: Request, brand_id: str):
    return await _write(request, brand_id, onboarding.put_media)


@router.get(_BASE + "/tools")
def tools_get(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    conn = _conn()
    names = []
    for account_id in meta_repo.bound_account_ids_for_brand(conn, actor.org_id, brand_id):
        account = meta_repo.get_account(conn, actor.org_id, account_id)
        if account is not None:
            names.append(account["name"] or account["account_id"])
    return _envelope(onboarding.get_tools(conn, brand_id, bound_account_names=names))
