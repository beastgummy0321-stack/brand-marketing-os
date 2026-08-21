# -*- coding: utf-8 -*-
"""app/brand_web/routes_library_write.py — 品牌智庫六分頁寫入動作的 /api 版本
（票：解除刪 app/brand_web/routes.py 最後 17 支舊頁 handler 的前置阻塞）。

`routes_library.py` 本身已經接近 `docs/tech-debt.md` 凍結的 800 行上限，這裡新增
的 17 支端點（品牌事實／限制規則／宣稱新增編輯刪除確認、官方素材刪除、自有渠道
新增編輯刪除、顧客原話封存刪除、品牌資料編輯）另開一個檔案，不把 `routes_library.py`
推過門檻——比照 `repository_channels.py` 從 `repository.py` 拆出來的同一個理由。

這些端點是 `app/brand_web/routes.py` 舊版 Jinja 表單 POST 端點（303 redirect 回
`/hub/*` 或 `/brands/{id}`）的 JSON 對應版本：驗證規則與錯誤訊息照抄舊版 handler，
業務邏輯全部沿用既有的 repository 函式，這裡只是換一層 JSON 進出的殼，不 redirect。
`frontend/src/lib/libraryApi.ts` 目前仍呼叫舊版端點；等前端切換過來後，舊版
handler 與它們 redirect 落地用的 GET hub 頁才能整批刪除（本票不動舊端點）。

小工具沿用而非複製：`_create_source_ref`／`_persona_conversion_goal_default`
（`app/brand_web/routes.py` 私有函式）與 `_fact_shape`／`_rule_shape`／`_claim_shape`／
`_channel_shape`／`_customer_voice_shape`／`_brand_profile_shape`
（`routes_library.py` 私有函式，`/api/library/brands/{id}` 整包讀取用的同一份形狀）
都直接 import，不另外維護第二份。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`）。
誰依賴它：只有 `app/main.py`。
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import mock_data as md
from app.brand_intelligence import repository as repo
from app.brand_web import routes as brand_routes
from app.brand_web.routes_library import (
    _brand_profile_shape,
    _channel_shape,
    _claim_shape,
    _customer_voice_shape,
    _fact_shape,
    _rule_shape,
)
from app.shared import web
from app.shared.web import NotFoundKind, clean, require_actor, require_brand

router = APIRouter()


async def _json_body(request: Request) -> dict:
    """新版 /api 端點統一收 JSON body；不是合法 JSON 或不是物件就當空 dict，
    後面照欄位各自的必填檢查報錯，不特別處理格式錯誤本身。"""
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _str_field(body: dict, key: str) -> str:
    return str(body.get(key) or "")


# ---- 品牌事實 ----

@router.post("/api/library/brands/{brand_id}/facts")
async def fact_create_api(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    body = await _json_body(request)
    fact_type = _str_field(body, "fact_type")
    label = _str_field(body, "label")
    value = _str_field(body, "value")
    status = _str_field(body, "status") or "pending"
    source_reference = _str_field(body, "source_reference")
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if status not in ("confirmed", "pending"):
        errors["status"] = "請選擇是否已經確認過。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = brand_routes._create_source_ref(brand_id, actor, source_reference)
    confirmed_by = actor if status == "confirmed" else None
    row = repo.create_brand_fact(
        web.conn, brand_id, actor=actor, fact_type=fact_type, label=clean(label), value=clean(value),
        status=status, source_reference_id=src_id, confirmed_by=confirmed_by,
    )
    return {"data": _fact_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/facts/{fact_id}/edit")
async def fact_update_api(request: Request, brand_id: str, fact_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    body = await _json_body(request)
    fact_type = _str_field(body, "fact_type")
    label = _str_field(body, "label")
    value = _str_field(body, "value")
    source_reference = _str_field(body, "source_reference")
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = brand_routes._create_source_ref(brand_id, actor, source_reference) or fact["source_reference_id"]
    row = repo.update_brand_fact(web.conn, brand_id, fact_id, actor=actor, fact_type=fact_type,
                                  label=clean(label), value=clean(value), source_reference_id=src_id)
    return {"data": _fact_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/facts/{fact_id}/confirm")
async def fact_confirm_api(request: Request, brand_id: str, fact_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    body = await _json_body(request)
    confirmed_by_c = clean(_str_field(body, "confirmed_by"))
    if not confirmed_by_c:
        return JSONResponse({"errors": {"confirmed_by": "請填寫確認人是誰。"}}, status_code=400)
    row = repo.confirm_brand_fact(web.conn, brand_id, fact_id, confirmed_by=confirmed_by_c, actor=actor)
    return {"data": _fact_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/facts/{fact_id}/delete")
async def fact_delete_api(request: Request, brand_id: str, fact_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    repo.delete_brand_fact(web.conn, brand_id, fact_id, actor=actor)
    return {"ok": True}


# ---- 限制規則 ----

def _validate_rule_fields(brand_id: str, rule_type: str, content: str, severity: str,
                           product_id: str) -> dict:
    errors = {}
    if not clean(rule_type):
        errors["rule_type"] = "請選擇規則類型。"
    if not clean(content):
        errors["content"] = "請填寫規則內容。"
    if severity not in ("hard", "soft"):
        errors["severity"] = "請選擇必須遵守或建議遵守。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    return errors


@router.post("/api/library/brands/{brand_id}/rules")
async def rule_create_api(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    body = await _json_body(request)
    rule_type = _str_field(body, "rule_type")
    content = _str_field(body, "content")
    severity = _str_field(body, "severity") or "soft"
    product_id = clean(_str_field(body, "product_id"))
    source_reference = _str_field(body, "source_reference")
    errors = _validate_rule_fields(brand_id, rule_type, content, severity, product_id)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = brand_routes._create_source_ref(brand_id, actor, source_reference)
    row = repo.create_rule(web.conn, brand_id, actor=actor, rule_type=rule_type, content=clean(content),
                            severity=severity, product_id=product_id or None, source_reference_id=src_id)
    return {"data": _rule_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/rules/{rule_id}/edit")
async def rule_update_api(request: Request, brand_id: str, rule_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    rule = repo.get_rule(web.conn, brand_id, rule_id)
    if not rule:
        raise NotFoundKind("限制規則")
    body = await _json_body(request)
    rule_type = _str_field(body, "rule_type")
    content = _str_field(body, "content")
    severity = _str_field(body, "severity") or "soft"
    product_id = clean(_str_field(body, "product_id"))
    source_reference = _str_field(body, "source_reference")
    errors = _validate_rule_fields(brand_id, rule_type, content, severity, product_id)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = brand_routes._create_source_ref(brand_id, actor, source_reference) or rule["source_reference_id"]
    row = repo.update_rule(web.conn, brand_id, rule_id, actor=actor, rule_type=rule_type,
                            content=clean(content), severity=severity, product_id=product_id or None,
                            source_reference_id=src_id)
    return {"data": _rule_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/rules/{rule_id}/delete")
async def rule_delete_api(request: Request, brand_id: str, rule_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    try:
        repo.delete_rule(web.conn, brand_id, rule_id, actor=actor)
    except ValueError:
        raise NotFoundKind("限制規則")
    return {"ok": True}


# ---- 宣稱 ----

def _validate_claim_fields(brand_id: str, claim_text: str, claim_type: str, product_id: str) -> dict:
    errors = {}
    if not clean(claim_text):
        errors["claim_text"] = "請填寫宣稱內容。"
    if claim_type not in ("approved", "high_risk", "forbidden"):
        errors["claim_type"] = "請選擇這句宣稱屬於哪一類。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    return errors


@router.post("/api/library/brands/{brand_id}/claims")
async def claim_create_api(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    body = await _json_body(request)
    claim_text = _str_field(body, "claim_text")
    claim_type = _str_field(body, "claim_type") or "high_risk"
    product_id = clean(_str_field(body, "product_id"))
    evidence_source_reference = _str_field(body, "evidence_source_reference")
    errors = _validate_claim_fields(brand_id, claim_text, claim_type, product_id)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = brand_routes._create_source_ref(brand_id, actor, evidence_source_reference)
    row = repo.create_claim(web.conn, brand_id, actor=actor, claim_text=clean(claim_text),
                             claim_type=claim_type, product_id=product_id or None,
                             evidence_source_reference_id=src_id)
    return {"data": _claim_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/claims/{claim_id}/edit")
async def claim_update_api(request: Request, brand_id: str, claim_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    claim = repo.get_claim(web.conn, brand_id, claim_id)
    if not claim:
        raise NotFoundKind("宣稱")
    body = await _json_body(request)
    claim_text = _str_field(body, "claim_text")
    claim_type = _str_field(body, "claim_type") or "high_risk"
    product_id = clean(_str_field(body, "product_id"))
    evidence_source_reference = _str_field(body, "evidence_source_reference")
    errors = _validate_claim_fields(brand_id, claim_text, claim_type, product_id)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    src_id = (brand_routes._create_source_ref(brand_id, actor, evidence_source_reference)
              or claim["evidence_source_reference_id"])
    row = repo.update_claim(web.conn, brand_id, claim_id, actor=actor, claim_text=clean(claim_text),
                             claim_type=claim_type, product_id=product_id or None,
                             evidence_source_reference_id=src_id)
    return {"data": _claim_shape(brand_id, row)}


@router.post("/api/library/brands/{brand_id}/claims/{claim_id}/delete")
async def claim_delete_api(request: Request, brand_id: str, claim_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    try:
        repo.delete_claim(web.conn, brand_id, claim_id, actor=actor)
    except ValueError:
        raise NotFoundKind("宣稱")
    return {"ok": True}


# ---- 官方素材（上傳已有 /api/brands/{id}/assets，這裡補刪除）----

@router.post("/api/library/brands/{brand_id}/assets/{asset_id}/delete")
async def asset_delete_api(request: Request, brand_id: str, asset_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    asset = repo.get_official_asset(web.conn, brand_id, asset_id)
    if not asset:
        raise NotFoundKind("官方素材")
    repo.delete_official_asset(web.conn, brand_id, asset_id, actor=actor)
    try:
        Path(asset["file_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


# ---- 自有渠道（新增；編輯／刪除已有舊表單路徑版本，見下方「自有渠道編輯／刪除」段）----

@router.post("/api/library/brands/{brand_id}/channels")
async def channel_create_api(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    body = await _json_body(request)
    channel_type = _str_field(body, "channel_type")
    name = _str_field(body, "name")
    identifier = _str_field(body, "identifier")
    status = _str_field(body, "status") or "active"
    errors = {}
    if not clean(channel_type):
        errors["channel_type"] = "請選擇渠道類型。"
    if not clean(name):
        errors["name"] = "請填寫渠道名稱。"
    if not clean(identifier):
        errors["identifier"] = "請填寫網址或帳號。"
    if status not in ("active", "inactive"):
        errors["status"] = "請選擇狀態。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    row = repo.create_channel(web.conn, brand_id, actor=actor, channel_type=channel_type,
                               name=clean(name), identifier=clean(identifier), status=status)
    return {"data": _channel_shape(row)}


@router.post("/api/library/brands/{brand_id}/channels/{channel_id}/edit")
async def channel_update_api(request: Request, brand_id: str, channel_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    body = await _json_body(request)
    channel_type = _str_field(body, "channel_type")
    name = _str_field(body, "name")
    identifier = _str_field(body, "identifier")
    status = _str_field(body, "status") or "active"
    errors = {}
    if not clean(channel_type):
        errors["channel_type"] = "請選擇渠道類型。"
    if not clean(name):
        errors["name"] = "請填寫渠道名稱。"
    if not clean(identifier):
        errors["identifier"] = "請填寫網址或帳號。"
    if status not in ("active", "inactive"):
        errors["status"] = "請選擇狀態。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    try:
        row = repo.update_channel(web.conn, brand_id, channel_id, actor=actor, channel_type=channel_type,
                                   name=clean(name), identifier=clean(identifier), status=status)
    except ValueError:
        raise NotFoundKind("自有渠道")
    return {"data": _channel_shape(row)}


@router.post("/api/library/brands/{brand_id}/channels/{channel_id}/delete")
async def channel_delete_json_api(request: Request, brand_id: str, channel_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    try:
        repo.delete_channel(web.conn, brand_id, channel_id, actor=actor)
    except ValueError:
        raise NotFoundKind("自有渠道")
    return {"ok": True}


# ---- 品牌資料側板 ----

@router.post("/api/library/brands/{brand_id}/edit")
async def brand_update_api(request: Request, brand_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    body = await _json_body(request)
    name = _str_field(body, "name")
    client_name = _str_field(body, "client_name")
    status = _str_field(body, "status") or "active"
    persona = _str_field(body, "persona")
    market_region = _str_field(body, "market_region")
    conversion_goal = _str_field(body, "conversion_goal")
    industry = _str_field(body, "industry")
    errors = {}
    name_c = clean(name)
    if not name_c:
        errors["name"] = "請填寫品牌名稱。"
    if status not in ("active", "archived"):
        errors["status"] = "請選擇品牌狀態。"
    region_c = clean(market_region)
    if region_c and region_c not in dict(md.MARKET_REGIONS):
        errors["market_region"] = "請選擇有效的市場地區。"
    goal_c = clean(conversion_goal)
    if goal_c and goal_c not in repo.CONVERSION_GOALS:
        errors["conversion_goal"] = "請選擇有效的廣告目標。"
    industry_c = clean(industry)
    if industry_c and industry_c not in repo.INDUSTRIES:
        errors["industry"] = "請選擇有效的業種。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    repo.update_brand(web.conn, brand_id, name=name_c, client_name=clean(client_name), status=status,
                       actor=actor)
    repo.set_brand_switches(
        web.conn, brand_id, market_region=region_c or None,
        conversion_goal=goal_c or brand_routes._persona_conversion_goal_default(persona), actor=actor,
    )
    repo.set_brand_industry(web.conn, brand_id, industry=industry_c or None, actor=actor)
    updated = repo.get_brand(web.conn, brand_id)
    return {"data": _brand_profile_shape(brand_id, updated)}


# ---- 顧客原話封存／刪除：舊表單端點（`app/brand_web/routes.py`
# `customer_voice_archive_post`／`customer_voice_delete_post`）的 /api 對應版本 ----

@router.post("/api/library/brands/{brand_id}/customer-voice/{cv_id}/archive")
async def customer_voice_archive_api(request: Request, brand_id: str, cv_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    voice = repo.get_customer_voice(web.conn, brand_id, cv_id)
    if voice is None:
        raise NotFoundKind("顧客原話")
    new_status = "active" if voice["status"] == "archived" else "archived"
    row = repo.set_customer_voice_status(web.conn, brand_id, cv_id, status=new_status, actor=actor)
    return {"data": _customer_voice_shape(row)}


@router.post("/api/library/brands/{brand_id}/customer-voice/{cv_id}/delete")
async def customer_voice_delete_api(request: Request, brand_id: str, cv_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    voice = repo.get_customer_voice(web.conn, brand_id, cv_id)
    if voice is None:
        raise NotFoundKind("顧客原話")
    repo.delete_customer_voice(web.conn, brand_id, cv_id, actor=actor)
    return {"ok": True}
