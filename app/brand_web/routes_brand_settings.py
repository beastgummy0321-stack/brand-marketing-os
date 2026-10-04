"""app/brand_web/routes_brand_settings.py — 品牌層設定的 /api 端點：規則卡。

外殼切片（2026-08-28）從已刪除的 `app/ads/routes_settings.py` 搬過來規則卡讀寫／重設
（資料在 `app.core.rule_cards`）。原檔的 Meta MCP 與品牌風格偏好兩組端點屬於廣告模組，
跟著一起刪掉，沒有搬過來。節日提醒類別開關隨 ADR 0036 的日曆刪除一起刪掉。

路徑一字不改（契約 `.scratch/grill/GRILL-B1-settings.md` S15.29–S15.33 指定
`/api/settings/rule-cards/brands/{brand_id}/...`），前端不必跟著改。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/brand_web/__init__.py` 的 register()。
"""


from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.core import input_rules, rule_cards
from app.core.db import now_iso
from app.shared.web import JSONResponse

router = APIRouter()

# 有效卡鍵一律問 rule_cards.CARDS 本身，不在這裡另開一份清單（沿用原檔慣例）。


def _validate_card_fields(card_key: str, raw_values: dict) -> tuple:
    """驗證整卡送出的欄位：每個欄位都要填、且落在該欄位在 `rule_cards.CARDS` 宣告的範圍內
    （F47 Contract A，`app.core.input_rules`；缺欄位視為空字串，同「整卡一起送出」的既有規則）；
    卡上宣告的 (下限, 上限) 欄位對，下限大於上限整卡擋下，兩欄都掛同一句話。
    回傳 (parsed 有效值, field_errors)。"""
    card = rule_cards.CARDS[card_key]
    field_errors = {}
    parsed = {}
    for field_key, meta in card["fields"].items():
        raw = raw_values.get(field_key, "")
        try:
            parsed[field_key] = input_rules.within(
                "" if raw is None else raw, meta["label"], meta["bounds"])
        except input_rules.InputRuleError as exc:
            field_errors[field_key] = str(exc)
    for low_key, high_key in card.get("pairs", ()):
        if low_key in parsed and high_key in parsed:
            try:
                input_rules.ordered_pair(parsed[low_key], parsed[high_key],
                                         card["fields"][low_key]["label"],
                                         card["fields"][high_key]["label"])
            except input_rules.InputRuleError as exc:
                field_errors[low_key] = field_errors[high_key] = str(exc)
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
def api_rule_cards_get(brand_id: str, request: Request):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    cards = [_rule_card_json(c) for c in rule_cards.list_cards(main_mod.conn, brand_id)]
    return {
        "data": {"brand_id": brand_id, "cards": cards},
        "generated_at": now_iso(),
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
        return JSONResponse(
            {"error": next(iter(field_errors.values())), "field_errors": field_errors},
            status_code=400)
    for field_key, value in parsed.items():
        rule_cards.set_value(main_mod.conn, brand_id, card_key, field_key, value,
                             str(actor.user_id), org_id=actor.org_id)
    card = rule_cards.get_card(main_mod.conn, brand_id, card_key)
    return {"data": _rule_card_json(card), "generated_at": now_iso()}


@router.post("/api/settings/rule-cards/brands/{brand_id}/{card_key}/reset")
def api_rule_cards_reset(request: Request, brand_id: str, card_key: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    if card_key not in rule_cards.CARDS:
        raise main_mod.NotFoundKind("規則卡")
    rule_cards.reset_card(main_mod.conn, brand_id, card_key, str(actor.user_id),
                          org_id=actor.org_id)
    card = rule_cards.get_card(main_mod.conn, brand_id, card_key)
    return {"data": _rule_card_json(card), "generated_at": now_iso()}
