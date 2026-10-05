"""app/intake/routes_onboarding_api.py — brand onboarding JSON API (F42-I04).

The HTTP contract of the seven brand-onboarding screens (`#/b1`–`#/b7`), all under
`/api/intake/brands/{brand_id}/onboarding`. Logic lives in `app/intake/onboarding.py`; this file
only authenticates (`require_brand` tenant check on every route), parses the body and maps a
`ValueError` to 400 `{"error": 〈Chinese message〉}`. Reads are wrapped in the usual
`{data, generated_at}` envelope; PUTs return the step's fresh GET shape the same way.
F42-I05 adds `GET|POST …/scan` (the website/photo prefill, `app/intake/ai.py`) and
`POST …/custom` (「自訂」, `app/intake/custom.py`; a proposal only, nothing saved).

Entry point: this file's `router`, included at the end of `app/intake/routes_api.py`.
"""

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.db import Conn, now_iso
from app.intake import custom, onboarding
from app.meta import repository as meta_repo
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()

_BASE = "/api/intake/brands/{brand_id}/onboarding"


def _envelope(data) -> dict:
    return {"data": data, "generated_at": now_iso()}


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
        # F50 Contract I: a refusal that names its fields (`onboarding.FieldErrors`) also sends
        # them keyed, so the step shows each sentence under its own row.
        payload: dict = {"error": str(exc)}
        if field_errors := getattr(exc, "field_errors", None):
            payload["field_errors"] = field_errors
        return JSONResponse(payload, status_code=400)
    return _envelope(data)


@router.get(_BASE)
def onboarding_status(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.status)


@router.post(_BASE + "/complete")
def onboarding_complete(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.complete)


@router.get(_BASE + "/scan")
def scan_get(request: Request, brand_id: str):
    return _read(request, brand_id, onboarding.scan_status)


@router.post(_BASE + "/scan")
def scan_post(request: Request, brand_id: str):
    """Start the website/photo prefill (F42-I05) once; returns the GET shape. 400: no open draft
    or nothing to read; 409: the draft cost cap refused before any call."""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    try:
        data = onboarding.start_scan(_conn(), brand_id, org_id=actor.org_id)
    except onboarding.ScanRefused as exc:
        return _error(409, str(exc))
    except ValueError as exc:
        return _error(400, str(exc))
    return _envelope(data)


@router.post(_BASE + "/custom")
async def custom_post(request: Request, brand_id: str):
    """「自訂」 (F42-I05): `{block, text}` → one proposal; nothing is saved (the step's PUT saves).
    422 = the AI's reply is outside the block's contract."""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    try:  # the model call is blocking: keep it off the event loop
        data = await run_in_threadpool(custom.propose, _conn(), brand_id,
                                       str(body.get("block") or ""), str(body.get("text") or ""))
    except custom.CustomRefused as exc:
        return _error(exc.status_code, exc.message)
    except ValueError:
        return _error(422, custom.UNREADABLE_MESSAGE)
    return _envelope(data)


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
