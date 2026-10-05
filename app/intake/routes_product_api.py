"""app/intake/routes_product_api.py — product onboarding JSON API (F43-I05).

The HTTP contract of the products page, the five product-onboarding steps and the bundle page
(`#/plist`, `#/p1`–`#/p5`, `#/bundle`, the `#/home` product block). Logic lives in
`app/intake/product_onboarding.py`; this file only authenticates (`require_brand` tenant check on
every route), parses the body and maps errors: `ValueError` -> 400, `NotFound` (a product / bundle
that is not this brand's) -> 404, both as `{"error": 〈Chinese message〉}`; a refusal that names its
fields (`onboarding.FieldErrors`) adds `field_errors` {field key: sentence}. Reads are wrapped in
the usual `{data, generated_at}` envelope; PUTs return the step's fresh GET shape the same way.

Routes (all under `/api/intake/brands/{brand_id}`):
    GET|POST /products                                  products page / new product (step 1)
    POST     /products/suggestions/dismiss              「不用了」 on an AI suggestion (F47 Q8)
    GET      /products/{p}/onboarding                   step, completed, prefill status
    POST     /products/{p}/onboarding/complete          完成 (step 5 -> done)
    POST     /products/{p}/onboarding/scan              re-read the product page (F43-I06)
    POST     /products/{p}/onboarding/custom            「自訂」 product block (F43-I06)
    GET|PUT  /products/{p}/onboarding/what|who|evidence|sell-ways
    POST     /bundles, GET|PUT /bundles/{id}            新增組合 / edit
    POST     /bundles/preview                           新增組合's numbers (writes nothing)

Entry point: this file's `router`, included at the end of `app/intake/routes_api.py`.
"""

from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.db import Conn, now_iso
from app.intake import custom, product_prefill
from app.intake import product_onboarding as po
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()

_BRAND = "/api/intake/brands/{brand_id}"
_STEP = _BRAND + "/products/{product_id}/onboarding"


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


def _run(call: Callable[[], dict]):
    try:
        return _envelope(call())
    except po.NotFound as exc:
        return _error(404, str(exc))
    except ValueError as exc:
        # F50 Contract I: a refusal naming its fields (`onboarding.FieldErrors`) also sends them
        # keyed, so step 4 and the bundle page show each sentence under its own field.
        payload: dict = {"error": str(exc)}
        if field_errors := getattr(exc, "field_errors", None):
            payload["field_errors"] = field_errors
        return JSONResponse(payload, status_code=400)


def _read(request: Request, brand_id: str, reader: Callable[..., dict], *args):
    require_brand(brand_id, require_actor(request))
    return _run(lambda: reader(_conn(), brand_id, *args))


async def _write(request: Request, brand_id: str, writer: Callable[..., dict], *args):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    return _run(lambda: writer(_conn(), brand_id, *args, body, actor=str(actor.user_id)))


# ---- products page ----


@router.get(_BRAND + "/products")
def products_get(request: Request, brand_id: str):
    return _read(request, brand_id, po.list_page)


@router.post(_BRAND + "/products")
async def products_post(request: Request, brand_id: str):
    return await _write(request, brand_id, po.create)


@router.post(_BRAND + "/products/suggestions/dismiss")
async def suggestion_dismiss(request: Request, brand_id: str):
    """「不用了」 on an AI product suggestion `{name}` -> the products page (F47 Q8)."""
    return await _write(request, brand_id, po.dismiss_suggestion)


# ---- onboarding status / 完成 ----


@router.get(_STEP)
def onboarding_status(request: Request, brand_id: str, product_id: str):
    return _read(request, brand_id, po.status, product_id)


@router.post(_STEP + "/complete")
def onboarding_complete(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _run(lambda: po.complete(_conn(), brand_id, product_id, actor=str(actor.user_id)))


@router.post(_STEP + "/scan")
async def onboarding_scan(request: Request, brand_id: str, product_id: str):
    """Read the product page again (F43-I06) -> the status. Optional `{page_url}`: stored on the
    product, then read (F47 Contract F). 400: finished product / not a URL / nothing to read;
    409: the AI cost cap refused before anything was queued."""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    page_url = body.get("page_url")
    try:
        return _run(lambda: product_prefill.start_scan(
            _conn(), brand_id, product_id, page_url=page_url, actor=str(actor.user_id)))
    except product_prefill.ScanRefused as exc:
        return _error(409, str(exc))


@router.post(_STEP + "/custom")
async def onboarding_custom(request: Request, brand_id: str, product_id: str):
    """「自訂」 product block (F43-I06): `{block, text}` -> one proposal; nothing is saved (the
    step's PUT saves). 422 = the AI's reply is outside the block's contract."""
    require_brand(brand_id, require_actor(request))
    body = await _json_body(request)
    try:  # the model call is blocking: keep it off the event loop
        data = await run_in_threadpool(
            custom.propose, _conn(), brand_id, str(body.get("block") or ""),
            str(body.get("text") or ""), None, product_id=product_id)
    except po.NotFound as exc:
        return _error(404, str(exc))
    except custom.CustomRefused as exc:
        return _error(exc.status_code, exc.message)
    except ValueError:
        return _error(422, custom.UNREADABLE_MESSAGE)
    return _envelope(data)


# ---- the four steps ----


@router.get(_STEP + "/what")
def what_get(request: Request, brand_id: str, product_id: str):
    return _read(request, brand_id, po.get_what, product_id)


@router.put(_STEP + "/what")
async def what_put(request: Request, brand_id: str, product_id: str):
    return await _write(request, brand_id, po.put_what, product_id)


@router.get(_STEP + "/who")
def who_get(request: Request, brand_id: str, product_id: str):
    return _read(request, brand_id, po.get_who, product_id)


@router.put(_STEP + "/who")
async def who_put(request: Request, brand_id: str, product_id: str):
    return await _write(request, brand_id, po.put_who, product_id)


@router.get(_STEP + "/evidence")
def evidence_get(request: Request, brand_id: str, product_id: str):
    return _read(request, brand_id, po.get_evidence, product_id)


@router.put(_STEP + "/evidence")
async def evidence_put(request: Request, brand_id: str, product_id: str):
    return await _write(request, brand_id, po.put_evidence, product_id)


@router.get(_STEP + "/sell-ways")
def sell_ways_get(request: Request, brand_id: str, product_id: str):
    return _read(request, brand_id, po.get_sell_ways, product_id)


@router.put(_STEP + "/sell-ways")
async def sell_ways_put(request: Request, brand_id: str, product_id: str):
    return await _write(request, brand_id, po.put_sell_ways, product_id)


# ---- bundles ----


@router.post(_BRAND + "/bundles")
async def bundle_post(request: Request, brand_id: str):
    return await _write(request, brand_id, po.save_bundle, None)


@router.post(_BRAND + "/bundles/preview")
async def bundle_preview(request: Request, brand_id: str):
    """新增組合's numbers before 「建立組合」: POST /bundles's body -> GET /bundles/{id}'s shape
    (`id` null); writes nothing (the save runs in a rolled-back transaction)."""
    return await _write(request, brand_id, po.preview_bundle)


@router.get(_BRAND + "/bundles/{bundle_id}")
def bundle_get(request: Request, brand_id: str, bundle_id: str):
    return _read(request, brand_id, po.get_bundle, bundle_id)


@router.put(_BRAND + "/bundles/{bundle_id}")
async def bundle_put(request: Request, brand_id: str, bundle_id: str):
    return await _write(request, brand_id, po.save_bundle, bundle_id)
