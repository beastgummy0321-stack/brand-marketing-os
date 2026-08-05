# -*- coding: utf-8 -*-
"""app/ads/routes_performance.py — 成效頁、判讀、對帳、期中檢查點、CSV／手動匯入
（第 8 刀從 app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/{cycle}/performance`                    成效頁
- `/brands/{b}/ads/{cycle}/performance/hypotheses`         判讀假設結案
- `/brands/{b}/ads/{cycle}/performance/reconcile`          對帳自答
- `/brands/{b}/ads/{cycle}/revenue-reconcile`               舊網址轉址
- `/brands/{b}/ads/{cycle}/performance/data`                資料操作子頁
- `/brands/{b}/ads/{cycle}/revenue-reconcile/calibrate`     營收校準
- `/brands/{b}/ads/{cycle}/performance/shopee-code`         蝦皮期別碼
- `/brands/{b}/ads/{cycle}/reading/progress`                判讀進度頁
- `/brands/{b}/ads/{cycle}/performance/simulate`            模擬成效
- `/brands/{b}/ads/{cycle}/performance/csv`、`/manual`      成效匯入
- `/brands/{b}/ads/{cycle}/checkpoint/{kind}`                期中檢查點
- `/brands/{b}/ads/checkpoints/{id}/{action}`                檢查點紀錄管理

`orders_channel`、背景進度引擎：一律 `ads_routes.` 開頭即時查值，理由見
routes_sync.py／routes_connections.py 檔頭說明。
"""

import time
from datetime import date
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

import app.shared.web as main_mod
from app.ads import checklist as ads_checklist
from app.ads import checkpoint as ads_checkpoint
from app.ads import guardrails
from app.ads import inflation as ads_inflation
from app.ads import nextcycle
from app.ads import pacing as ads_pacing
from app.ads import performance as ads_performance
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


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/hypotheses")
async def ads_hypotheses_resolve(request: Request, brand_id: str, cycle_id: str):
    """判讀頁假設結案（GitHub issue #53）：表單欄位是 verdict_<假設id>，AI 已預填三選一，
    使用者零操作也能過——直接送出就照 AI 的預選結案。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    form = await request.form()
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    verdicts = {key[len("verdict_"):]: value for key, value in form.items()
               if key.startswith("verdict_")}
    if not verdicts:
        return main_mod.redirect_with_message(back, "沒有可結案的假設。", kind="warn")
    try:
        updated = ads_reading.resolve_hypotheses(main_mod.conn, brand_id, cycle_id, verdicts,
                                                 actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    if not updated:
        return main_mod.redirect_with_message(back, "這些假設已經結案過了。", kind="warn")
    return main_mod.redirect_with_message(back, f"已結案 {updated} 條假設。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/reconcile")
async def ads_reconcile(request: Request, brand_id: str, cycle_id: str,
                        budget_same: str = Form(""), schedule_same: str = Form(""),
                        other_campaign_running: str = Form("")):
    """對帳：自動比對總花費，加上使用者自答的三題（API 掛掉時的退路）。

    三題都沒答也可以按——自答是補充資訊，不是新的必經關卡。
    """
    main_mod.require_brand(brand_id)
    main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)

    def _tri(raw):
        return {"yes": True, "no": False}.get(raw)

    answers = {"budget_same": _tri(budget_same), "schedule_same": _tri(schedule_same),
               "other_campaign_running": _tri(other_campaign_running)}
    result = ads_reconcile_mod.run(main_mod.conn, brand_id, cycle_id, self_answers=answers)

    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"
    if not result["findings"]:
        return main_mod.redirect_with_message(back, "對過了，數字跟計畫對得上。")
    return main_mod.redirect_with_message(
        back, f"對過了，發現 {len(result['findings'])} 處跟計畫不一樣，"
              f"本期判讀標為「{result['label']}」。", kind="warn")


@router.get("/brands/{brand_id}/ads/{cycle_id}/revenue-reconcile")
async def ads_revenue_reconcile_page(request: Request, brand_id: str, cycle_id: str):
    """舊網址（票 #36）已併入資料操作子頁（GitHub issue #47：成效頁拆層），302 轉址，
    不再是旁支暗頁。"""
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return RedirectResponse(
        f"/brands/{brand_id}/ads/{cycle_id}/performance/data#revenue-reconcile",
        status_code=302)


@router.get("/brands/{brand_id}/ads/{cycle_id}/performance/data")
async def ads_performance_data_page(request: Request, brand_id: str, cycle_id: str):
    """資料操作子頁（GitHub issue #47）：匯入 CSV、手動填、蝦皮碼、對帳自答、營收校準
    全部收在這裡；成效頁本身只留判讀結論（拆層，決策 0029 第 10 點）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    reading = ads_reading.load(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_performance_data.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     summary=ads_performance.totals(conn, brand_id, cycle_id),
                     snapshots=ads_performance.list_snapshots(conn, brand_id, cycle_id),
                     is_simulation=simulation.is_simulation(cycle),
                     channel=(reading["cycle"]["result"].get("channel_comparison")
                              if reading["cycle"] else None),
                     shopee_code=ads_routes.orders_channel.get_shopee_code(conn, brand_id, cycle_id),
                     self_answer_questions=guardrails.SELF_ANSWER_QUESTIONS,
                     reconcile=ads_inflation.reconcile_cycle(conn, brand_id, cycle_id),
                     coefficient=ads_inflation.effective_coefficient(conn, brand_id),
                     cadence=ads_inflation.cadence_state(conn, brand_id),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             ("成效", f"/brands/{brand_id}/ads/{cycle_id}/performance"),
                                             ("資料操作", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/revenue-reconcile/calibrate")
async def ads_revenue_reconcile_calibrate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"
    try:
        result = ads_inflation.calibrate(main_mod.conn, brand_id, cycle_id, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, f"係數校準到第 {result['version']} 版：{result['coefficient']:.2f} 倍。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/shopee-code")
async def ads_shopee_code(request: Request, brand_id: str, cycle_id: str,
                          code: str = Form(""), redemption_count: str = Form("")):
    """蝦皮期別專屬碼＋回收數（GitHub issue #40）：全部選填，外溢下限鐵證。重新判讀後
    才會反映到通路對照卡的燈號（比照 repurchase_line／baseline_comparison 只在判讀時算）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    count_value = None
    if redemption_count.strip():
        count_value, ok = main_mod.parse_number(redemption_count)
        if not ok:
            return main_mod.redirect_with_message(back, "回收數請填數字，或留空。", kind="warn")
        count_value = int(count_value)
    try:
        ads_routes.orders_channel.set_shopee_code(main_mod.conn, brand_id, cycle_id, code=code or None,
                                       redemption_count=count_value, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已記下蝦皮期別碼資料，重新判讀後會反映在通路對照卡。")


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


@router.post("/brands/{brand_id}/ads/{cycle_id}/performance/simulate")
async def ads_simulate(request: Request, brand_id: str, cycle_id: str):
    """替模擬檔期產生假成效。數字由程式算，不讓 LLM 編。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance"
    ok, note = simulation.generate(main_mod.conn, brand_id, cycle_id, actor)
    if not ok:
        return main_mod.redirect_with_message(back, note, kind="warn")
    return main_mod.redirect_with_message(back, f"模擬成效出來了（{note}）。")


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
                                 revenue: str = Form(""), date_start: str = Form(""),
                                 date_stop: str = Form("")):
    """手動輸入。API 掛掉、CSV 也匯不進來時的最後退路。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/performance/data"

    values = {}
    for key, raw in (("spend", spend), ("impressions", impressions), ("clicks", clicks),
                     ("conversions", conversions), ("revenue", revenue)):
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


@router.get("/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}")
async def ads_checkpoint_page(request: Request, brand_id: str, cycle_id: str, kind: str):
    """期中檢查點頁（票 9）：第 3／7 天提醒卡點進來就是這裡。健康檢查模式，明文不判勝負。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    if kind not in ads_checkpoint.KIND_LABELS:
        raise main_mod.NotFoundKind("檢查點")

    history = ads_checkpoint.list_checkpoints(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_checkpoint.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     kind=kind, kind_label=ads_checkpoint.KIND_LABELS[kind],
                     latest=next((c for c in history if c["kind"] == kind), None),
                     history=[c for c in history if c["status"] == "active"],
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}"),
                                             (ads_checkpoint.KIND_LABELS[kind], None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}")
async def ads_checkpoint_run(request: Request, brand_id: str, cycle_id: str, kind: str,
                             csv_file: UploadFile = File(None), csv_text: str = Form("")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/checkpoint/{kind}"
    if kind not in ads_checkpoint.KIND_LABELS:
        raise main_mod.NotFoundKind("檢查點")

    text, decode_error = await _decode_csv_upload(csv_file, csv_text)
    if decode_error:
        return main_mod.redirect_with_message(back, decode_error, kind="warn")

    result = ads_checkpoint.run(main_mod.conn, brand_id, cycle_id, kind, actor=actor,
                                csv_text=text or None)
    if result.get("merged_into_final"):
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/performance",
            "這期已經進入期末判讀，期中檢查不用再補做，直接看期末結論。")
    if result["import_errors"]:
        return main_mod.redirect_with_message(back, result["import_errors"][0], kind="warn")
    msg = "健康檢查跑完了。" if result["data_sufficient"] else "還沒有成效資料，先匯入 CSV 再檢查。"
    return main_mod.redirect_with_message(back, msg)


@router.post("/brands/{brand_id}/ads/checkpoints/{checkpoint_id}/{action}")
async def ads_checkpoint_manage(request: Request, brand_id: str, checkpoint_id: str, action: str):
    """檢查點紀錄的封存／恢復／刪除（決策 0023 第 8 條：新資料實體必附封存＋刪除）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = (request.headers.get("referer") or f"/brands/{brand_id}/ads").split("?")[0]
    try:
        if action == "archive":
            ads_checkpoint.set_status(main_mod.conn, brand_id, checkpoint_id,
                                      status="archived", actor=actor)
            return main_mod.redirect_with_message(back, "已封存這筆檢查點紀錄。")
        if action == "restore":
            ads_checkpoint.set_status(main_mod.conn, brand_id, checkpoint_id,
                                      status="active", actor=actor)
            return main_mod.redirect_with_message(back, "已恢復這筆檢查點紀錄。")
        if action == "delete":
            ads_checkpoint.delete(main_mod.conn, brand_id, checkpoint_id, actor=actor)
            return main_mod.redirect_with_message(back, "已刪除這筆檢查點紀錄。")
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    raise main_mod.NotFoundKind("動作")


