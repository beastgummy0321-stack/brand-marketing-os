# -*- coding: utf-8 -*-
"""app/brand_intelligence/routes_settings.py — 設定中心入口頁（設定中心票 01；票
02-qa-reminder-reset 後範圍縮小）。

`/brands/{brand_id}/settings`：兩張分類卡（廣告層面／系統設定）的入口頁。「廣告層面」詳細頁
（`/brands/{brand_id}/settings/ads`，規則卡＋上線前提醒）已搬到 `app/ads/routes_settings.py`
——那頁的「上線前提醒」小節要讀 `app.ads.checklist` 的資料，而 `app.brand_intelligence` 依
A1 三層地界不得 import `app.ads`（分支專屬層，見 `test_architecture_boundaries.py` 的
`BRANCH_PACKAGES` 硬性掃描）。入口頁本身只讀 `rule_cards`（`app.core`）的預覽值，不需要 ads
資料，留在這裡不動。這裡也不 import `app.ads`——系統設定分類等它自己的票把憑證搬進來時再接
（見票 01 的 Out of Scope）。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`，不掛在
`app.brand_intelligence.routes` 底下——那個檔已經頂著 1854 行的凍結上限，不得再加）。
誰依賴它：只有 `app/main.py` 這個組裝根。
"""

from fastapi import APIRouter, Request

from app.core import rule_cards
from app.shared import web
from app.shared.web import _num_str, banner_ctx, ctx, require_brand, templates

router = APIRouter()

# 有效卡鍵一律問 rule_cards.CARDS 本身，不在這裡另開一份清單——CARDS 的檔頭註解就是承諾
# 「新增一張卡只要改那個常數，不用碰別的檔案」，這裡照樣遵守，不重造第二份權威來源。

# 入口頁「廣告層面」分類卡的 4 個代表性欄位（G14.1）：每張卡各挑一個，不是隨機湊數。
_ENTRY_PREVIEW_FIELDS = (
    ("budget_structure", "min_daily_per_group"),
    ("pacing", "deviation_threshold_ratio"),
    ("ad_creative_fatigue", "cold_danger"),
    ("sample_size", "baseline_5pct"),
)


def _crumb(brand: dict, *tail) -> list:
    items = [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}")]
    items.extend(tail)
    return items


def _ads_preview_pairs(conn, brand_id: str) -> list:
    """入口頁「廣告層面」卡的 4 個代表性欄位現值，沿用 CARDS 自己的標籤／單位，不另外造詞。"""
    pairs = []
    for card_key, field_key in _ENTRY_PREVIEW_FIELDS:
        meta = rule_cards.CARDS[card_key]["fields"][field_key]
        value = rule_cards.get_value(conn, brand_id, card_key, field_key)
        pairs.append((meta["label"], f"{_num_str(value)} {meta['unit']}", False))
    return pairs


def _ads_last_modified(conn, brand_id: str):
    """這個品牌最後一次改規則卡的稽核時間（ISO 字串）；從沒改過回 None（空態，G14.8）。"""
    row = conn.execute(
        "SELECT created_at FROM audit_log WHERE brand_id = ? AND entity_type = 'rule_card_value'"
        " ORDER BY created_at DESC LIMIT 1",
        (brand_id,),
    ).fetchone()
    return row["created_at"] if row else None


@router.get("/brands/{brand_id}/settings")
async def settings_hub_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    conn = web.conn
    return templates.TemplateResponse(request, "settings_hub.html", ctx(
        request, brand=brand, nav_current=None,
        breadcrumb_items=_crumb(brand, ("設定中心", None)),
        ads_preview_pairs=_ads_preview_pairs(conn, brand_id),
        ads_updated_at=_ads_last_modified(conn, brand_id),
        **banner_ctx(request),
    ))
