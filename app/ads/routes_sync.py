# -*- coding: utf-8 -*-
"""app/ads/routes_sync.py — Meta／GA4 回填精靈（第 8 刀從 app/ads/routes.py 拆出；T4
廣告模組 Jinja 大清倉刪掉本檔其餘 Jinja 舊頁與表單）。

本檔現在負責的路由：
- `/brands/{b}/ads/connections/meta/backfill` Meta 回填精靈（test_ads_backfill.py 直打）
- `/brands/{b}/ads/connections/ga4/backfill`  GA4 回填精靈（test_ads_backfill.py 直打）

T4 一併刪除：廣告首頁（`/brands/{b}/ads`）、歷期戰績（`/ads/history`）、Meta 立即同步
（`/ads/sync`，已有 `/api/dashboard/brands/{id}/sync` 等價端點）、待認領廣告活動
（`/ads/claims`、`/claims/{id}/{action}`，已有 `/api/campaigns/brands/{id}/claims`
等價端點）、GA4 同步結果頁與立即同步（`/ads/ga4`、`/ga4/sync`，已有
`/api/campaigns/brands/{id}/sync/ga4` 等價端點）、提醒收起（`/ads/reminders/{id}/
dismiss`，目前無 React 等價功能，測試也不打）——測試與 React 都已不再打這批舊路徑。

背景進度引擎（`_progress_touch`／`_progress_start`／`_render_wait_page` 等）在
app/ads/routes_progress.py，這裡一律 `ads_routes.` 開頭即時查值——不能
`from app.ads.routes_progress import X` 把名字綁死，main.py 與
test_ads_progress_background.py 對這份狀態的動態注入／覆寫才吃得到。
"""

import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import ga4_sync
from app.ads import routes as ads_routes
from app.ads import sync as ads_sync

router = APIRouter()

_GA4_SYNC_STAGES = [
    ("connect", "連線 GA4 服務帳戶"),
    ("fetch", "抓取來源／媒介成效與 purchase 事件"),
    ("save", "寫入彙總表"),
]
# 回填（票 F3，決策 0039 第 3 條）：只有精靈用，日常同步（ads_sync_now／
# ads_ga4_sync_progress）維持既有行為與 30 天視窗不動。sync_account 不接受 on_stage，
# 比照判讀借用單一階段；GA4 sync_brand 有 on_stage，沿用既有 _GA4_SYNC_STAGES 三階段。
_META_BACKFILL_STAGES = [("run", "回填 Meta 廣告成效中")]
BACKFILL_MONTHS = 12


def _describe_sync_result(result) -> list:
    """SyncResult → 人話清單（票 F3 從 ads_sync_now 抽出，回填路由共用同一份措辭，
    不重寫第二份）。"""
    parts = [f"抓回 {result.snapshots} 筆成效"]
    if result.discovered:
        parts.append(f"發現 {result.discovered} 個新的廣告活動要你認領")
    if result.skipped_unclaimed:
        parts.append(f"{result.skipped_unclaimed} 筆因為還沒認領歸屬先沒收")
    if result.skipped_duplicate:
        parts.append(f"已略過重複 {result.skipped_duplicate} 列")
    if result.quarantined:
        parts.append(f"{result.quarantined} 筆數字不合理已擱置")
    return parts


@router.get("/brands/{brand_id}/ads/connections/meta/backfill")
def ads_meta_backfill_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """回填精靈第①格（票 F3，決策 0039 第 3 條）：一鍵把 Meta 回填 12 個月，僅精靈用——
    日常同步（`/ads/sync`）維持 30 天視窗不動。背景執行＋只讀進度頁＋F5 冪等，
    比照 ads_ga4_sync_progress 同一套機制；sync_account 沒有 on_stage，借用單一階段
    （比照判讀 _READING_STAGES 的先例）。"""
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/connections"

    if not ads_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 Meta 廣告帳號的唯讀連線，先去設定頁填一下。", kind="warn")

    progress_key = ads_routes._progress_key("meta_backfill", brand_id, "_brand_")
    if run != "1":
        entry = ads_routes._progress_touch(progress_key, _META_BACKFILL_STAGES)
        return ads_routes._render_wait_page(
            request, brand, heading="正在回填 Meta 廣告成效",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的資料。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="Meta 回填中",
            progress_rows=ads_routes._progress_definition_rows(_META_BACKFILL_STAGES, "meta_backfill", entry))

    def work(on_stage):
        since, until, actual_months = ads_sync.backfill_range(BACKFILL_MONTHS)
        result = ads_sync.sync_account(main_mod.conn, actor, since=since, until=until)
        return result, actual_months

    entry = ads_routes._progress_start(progress_key, _META_BACKFILL_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "Meta 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return ads_routes._render_wait_page(
            request, brand, heading="正在回填 Meta 廣告成效",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的資料。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="Meta 回填中",
            progress_rows=ads_routes._progress_definition_rows(_META_BACKFILL_STAGES, "meta_backfill", entry))

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result, actual_months = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    parts = [f"實際拿到 {actual_months} 個月"] + _describe_sync_result(result)
    return main_mod.redirect_with_message(result_url, "、".join(parts) + "。")


def _describe_ga4_result(result) -> list:
    """GA4SyncResult → 人話清單（票 F3 從 ads_ga4_sync_progress 抽出，回填路由共用同一份
    措辭，不重寫第二份）。"""
    parts = [f"抓回 {result.rows} 列來源／媒介資料"]
    if result.purchase_event_seen:
        parts.append("purchase 事件有收到")
    else:
        parts.append("purchase 事件目前沒收到，確認 GA4 轉換設定或看設定教學")
    return parts


@router.get("/brands/{brand_id}/ads/connections/ga4/backfill")
def ads_ga4_backfill_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """回填精靈第③格（票 F3，決策 0039 第 3 條）：一鍵把 GA4 回填 12 個月，僅精靈用——
    日常同步（`/ads/ga4/sync`）維持 30 天視窗不動。GA4 沒有 Meta 那種寫死的官方月數
    上限可夾（見 ga4_sync.py 常數區註解：天花板是 property 建立日，系統查不到），
    優雅降級＝照樣送出 12 個月請求，GA4 對還不存在的日子誠實回傳 0 而不是報錯。
    背景執行＋只讀進度頁＋F5 冪等，沿用既有 _GA4_SYNC_STAGES 三階段。"""
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/connections"

    if not ga4_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 GA4 服務帳戶金鑰，先去設定頁填一下。", kind="warn")

    progress_key = ads_routes._progress_key("ga4_backfill", brand_id, "_brand_")
    if run != "1":
        entry = ads_routes._progress_touch(progress_key, _GA4_SYNC_STAGES)
        return ads_routes._render_wait_page(
            request, brand, heading="正在回填 GA4 網站數據",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的來源／媒介彙總。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 回填中",
            progress_rows=ads_routes._progress_definition_rows(_GA4_SYNC_STAGES, "ga4_backfill", entry))

    def work(on_stage):
        until = date.today().isoformat()
        since = ads_sync.months_before(until, BACKFILL_MONTHS)
        return ga4_sync.sync_brand(main_mod.conn, brand_id, actor, since=since, until=until,
                                   on_stage=on_stage)

    entry = ads_routes._progress_start(progress_key, _GA4_SYNC_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "GA4 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return ads_routes._render_wait_page(
            request, brand, heading="正在回填 GA4 網站數據",
            lede=f"這次會嘗試抓回過去 {BACKFILL_MONTHS} 個月的來源／媒介彙總。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 回填中",
            progress_rows=ads_routes._progress_definition_rows(_GA4_SYNC_STAGES, "ga4_backfill", entry))

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    parts = [f"實際回填 {BACKFILL_MONTHS} 個月"] + _describe_ga4_result(result)
    return main_mod.redirect_with_message(result_url, "、".join(parts) + "。")
