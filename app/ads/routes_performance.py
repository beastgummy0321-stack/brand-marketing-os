# -*- coding: utf-8 -*-
"""app/ads/routes_performance.py — 成效頁、CSV／手動匯入、判讀進度頁（第 8 刀從
app/ads/routes.py 拆出；T4 廣告模組 Jinja 大清倉刪掉本檔其餘 Jinja 舊頁與表單）。

本檔現在負責的路由：
- `/brands/{b}/ads/{cycle}/performance`         成效頁（test_ads_performance.py 直打，
  `page.text` 斷言頁面內容含「擱在一旁」「資料不足」等措辭，不能只留 CSV／manual）
- `/brands/{b}/ads/{cycle}/performance/csv`、`/manual`  成效匯入（同上，測試直打舊路徑）
- `/brands/{b}/ads/{cycle}/reading/progress`    判讀進度頁（test_ads_weekly_proposal.py
  直打，背景執行＋冪等閘＋逾時同 ads_plan_progress）

T4 一併刪除：判讀假設結案（`/performance/hypotheses`）、對帳自答（`/performance/
reconcile`）、舊網址轉址（`/revenue-reconcile`）、資料操作子頁（`/performance/data`）、
營收校準（`/revenue-reconcile/calibrate`）、蝦皮期別碼（`/performance/shopee-code`）、
模擬成效（`/performance/simulate`，已有 `/api/campaigns/.../performance/simulate` 等價
端點）、期中檢查點（`/checkpoint/{kind}`，已有 `/api/campaigns/.../checkpoint/{kind}`
等價端點）、檢查點紀錄管理（`/checkpoints/{id}/{action}`）——測試與 React 都已不再打
這批舊路徑。

`orders_channel`、背景進度引擎（app/ads/routes_progress.py）：一律 `ads_routes.`
開頭即時查值，理由見 routes_progress.py 檔頭說明。
"""

import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

import app.shared.web as main_mod
from app.ads import checklist as ads_checklist
from app.ads import guardrails
from app.ads import nextcycle
from app.ads import performance as ads_performance
from app.ads import pacing as ads_pacing
from app.ads import reading as ads_reading
from app.ads import reconcile as ads_reconcile_mod
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.ads import settlement as ads_settlement
from app.ads import simulation
from app.ads.routes_common import _crumb, _cycle_progress_items, _cycle_view, _require_cycle

router = APIRouter()

# 判讀沒有細分階段可回報（ads_reading.run／finalize 不接受 on_stage），只借用同一套
# 背景執行／冪等閘／逾時機制，不顯示 progress_rows（沿用原本就沒有階段清單的畫面）。
_READING_STAGES = [("run", "判讀中")]


@router.get("/brands/{brand_id}/ads/{cycle_id}/performance")
async def ads_performance_page(request: Request, brand_id: str, cycle_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    snapshots = ads_performance.list_snapshots(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_performance.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     summary=ads_performance.totals(conn, brand_id, cycle_id),
                     quarantined=[s for s in snapshots if s["quarantined"]],
                     reconciliation=ads_reconcile_mod.load(conn, brand_id, cycle_id),
                     self_answer_questions=guardrails.SELF_ANSWER_QUESTIONS,
                     reading=ads_reading.load(conn, brand_id, cycle_id),
                     prediction=ads_reading.prediction_settlement(conn, brand_id, cycle),
                     repurchase_dissents=[
                         d for d in ads_repo.list_dissents(conn, brand_id, cycle_id, status="pending")
                         if d["target_type"] == "repurchase_breakeven"
                     ],
                     settlement=ads_settlement.load_snapshot(conn, brand_id, cycle_id),
                     shopee_code=ads_routes.orders_channel.get_shopee_code(conn, brand_id, cycle_id),
                     next_cycle=nextcycle.load(conn, brand_id, cycle_id),
                     checklist=ads_checklist.completeness(conn, brand_id, cycle_id),
                     is_simulation=simulation.is_simulation(cycle),
                     simulation_note=simulation.SIMULATION_NOTE,
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     errors={}, **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/{cycle_id}/reading/progress")
def ads_reading_progress(request: Request, brand_id: str, cycle_id: str,
                         run: Optional[str] = None, final: Optional[str] = None):
    """判讀：狀態由規則判，LLM 只把結論翻成人話（決策 0016 硬性原則 4）。

    final=1 是期末＋14 天最終結算入口（票 #38，決策 0025 判讀節奏第 5 點）：重用同一條
    等待頁與 run 流程，只是跑完後多把檔期標成 CLOSED——不為此另開一份等待頁模板。

    修憲落地 M3：同樣改背景執行緒＋冪等閘＋逾時，理由見 ads_plan_progress。
    """
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    result_url = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    is_final = final == "1"
    heading = "正在做最終結算" if is_final else "正在判讀這期的成效"
    progress_key = ads_routes._progress_key("reading", brand_id, cycle_id)

    if run != "1":
        run_url = f"{request.url.path}?run=1" + ("&final=1" if is_final else "")
        ads_routes._progress_touch(progress_key, _READING_STAGES)
        return ads_routes._render_wait_page(
            request, brand, heading=heading, lede="通常要 20 到 40 秒。", run_url=run_url,
            leave_url=result_url, breadcrumb_tail="判讀中")

    def work(on_stage):
        if is_final:
            return ads_reading.finalize(main_mod.conn, brand_id, cycle_id, actor)
        return ads_reading.run(main_mod.conn, brand_id, cycle_id, actor)

    entry = ads_routes._progress_start(progress_key, _READING_STAGES, work)

    if entry["status"] != "done":
        if time.time() - entry["started_at"] > ads_routes._PROGRESS_TIMEOUT_SECONDS:
            ads_routes._progress_clear(progress_key)
            return main_mod.redirect_with_message(
                result_url, "AI 這次沒有在時間內回應。你的資料都還在，沒有掉。"
                           "可以再試一次，或先跳過這一步。", kind="warn")
        run_url = f"{request.url.path}?run=1" + ("&final=1" if is_final else "")
        return ads_routes._render_wait_page(
            request, brand, heading=heading, lede="通常要 20 到 40 秒。", run_url=run_url,
            leave_url=result_url, breadcrumb_tail="判讀中")

    outcome_kind, payload = entry["result"]
    ads_routes._progress_clear(progress_key)
    if outcome_kind == "error":
        return main_mod.redirect_with_message(result_url, payload, kind="warn")
    ok, err = payload
    if not ok:
        return main_mod.redirect_with_message(result_url, err, kind="warn")
    ok_message = "最終結算完成，這期正式結案。" if is_final else "判讀好了。"
    return main_mod.redirect_with_message(result_url, ok_message)


async def _decode_csv_upload(csv_file: Optional[UploadFile], csv_text: str) -> tuple:
    """上傳檔案或直接貼內容都可以；回傳 (內容文字, 編碼錯誤訊息或 None)。"""
    if csv_file is not None and csv_file.filename:
        raw = await csv_file.read()
        for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
            try:
                return raw.decode(encoding), None
            except UnicodeDecodeError:
                continue
        return "", "這個檔案的文字編碼讀不出來，請用 Excel 另存成 UTF-8 的 CSV。"
    return csv_text, None


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/csv")
async def ads_performance_csv(request: Request, brand_id: str, cycle_id: str,
                              csv_file: UploadFile = File(None), csv_text: str = Form("")):
    """CSV 匯入。上傳檔案或直接貼內容都可以。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    text, decode_error = await _decode_csv_upload(csv_file, csv_text)
    if decode_error:
        return main_mod.redirect_with_message(back, decode_error, kind="warn")

    # 缺日期欄的資料列要退回今天，不能留空字串（issue #23 bug 4）
    result = ads_performance.import_csv(main_mod.conn, brand_id, cycle_id, text, actor=actor,
                                        today=date.today().isoformat())
    if result.errors:
        return main_mod.redirect_with_message(back, result.errors[0], kind="warn")

    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    ads_pacing.check_cycle(main_mod.conn, brand_id, cycle_id)  # 票 08：新數據落地後判一次步調
    msg = f"匯入 {result.imported} 筆成效資料。"
    if result.quarantined:
        msg += f"其中 {result.quarantined} 筆數字不合理，先擱在一旁不列入計算。"
    return main_mod.redirect_with_message(back, msg)


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/manual")
async def ads_performance_manual(request: Request, brand_id: str, cycle_id: str,
                                 spend: str = Form(""), impressions: str = Form(""),
                                 clicks: str = Form(""), conversions: str = Form(""),
                                 revenue: str = Form(""), reach: str = Form(""),
                                 date_start: str = Form(""), date_stop: str = Form("")):
    """手動輸入。API 掛掉、CSV 也匯不進來時的最後退路。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    values = {}
    for key, raw in (("spend", spend), ("impressions", impressions), ("clicks", clicks),
                     ("conversions", conversions), ("revenue", revenue), ("reach", reach)):
        value, ok = main_mod.parse_number(raw)
        if not ok:
            return main_mod.redirect_with_message(back, "數字欄位請只填數字。", kind="warn")
        values[key] = value
    values["date_start"] = date_start or None
    values["date_stop"] = date_stop or None

    result = ads_performance.import_manual(main_mod.conn, brand_id, cycle_id, values,
                                           actor=actor)
    if result.errors:
        return main_mod.redirect_with_message(back, result.errors[0], kind="warn")
    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    ads_pacing.check_cycle(main_mod.conn, brand_id, cycle_id)  # 票 08：新數據落地後判一次步調
    return main_mod.redirect_with_message(back, "記下來了。")

