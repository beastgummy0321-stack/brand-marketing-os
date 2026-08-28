"""app/dashboard/pinned_views.py — 駕駛艙成效釘選區（票 B4R-cockpit-pins 接線，契約
`.scratch/grill/GRILL-B4R-performance.md` 第一節，型別逐欄對照
`frontend/src/lib/pinnedViewsApi.ts`）。

目錄固定 5 筆（R3-1 定案），釘選清單存進既有 `app_setting` 鍵值表（`app.core.settings`
既有 `get_setting`／`set_setting`，不新增資料表），鍵為 `dashboard_pinned_views:{brand_id}`
——單機單人，不分使用者（見 grill「拿不準的點」第 3 條）。

對外進入點：`PINNED_VIEW_CATALOG`、`get_pinned_views()`、`set_pinned_views()`、
`build_performance_view()`。誰依賴它：`app/dashboard/routes_pinned_views_api.py`。
"""

import json
from datetime import date

from app.ads import codes as ads_codes
from app.ads import health_lights as ads_health_lights
from app.ads import pacing as ads_pacing
from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads.routes_common import _hub_stage_info
from app.core import rule_cards
from app.core import settings as core_settings
from app.dashboard.repository import _latest_cycle

PINNED_VIEW_LIMIT = 5

PINNED_VIEW_CATALOG = [
    {"key": "ad_overview", "label": "廣告總覽"},
    {"key": "post_placeholder", "label": "貼文（短影音）成效"},
    {"key": "weekly_burn", "label": "本週燒錢與進度"},
    {"key": "attribution", "label": "訂單歸因"},
    {"key": "health_lights", "label": "檔期健康燈號"},
]
_VALID_KEYS = {c["key"] for c in PINNED_VIEW_CATALOG}


def _setting_key(brand_id: str) -> str:
    return f"dashboard_pinned_views:{brand_id}"


def get_pinned_views(conn, brand_id: str) -> list:
    """未存過就回目錄全部 5 筆（S3P：首次進駕駛艙全部預設釘選）。"""
    raw = core_settings.get_setting(conn, _setting_key(brand_id))
    if not raw:
        return [c["key"] for c in PINNED_VIEW_CATALOG]
    try:
        views = json.loads(raw)
    except (TypeError, ValueError):
        return [c["key"] for c in PINNED_VIEW_CATALOG]
    return [v for v in views if v in _VALID_KEYS]


def set_pinned_views(conn, brand_id: str, views: list) -> None:
    core_settings.set_setting(conn, _setting_key(brand_id), json.dumps(views, ensure_ascii=False))


def _ad_overview(conn, brand_id: str, cycle: dict) -> dict:
    totals = ads_performance.totals(conn, brand_id, cycle["id"])
    summary = {
        "spend": totals["spend"], "impressions": totals["impressions"], "reach": totals["reach"],
        "clicks": totals["clicks"], "conversions": totals["conversions"], "revenue": totals["revenue"],
        "kpis": totals["kpis"],
        "discarded_rows": sum(1 for s in ads_performance.list_snapshots(conn, brand_id, cycle["id"])
                              if s["quarantined"]),
    }
    reading = ads_reading.load(conn, brand_id, cycle["id"])["cycle"]
    # B0-15：駕駛艙同時有好幾個進行中檔期時，「看這期完整作戰室」跟「下一步指南」的連結
    # 可能各指向不同檔期，畫面卻沒寫是哪一期——附上日期區間，使用者才知道點下去是哪一期。
    return {"kind": "ad_overview", "cycle_id": cycle["id"], "summary": summary,
            "reading_status": reading["status"] if reading else None,
            "cycle_label": f"{cycle['start_date']} ～ {cycle['end_date']}"}


def _weekly_burn(conn, brand_id: str, cycle: dict) -> dict:
    threshold = rule_cards.get_value(conn, brand_id, "pacing", "deviation_threshold_ratio")
    spend = ads_performance.totals(conn, brand_id, cycle["id"])["spend"]
    result = ads_pacing.classify(budget=cycle["budget"], spend=spend, start_date=cycle["start_date"],
                                 end_date=cycle["end_date"], today=date.today().isoformat(),
                                 threshold_pct=threshold)
    # B0-05：end_date 已過但還沒收帳時 `_hub_stage_info` 的 days_left 回 None（倒數已經不
    # 成立），但這顆釘選卡的契約是 number（非 nullable）——這裡不是本票要修的畫面，維持
    # 既有的「夾到 0」行為，別把 None 傳給沒準備好接 null 的前端型別。
    days_left = _hub_stage_info(conn, brand_id, cycle)["days_left"] or 0
    return {"kind": "weekly_burn", "cycle_id": cycle["id"], "status": result["status"],
            "time_progress": result["time_progress"], "budget_progress": result["budget_progress"],
            "days_left": days_left}


def _attribution(conn, brand_id: str, cycle: dict) -> dict:
    summary = ads_codes.attribution_summary(conn, brand_id, cycle["id"])
    return {"kind": "attribution", "cycle_id": cycle["id"], **summary}


def _health_lights(conn, brand_id: str, cycle: dict) -> dict:
    lights = ads_health_lights.compute(conn, brand_id, cycle["id"])
    return {"kind": "health_lights", "cycle_id": cycle["id"], **lights}


_BUILDERS = {"ad_overview": _ad_overview, "weekly_burn": _weekly_burn,
             "attribution": _attribution, "health_lights": _health_lights}


def build_performance_view(conn, brand_id: str, view_key: str) -> dict | None:
    """`None`＝這個品牌完全沒開過任何檔期（S3P.13）；`post_placeholder` 是固定留位空態，
    恆定顯示，不查資料庫（R2-1 決定）。"""
    if view_key == "post_placeholder":
        return {"kind": "post_placeholder"}
    if view_key not in _BUILDERS:
        return None
    cycle = _latest_cycle(conn, brand_id)
    if cycle is None:
        return None
    return _BUILDERS[view_key](conn, brand_id, cycle)
