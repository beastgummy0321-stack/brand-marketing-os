# -*- coding: utf-8 -*-
"""app/ads/routes_sync.py — 首頁、歷期戰績、Meta／GA4 同步與回填、待認領（第 8 刀從
app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads`                           廣告首頁
- `/brands/{b}/ads/history`                   歷期戰績
- `/brands/{b}/ads/sync`                      Meta 立即同步
- `/brands/{b}/ads/connections/meta/backfill` Meta 回填精靈
- `/brands/{b}/ads/claims`、`/claims/{id}/{action}` 待認領廣告活動
- `/brands/{b}/ads/ga4`、`/ga4/sync`          GA4 同步結果與立即同步
- `/brands/{b}/ads/connections/ga4/backfill`  GA4 回填精靈
- `/brands/{b}/ads/reminders/{id}/dismiss`    收起廣告到期等提醒

背景進度引擎（`_progress_touch`／`_progress_start`／`_render_wait_page` 等）與
`_PROGRESS_TIMEOUT_SECONDS` 留在 app/ads/routes.py 那份匯總檔，這裡一律
`ads_routes.` 開頭即時查值——不能 `from app.ads.routes import X` 把名字綁死，
main.py 與 test_ads_progress_background.py 對這份狀態的動態注入／覆寫才吃得到。
"""

import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import ga4_sync
from app.ads import onboarding
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads import stages
from app.ads import sync as ads_sync
from app.ads.routes_common import _crumb, _cycle_view, _history_trend_rows, _hub_stage_info, _latest_closed_summary

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


@router.get("/brands/{brand_id}/ads")
async def ads_home(request: Request, brand_id: str):
    """廣告首頁（修憲落地 V3，遷 B｜工作台式，決策 0033／0038）：卡片牆拿掉，改成單欄
    清單——進行中檔期／最近結案的檔期兩塊摘要（`kind=content`，不計入 §20.1 規則 1 的
    主欄 ≤5 上限）＋底部開新檔期等動作按鈕。全部檔期清單仍在 /ads/history，Meta 同步與
    待認領提醒仍在 /ads/connections（#44），本頁不留操作列。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycles = [_cycle_view(conn, brand_id, c) for c in ads_repo.list_cycles(conn, brand_id)]
    in_progress = [c for c in cycles if c["status"] != "CLOSED"]
    primary_cycle = in_progress[0] if in_progress else None  # list_cycles 已依 start_date DESC 排序
    return main_mod.templates.TemplateResponse(
        request, "ads_home.html",
        main_mod.ctx(request, brand=brand,
                     has_cycles=bool(cycles) or ads_repo.list_archived_cycles(conn, brand_id) != [],
                     primary_cycle=primary_cycle,
                     stage=_hub_stage_info(conn, brand_id, primary_cycle) if primary_cycle else None,
                     stage_total=len(stages.STAGE_LABELS),
                     other_in_progress_count=len(in_progress) - 1 if in_progress else 0,
                     latest_closed=_latest_closed_summary(conn, brand_id, cycles),
                     inbox_count=len(main_mod.core_interrupts.list_open(conn, brand_id=brand_id)),
                     nav_current='ads',
                     breadcrumb_items=_crumb(brand),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/history")
async def ads_history(request: Request, brand_id: str):
    """歷期戰績（GitHub issue #45）：全部檔期清單，分進行中／已結案／已封存三段。
    原本廣告首頁表格＋底部封存收合區的內容搬到這裡，恢復／永久刪除沿用既有路由，行為不變。
    註冊在 /ads/{cycle_id} 萬用路由之前，避免被吃掉（比照 #44 的 /ads/connections）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycles = [_cycle_view(conn, brand_id, c) for c in ads_repo.list_cycles(conn, brand_id)]
    archived_cycles = [_cycle_view(conn, brand_id, c)
                       for c in ads_repo.list_archived_cycles(conn, brand_id)]
    closed_cycles = [c for c in cycles if c["status"] == "CLOSED"]
    return main_mod.templates.TemplateResponse(
        request, "ads_history.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     in_progress_cycles=[c for c in cycles if c["status"] != "CLOSED"],
                     closed_cycles=closed_cycles,
                     trend_rows=_history_trend_rows(conn, brand_id, closed_cycles),
                     archived_cycles=archived_cycles,
                     breadcrumb_items=_crumb(brand, ("歷期戰績", None)),
                     **main_mod.banner_ctx(request)),
    )


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


@router.post("/brands/{brand_id}/ads/sync")
async def ads_sync_now(request: Request, brand_id: str):
    """從 Meta 抓一次資料回來。沒設定連線就給人話提示，不當機（鐵則 16）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    back = f"/brands/{brand_id}/ads"

    if not ads_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            back, "還沒設定 Meta 廣告帳號的唯讀連線，先去設定頁填一下。", kind="warn")

    result = ads_sync.sync_account(conn, actor)
    if result.error:
        return main_mod.redirect_with_message(back, result.error, kind="warn")

    return main_mod.redirect_with_message(back, "、".join(_describe_sync_result(result)) + "。")


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


@router.get("/brands/{brand_id}/ads/claims")
async def ads_claims(request: Request, brand_id: str):
    """待認領的廣告活動。只列「猜是這個品牌的」與「完全沒歸屬的」，
    已認領給別的品牌的不會出現在這裡（鐵則 13 品牌隔離）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    return main_mod.templates.TemplateResponse(
        request, "ads_claims.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     pending=ads_sync.list_pending_claims(conn, brand_id),
                     breadcrumb_items=_crumb(brand, ("還沒認領的廣告", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/claims/{discovered_id}/{action}")
async def ads_claim_action(request: Request, brand_id: str, discovered_id: str, action: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    back = f"/brands/{brand_id}/ads/claims"
    try:
        if action == "claim":
            row = ads_sync.claim(conn, brand_id, discovered_id, actor)
            msg = f"「{row['campaign_name']}」記成這個品牌的了，它的成效數字會算進來。"
        elif action == "ignore":
            ads_sync.ignore(conn, brand_id, discovered_id, actor)
            msg = "好，這個活動不算這個品牌的。"
        else:
            raise main_mod.NotFoundKind("頁面")
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, msg)


@router.get("/brands/{brand_id}/ads/ga4")
async def ads_ga4_page(request: Request, brand_id: str):
    """GA4 同步結果頁：來源／媒介 × 工作階段／轉換／收益，含 purchase 事件驗證狀態。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    return main_mod.templates.TemplateResponse(
        request, "ads_ga4.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     ga4_configured=ga4_sync.is_configured(conn),
                     summary_rows=ga4_sync.latest_summary(conn, brand_id),
                     sync_status=ga4_sync.get_sync_status(conn, brand_id),
                     breadcrumb_items=_crumb(brand, ("GA4 網站數據", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/ga4/sync")
def ads_ga4_sync_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """從 GA4 抓一次最新資料。沿用既有等待頁模式（決策 0025 補遺第 6 點：設定耗時
    以熟悉 Google Cloud 者為前提，抓資料本身另計，不長，仍走等待頁誠實顯示已等秒數）。

    修憲落地 M3：同樣改背景執行緒＋冪等閘＋逾時，理由見 ads_plan_progress——GA4
    同步不花錢，但一樣會凍住畫面、一樣可能被 F5 重複觸發。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    result_url = f"/brands/{brand_id}/ads/ga4"

    if not ga4_sync.is_configured(conn):
        return main_mod.redirect_with_message(
            result_url, "還沒設定 GA4 服務帳戶金鑰，先去設定頁填一下。", kind="warn")

    progress_key = ads_routes._progress_key("ga4", brand_id, "_brand_")
    if run != "1":
        entry = ads_routes._progress_touch(progress_key, _GA4_SYNC_STAGES)
        return ads_routes._render_wait_page(
            request, brand, heading="正在從 GA4 抓最新資料",
            lede="這次會抓來源／媒介的工作階段、轉換與收益。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 同步中",
            progress_rows=ads_routes._progress_definition_rows(_GA4_SYNC_STAGES, "ga4", entry))

    def work(on_stage):
        return ga4_sync.sync_brand(main_mod.conn, brand_id, actor, on_stage=on_stage)

    entry = ads_routes._progress_start(progress_key, _GA4_SYNC_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "GA4 這次沒有在時間內回應，可以再試一次。", kind="warn")
        return ads_routes._render_wait_page(
            request, brand, heading="正在從 GA4 抓最新資料",
            lede="這次會抓來源／媒介的工作階段、轉換與收益。",
            run_url=f"{request.url.path}?run=1", leave_url=result_url,
            breadcrumb_tail="GA4 同步中",
            progress_rows=ads_routes._progress_definition_rows(_GA4_SYNC_STAGES, "ga4", entry))

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    result = payload
    if result.error:
        return main_mod.redirect_with_message(result_url, result.error, kind="warn")
    return main_mod.redirect_with_message(
        result_url, "、".join(_describe_ga4_result(result)) + "。")


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


@router.post("/brands/{brand_id}/ads/reminders/{reminder_id}/dismiss")
async def ads_reminder_dismiss(request: Request, brand_id: str, reminder_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    onboarding.dismiss(main_mod.conn, brand_id, reminder_id, actor=actor)
    back = (request.headers.get("referer") or f"/brands/{brand_id}/ads").split("?")[0]
    return main_mod.redirect_with_message(back, "好，這則提醒收起來了。")


