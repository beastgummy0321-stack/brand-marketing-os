"""app/brand_web/routes_brand_settings.py — 品牌層設定的 /api 端點：規則卡與節日提醒開關。

外殼切片（2026-08-28）從已刪除的 `app/ads/routes_settings.py` 搬過來。搬的是那支檔案裡
**不屬於廣告**的兩組端點：規則卡讀寫／重設（資料在 `app.core.rule_cards`）與節日提醒
類別開關（資料在 `app.core.calendar_dismiss`，跨品牌總覽的檔期提醒指南卡讀它）。原檔的
Meta MCP 與品牌風格偏好兩組端點屬於廣告模組，跟著一起刪掉，沒有搬過來。

路徑一字不改（契約 `.scratch/grill/GRILL-B1-settings.md` S15.29–S15.33 指定
`/api/settings/rule-cards/brands/{brand_id}/...`），前端不必跟著改。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/brand_web/__init__.py` 的 register()。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.core import calendar_dismiss as core_calendar_dismiss
from app.core import rule_cards
from app.shared.web import JSONResponse

router = APIRouter()

# 有效卡鍵一律問 rule_cards.CARDS 本身，不在這裡另開一份清單（沿用原檔慣例）。


def _calendar_categories_ctx(conn, brand_id: str) -> list:
    """節日提醒小節（G14.9／G14.10）：逐節日類別現況。空狀態（品牌從沒關過任何類別）
    全部 enabled=True，等同「全部提醒中」——不用另外判斷空態，`list_dismissed()` 沒有
    任何列本身就是這個狀態。"""
    dismissed = core_calendar_dismiss.list_dismissed(conn, brand_id)
    return [{"category": cat["category"], "label": cat["label"],
            "enabled": cat["category"] not in dismissed}
            for cat in core_calendar_dismiss.list_categories()]


def _validate_card_fields(card_key: str, raw_values: dict) -> tuple:
    """驗證整卡送出的欄位：每個欄位都要填、且要大於 0（缺欄位視為空字串，同「整卡一起
    送出」的既有規則）。回傳 (parsed 有效值, field_errors)。"""
    field_errors = {}
    parsed = {}
    for field_key in rule_cards.CARDS[card_key]["fields"]:
        raw = raw_values.get(field_key, "")
        raw_str = "" if raw is None else str(raw)
        value, ok = main_mod.parse_number(raw_str)
        if not ok or value is None or value <= 0:
            field_errors[field_key] = "請填一個大於 0 的數字。"
            continue
        if card_key == "autonomy" and value not in (1.0, 2.0):
            field_errors[field_key] = "投放自動度只有保守檔（1）與放手檔（2）兩種。"
            continue
        parsed[field_key] = value
    return parsed, field_errors


# ---------------------------------------------------------------------------
# 規則卡 JSON API（票 B1-settings，契約 S15.29–S15.33）。讀寫邏輯全部重用 rule_cards
# 既有函式與上面 `_validate_card_fields()`，這裡只做「解析請求 → 呼叫 → 組 JSON」的薄層。
# ---------------------------------------------------------------------------

def _rule_card_json(card: dict) -> dict:
    """把 `rule_cards.get_card()`／`list_cards()` 回傳的卡片轉成契約 RuleCard 型別：
    加 `customized` 旗標，比對這張卡目前值是否偏離系統預設值。"""
    return {
        "key": card["key"], "title": card["title"], "description": card["description"],
        "fields": [
            {"key": f["key"], "label": f["label"], "unit": f["unit"], "help": f["help"],
             "value": f["value"], "customized": f["value"] != f["default"]}
            for f in card["fields"]
        ],
    }


@router.get("/api/settings/rule-cards/brands/{brand_id}")
async def api_rule_cards_get(brand_id: str, request: Request):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    cards = [_rule_card_json(c) for c in rule_cards.list_cards(main_mod.conn, brand_id)]
    return {
        "data": {"brand_id": brand_id, "cards": cards},
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/api/settings/rule-cards/brands/{brand_id}/{card_key}")
async def api_rule_cards_save(request: Request, brand_id: str, card_key: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    if card_key not in rule_cards.CARDS:
        raise main_mod.NotFoundKind("規則卡")
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    parsed, field_errors = _validate_card_fields(card_key, body)
    if field_errors:
        error_message = "有欄位沒有填一個大於 0 的數字。"
        if card_key == "autonomy" and "mode" in field_errors:
            error_message = field_errors["mode"]
        return JSONResponse(
            {"error": error_message, "field_errors": field_errors}, status_code=400)
    for field_key, value in parsed.items():
        rule_cards.set_value(main_mod.conn, brand_id, card_key, field_key, value,
                             str(actor.user_id), org_id=actor.org_id)
    card = rule_cards.get_card(main_mod.conn, brand_id, card_key)
    return {"data": _rule_card_json(card), "generated_at": datetime.now(UTC).isoformat()}


@router.post("/api/settings/rule-cards/brands/{brand_id}/{card_key}/reset")
async def api_rule_cards_reset(request: Request, brand_id: str, card_key: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    if card_key not in rule_cards.CARDS:
        raise main_mod.NotFoundKind("規則卡")
    rule_cards.reset_card(main_mod.conn, brand_id, card_key, str(actor.user_id),
                          org_id=actor.org_id)
    card = rule_cards.get_card(main_mod.conn, brand_id, card_key)
    return {"data": _rule_card_json(card), "generated_at": datetime.now(UTC).isoformat()}


# ---------------------------------------------------------------------------
# 節日提醒開關 JSON API（新殼設定頁）。清單與現況判斷沿用 `_calendar_categories_ctx()`，
# 不重寫一份；驗證邏輯（未知類別 404）沿用同一函式上面的既有比對。
# ---------------------------------------------------------------------------

@router.get("/api/settings/calendar/brands/{brand_id}")
async def api_calendar_categories_get(brand_id: str, request: Request):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    categories = _calendar_categories_ctx(main_mod.conn, brand_id)
    return {
        "data": {"brand_id": brand_id, "categories": categories},
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/api/settings/calendar/brands/{brand_id}/{category}")
async def api_calendar_category_toggle(request: Request, brand_id: str, category: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    valid_categories = {cat["category"] for cat in core_calendar_dismiss.list_categories()}
    if category not in valid_categories:
        raise main_mod.NotFoundKind("節日類別")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return JSONResponse({"error": "enabled 必須是 true 或 false"}, status_code=400)
    if body["enabled"]:
        core_calendar_dismiss.undismiss(main_mod.conn, brand_id, category)
    else:
        core_calendar_dismiss.dismiss(main_mod.conn, brand_id, category, org_id=actor.org_id)
    item = next(c for c in _calendar_categories_ctx(main_mod.conn, brand_id)
                if c["category"] == category)
    return {"data": item, "generated_at": datetime.now(UTC).isoformat()}
