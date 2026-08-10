# -*- coding: utf-8 -*-
"""app/ads/routes_settings.py — 設定中心「廣告層面」分類詳細頁（票 02-qa-reminder-reset）。

`/brands/{brand_id}/settings/ads`：既有四張規則卡（`app.core.rule_cards`）＋新增「上線前
提醒」小節（資料來自 `app.ads.checklist` 的 `QA_LAUNCH_ITEMS`／`brand_checklist_item`
表，決策 0016 第三節）。

**這頁本來在 `app/brand_intelligence/routes_settings.py`，這一票搬過來**：那個檔的檔頭已經
寫明「這裡不 import `app.ads`」——`app.brand_intelligence` 依 A1 三層地界（見
`test_architecture_boundaries.py` 的 `LAYER_ORDER`／`BRANCH_PACKAGES`）不得依賴分支專屬層
`app.ads`，硬性掃描會擋下。「上線前提醒」小節需要 `app.ads.checklist` 的資料，所以整頁改
掛到 `app.ads`（本來就允許依賴 `app.brand_intelligence`／`app.core`／`app.shared`，方向對）。
入口頁 `/brands/{brand_id}/settings`（兩張分類卡）不需要 checklist 資料，留在原檔不動。

票 02-permanent-dismiss-category（ADR 0014 第三節，G14.9／G14.10）：再加「節日提醒」小節，
逐節日類別一顆開關，沿用「上線前提醒」小節剛立下的欄位列＋按鈕切換慣例（`.claim-block`／
`.claim-row`／badge／hidden field 表單，見下方 `settings_calendar_toggle_post`）。資料存取走
`app.core.calendar_dismiss`（`app.core`，不是 `app.dashboard`）——`app.core.calendar_dismiss.
list_categories()` 刻意直接讀 `campaign_calendar_data.json`、不 import
`app.dashboard.campaign_calendar`，理由見該模組檔頭（app.dashboard 排在 app.ads 之後，
import 一樣違反 A1 三層地界）。

對外進入點：本檔的 `router`，掛進 `app/ads/routes.py` 的匯總 router（沿用第 8 刀「固定前綴、
掛的順序不影響」的既有掛法，同 routes_creative_theme／routes_workbench）。誰依賴它：只有
`app/ads/routes.py`。
"""

from fastapi import APIRouter, Form, Request

import app.shared.web as main_mod
from app.ads import checklist as ads_checklist
from app.core import calendar_dismiss as core_calendar_dismiss
from app.core import rule_cards

router = APIRouter()

# 有效卡鍵一律問 rule_cards.CARDS 本身，不在這裡另開一份清單（沿用原檔慣例）。


def _crumb(brand: dict, *tail) -> list:
    items = [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"),
             ("設定中心", f"/brands/{brand['id']}/settings")]
    items.extend(tail)
    return items


def _calendar_categories_ctx(conn, brand_id: str) -> list:
    """節日提醒小節（G14.9／G14.10）：逐節日類別現況。空狀態（品牌從沒關過任何類別）
    全部 enabled=True，等同「全部提醒中」——不用另外判斷空態，`list_dismissed()` 沒有
    任何列本身就是這個狀態。"""
    dismissed = core_calendar_dismiss.list_dismissed(conn, brand_id)
    return [{"category": cat["category"], "label": cat["label"],
            "enabled": cat["category"] not in dismissed}
            for cat in core_calendar_dismiss.list_categories()]


def _ads_cards_ctx(request: Request, brand: dict, errors=None, raw_values=None):
    """raw_values＝{card_key: {field_key: 使用者剛送出的原始字串}}：驗證失敗時原樣填回輸入框，
    不要讓打錯字的使用者看到自己輸入被靜靜換成舊的資料庫值（沿用既有 /rule-cards 慣例）。"""
    conn = main_mod.conn
    cards = rule_cards.list_cards(conn, brand["id"])
    raw_values = raw_values or {}
    for card in cards:
        overrides = raw_values.get(card["key"]) or {}
        for f in card["fields"]:
            f["customized"] = f["value"] != f["default"]  # G14.5：前端比對，不是後端旗標
            f["value"] = overrides[f["key"]] if f["key"] in overrides else main_mod._num_str(f["value"])
    return main_mod.ctx(
        request, brand=brand, nav_current=None,
        breadcrumb_items=_crumb(brand, ("廣告層面", None)),
        cards=cards,
        qa_launch=ads_checklist.qa_launch_summary(conn, brand["id"]),
        calendar_categories=_calendar_categories_ctx(conn, brand["id"]),
        errors=errors or {},
        **main_mod.banner_ctx(request),
    )


@router.get("/brands/{brand_id}/settings/ads")
async def settings_ads_get(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    return main_mod.templates.TemplateResponse(
        request, "settings_ads.html", _ads_cards_ctx(request, brand))


@router.post("/brands/{brand_id}/settings/ads/{card_key}/edit")
async def settings_ads_edit_post(request: Request, brand_id: str, card_key: str):
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    if card_key not in rule_cards.CARDS:
        raise main_mod.NotFoundKind("規則卡")
    form = await request.form()
    field_errors = {}
    raw_values = {}
    parsed = {}
    for field_key in rule_cards.CARDS[card_key]["fields"]:
        raw = form.get(field_key, "")
        raw_values[field_key] = raw
        value, ok = main_mod.parse_number(raw)
        if not ok or value is None or value <= 0:
            field_errors[field_key] = "請填一個大於 0 的數字。"
            continue
        parsed[field_key] = value
    if field_errors:
        return main_mod.templates.TemplateResponse(request, "settings_ads.html", _ads_cards_ctx(
            request, brand, errors={card_key: field_errors}, raw_values={card_key: raw_values},
        ), status_code=400)
    for field_key, value in parsed.items():
        rule_cards.set_value(main_mod.conn, brand_id, card_key, field_key, value, actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/settings/ads", f"已更新「{rule_cards.CARDS[card_key]['title']}」。")


@router.post("/brands/{brand_id}/settings/ads/{card_key}/reset")
async def settings_ads_reset_post(request: Request, brand_id: str, card_key: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    if card_key not in rule_cards.CARDS:
        raise main_mod.NotFoundKind("規則卡")
    rule_cards.reset_card(main_mod.conn, brand_id, card_key, actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/settings/ads",
        f"已將「{rule_cards.CARDS[card_key]['title']}」重設為系統預設值。")


@router.post("/brands/{brand_id}/settings/ads/qa-launch/{item_key}")
async def settings_ads_qa_launch_toggle(request: Request, brand_id: str, item_key: str,
                                        checked: str = Form("1")):
    """上線前提醒開關（票 02，決策 0016 第三節）：關閉＝已確認、不再提醒；重新打開＝清除
    確認紀錄，下次上線授權頁重新顯示紅色警示。跟 `app.ads.routes_handoff` 的
    `/handoff/qa-launch/{key}` 共用同一個 `set_qa_launch_item`——「確認一次全站生效」是
    `brand_checklist_item` 這張表本來就有的行為（不分哪個入口寫入），不用另外實作。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    try:
        ads_checklist.set_qa_launch_item(main_mod.conn, brand_id, item_key, checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/settings/ads", str(exc), kind="warn")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/settings/ads", "記下來了。")


@router.post("/brands/{brand_id}/settings/ads/calendar/{category}")
async def settings_calendar_toggle_post(request: Request, brand_id: str, category: str,
                                        enabled: str = Form("1")):
    """節日提醒永久開關（票 02-permanent-dismiss-category，ADR 0014 第二、三節）：關閉＝
    永久忽略這個節日類別，之後系統業種比對判成相關也不再提醒；重新開啟＝刪除覆寫紀錄，
    恢復正常提醒。category 驗證合法性同 card_key 慣例（未知值 404，不是靜默忽略）。"""
    main_mod.require_brand(brand_id)
    valid_categories = {cat["category"] for cat in core_calendar_dismiss.list_categories()}
    if category not in valid_categories:
        raise main_mod.NotFoundKind("節日類別")
    if enabled == "1":
        core_calendar_dismiss.undismiss(main_mod.conn, brand_id, category)
    else:
        core_calendar_dismiss.dismiss(main_mod.conn, brand_id, category)
    return main_mod.redirect_with_message(f"/brands/{brand_id}/settings/ads", "記下來了。")
