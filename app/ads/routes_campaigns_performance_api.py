"""app/ads/routes_campaigns_performance_api.py — S8 成效＋覆盤 JSON API（票 B4-warroom 接線，
契約 `.scratch/grill/GRILL-B4-warroom.md`＋`GRILL-B4R-performance.md`，型別逐欄對照
`frontend/src/lib/warroomApi.ts`）。

`compile_closing_review()`（S8.59）只有這一個呼叫端，薄聚合既有四塊資料，不獨立成
業務模組檔（ponytail：只有一個呼叫端就直接寫在這裡，出現第 2 個真實呼叫端才抽）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

from datetime import UTC, date, datetime

from fastapi import APIRouter, File, Request, UploadFile

import app.shared.web as main_mod
from app.ads import bottleneck as ads_bottleneck
from app.ads import codes as ads_codes
from app.ads import health_lights as ads_health_lights
from app.ads import nextcycle, performance_batches, simulation, target_cpa, weekly_proposals
from app.ads import pacing as ads_pacing
from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import settlement as ads_settlement
from app.ads.routes_common import OBJECTIVE_LABELS, _require_cycle
from app.brand_intelligence.repository_learning_text import collapse_learnings
from app.core import rule_cards
from app.shared.web import JSONResponse

router = APIRouter()


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _dict_note(d) -> "str | None":
    if not isinstance(d, dict):
        return None
    return d.get("note") or d.get("reason")


# 票 F1：原本這裡自己有一份 `_late_data_rerun`——「重判＋補建卡」的邏輯已經搬到
# `weekly_proposals.rerun_after_late_data()`，讓拖檔口（`app/orders/dispatch.py`）跟
# 批次刪除的非結案分支也能共用同一個出處，不用各自重寫一份、各自漏掉 generate()。


# ---- 成效（S8.51-58） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/performance")
async def performance_get(brand_id: str, cycle_id: str, request: Request):
    main_mod.require_brand(brand_id, main_mod.require_actor(request))
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)

    totals = ads_performance.totals(conn, brand_id, cycle_id)
    snapshots = ads_performance.list_snapshots(conn, brand_id, cycle_id)
    last_synced_at = max(
        (s["snapshot_taken_at"] for s in snapshots if s.get("snapshot_taken_at")), default=None)
    # `PerformanceSummary | null`（`warroomApi.ts`）：一筆成效資料都沒有時回 null，
    # 前端顯示「資料不足，還沒有可以算的成效數字」空狀態，不是全 0 的表格（鐵則 16）。
    summary = None if totals["rows"] == 0 else {
        "spend": totals["spend"], "impressions": totals["impressions"], "reach": totals["reach"],
        "clicks": totals["clicks"], "conversions": totals["conversions"], "revenue": totals["revenue"],
        "kpis": totals["kpis"], "discarded_rows": sum(1 for s in snapshots if s["quarantined"]),
    }

    loaded = ads_reading.load(conn, brand_id, cycle_id)
    cycle_reading = loaded["cycle"]
    reading = None
    confidence_label = "這期還沒有成效判讀，可信度未知。"
    if cycle_reading:
        result = cycle_reading["result"] or {}
        reading = {
            "status": cycle_reading["status"], "status_label": cycle_reading["status_label"],
            "statistical_level": result.get("statistical_level"),
            "statistical_level_label": result.get("statistical_level_label"),
            "llm_explanation": cycle_reading.get("llm_explanation") or "",
            "reasons": result.get("reasons") or [],
            "asset_breakdown": result.get("asset_breakdown") or [],
        }
        confidence_label = f"{result.get('statistical_level_label', '')}尚未完成對帳三題自答，可信度中等".strip()

    # 錢卡在哪一關（票 C2-01）：跟判讀狀態並列，還沒有判讀時不算——沒有判讀就沒有「這期
    # 賺不賺」的結論，瓶頸判讀依附在這個結論底下才有意義。
    bottleneck = None
    if cycle_reading:
        threshold_pct = rule_cards.get_value(conn, brand_id, "pacing", "deviation_threshold_ratio")
        pacing_result = ads_pacing.classify(
            budget=cycle["budget"], spend=totals["spend"], start_date=cycle["start_date"],
            end_date=cycle["end_date"], today=date.today().isoformat(), threshold_pct=threshold_pct)
        baseline = ads_reading.brand_baseline(conn, brand_id, exclude_cycle_id=cycle_id)
        totals["max_frequency"] = ads_performance.max_frequency(conn, brand_id, cycle_id)
        bottleneck = ads_bottleneck.diagnose(totals, baseline=baseline, brand_id=brand_id,
                                             pacing_status=pacing_result["status"], conn=conn)

    return _envelope({"summary": summary, "reading": reading, "bottleneck": bottleneck,
                      "confidence_label": confidence_label, "last_synced_at": last_synced_at})


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/simulate")
async def performance_simulate(request: Request, brand_id: str, cycle_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    _require_cycle(brand_id, cycle_id)
    ok, note = simulation.generate(main_mod.conn, brand_id, cycle_id, str(actor.user_id))
    if not ok:
        return _error(400, note)
    return JSONResponse(None, status_code=204)


_MANUAL_NUMBER_FIELDS = ("spend", "impressions", "clicks", "conversions", "revenue", "reach")


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/manual")
async def performance_manual(request: Request, brand_id: str, cycle_id: str):
    """使用者自己填成效數字——API 掛掉、CSV 也匯不進來時的最後退路（原
    `ads_performance_manual`，T4 清倉刪掉 Jinja 路由後恢復成 JSON 版本）。"""
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    _require_cycle(brand_id, cycle_id)
    actor_id = str(actor.user_id)
    body = await request.json()

    values = {}
    for key in _MANUAL_NUMBER_FIELDS:
        value, ok = main_mod.parse_number(body.get(key))
        if not ok:
            return _error(400, "數字欄位請只填數字。")
        values[key] = value
    values["date_start"] = body.get("date_start") or None
    values["date_stop"] = body.get("date_stop") or None

    result = ads_performance.import_manual(main_mod.conn, brand_id, cycle_id, values, actor=actor_id)
    if result.errors:
        return _error(400, result.errors[0])

    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    ads_pacing.check_cycle(main_mod.conn, brand_id, cycle_id)  # 新數據落地後判一次步調
    # 票 11 D2：跟 CSV 路由同一個回應形狀，讓面板秀出「跳過幾筆」——不然使用者以為
    # 手動填一定會生效，實則被去重悄悄吃掉還不知道。
    return JSONResponse({
        "imported": result.imported,
        "quarantined": result.quarantined,
        "skipped": result.skipped,
        "matched_assets": result.matched_assets,
        "unmatched_columns": result.unmatched_columns,
        "warnings": [],
        **weekly_proposals.rerun_after_late_data(main_mod.conn, brand_id, cycle_id, actor_id),
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/csv")
async def performance_csv(request: Request, brand_id: str, cycle_id: str,
                          perf_file: UploadFile = File(None)):
    """Meta CSV 匯出檔匯入（原 `ads_performance_csv`，同上恢復成 JSON 版本）。"""
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    _require_cycle(brand_id, cycle_id)

    if perf_file is None or not perf_file.filename:
        return _error(400, "沒有選到檔案。")
    content = await perf_file.read()
    if not content:
        return _error(400, "沒有選到檔案。")
    # Windows 匯出常見 cp950/big5（繁體中文帳號匯出的 Meta CSV 常見）——errors="replace" 會把中文標題變成
    # U+FFFD 亂碼，欄名對不到 COLUMN_ALIASES，默默回 imported=0（還是 200），使用者以為成功實則沒匯進任何東西。
    # 四種編碼視圖依序解，都失敗才回 400（對照 e48c6b8^:app/ads/routes_performance.py 的 _decode_csv_upload，
    # 同一套現成的已驗證行為，不發明新的）。
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return _error(400, "這個檔案的文字編碼讀不出來，請用 Excel 另存成 UTF-8 的 CSV。")

    result = ads_performance.import_csv(main_mod.conn, brand_id, cycle_id, text, actor=str(actor.user_id),
                                        today=date.today().isoformat())
    if result.errors:
        return _error(400, result.errors[0])

    ads_performance.save_derived_metrics(main_mod.conn, brand_id, cycle_id)
    ads_pacing.check_cycle(main_mod.conn, brand_id, cycle_id)  # 新數據落地後判一次步調
    return JSONResponse({
        "imported": result.imported,
        "quarantined": result.quarantined,
        "skipped": result.skipped,
        "matched_assets": result.matched_assets,
        "unmatched_columns": result.unmatched_columns,
        "warnings": [],
        **weekly_proposals.rerun_after_late_data(main_mod.conn, brand_id, cycle_id, str(actor.user_id)),
    })


# ---- 現在結算＋匯入整批撤銷（票 S1-01） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/settle-now")
async def settle_now_get(brand_id: str, cycle_id: str, request: Request):
    main_mod.require_brand(brand_id, main_mod.require_actor(request))
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    can_settle, reason, already_closed = performance_batches.can_settle(conn, brand_id, cycle_id, cycle)
    return _envelope({
        "can_settle": can_settle, "reason": reason,
        "estimated_cost": ads_reading.estimated_run_cost(conn, brand_id), "already_closed": already_closed,
        # 票 F9：按下結算前先問「還有幾張建議卡沒處理」，畫面拿這個問使用者要不要確認結案。
        "unhandled_cards": weekly_proposals.unhandled_cards(conn, brand_id, cycle_id),
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/settle-now")
async def settle_now_post(request: Request, brand_id: str, cycle_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    can_settle, reason, _already_closed = performance_batches.can_settle(conn, brand_id, cycle_id, cycle)
    if not can_settle:
        return JSONResponse({"detail": reason}, status_code=400)
    ok, err = ads_reading.finalize(conn, brand_id, cycle_id, str(actor.user_id))
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    # 票 F9：finalize() 內部已經把還沒處理的 GENERATED 卡轉成 ARCHIVED_ON_CLOSE 了，
    # can_settle() 剛擋掉重複結算同一期，所以這裡讀到的一定是這次結案剛歸檔的那批。
    archived_cards = weekly_proposals.archived_on_close_cards(conn, brand_id, cycle_id)
    return JSONResponse({
        "ok": True, "message": "收帳完成，覆盤可以看了。", "archived_cards": archived_cards,
    })


@router.get("/api/campaigns/{brand_id}/{cycle_id}/performance/batches")
async def performance_batches_get(brand_id: str, cycle_id: str, request: Request):
    main_mod.require_brand(brand_id, main_mod.require_actor(request))
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    items = performance_batches.list_batches(conn, brand_id, cycle_id)
    return _envelope({"items": items, "estimated_rerun_cost": ads_reading.estimated_run_cost(conn, brand_id)})


@router.delete("/api/campaigns/{brand_id}/{cycle_id}/performance/batches/{batch_id}")
async def performance_batch_delete(request: Request, brand_id: str, cycle_id: str, batch_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)

    deleted = ads_performance.delete_snapshots(conn, brand_id, cycle_id, batch_id=batch_id)
    if deleted == 0:
        return JSONResponse({"detail": "找不到這批匯入"}, status_code=404)

    # 票 F1 root cause 2：這裡以前只有 CLOSED 分支走共用重判，非 CLOSED 分支只呼叫
    # `ads_reading.run()`，從不補建週提案卡——`reading.run()` 每次重跑都會清掉未處理的舊卡
    # （見 `reading.py` 的 `preserved_weekly`），沒人接著建卡，卡片就這樣不見了。兩個分支
    # 現在走同一個共用出處，非 CLOSED 也補上 generate()。
    outcome = weekly_proposals.rerun_after_late_data(conn, brand_id, cycle_id, str(actor.user_id))
    rerun = outcome["rerun"]
    message = f"撤銷了 {deleted} 筆，" + (outcome["rerun_message"] or "沒有重新算過。")
    return JSONResponse({"ok": True, "deleted": deleted, "rerun": rerun, "message": message})


# ---- 檔期健康燈號（S8R.20-21） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/health-lights")
async def health_lights_get(brand_id: str, cycle_id: str, request: Request):
    main_mod.require_brand(brand_id, main_mod.require_actor(request))
    _require_cycle(brand_id, cycle_id)
    try:
        return _envelope(ads_health_lights.compute(main_mod.conn, brand_id, cycle_id))
    except ValueError as exc:
        return _error(404, str(exc))


# ---- 覆盤（S8.59-66） ----

def _closing_goal_comparison(conn, brand_id: str, cycle: dict, kpis: dict) -> dict:
    objective_label = OBJECTIVE_LABELS.get(cycle["objective"], cycle["objective"])
    product_ids = [a["product_id"] for a in ads_repo.list_cycle_products(conn, brand_id, cycle["id"])]
    if cycle["objective"] in target_cpa.CONVERSION_OBJECTIVES:
        target = target_cpa.resolve_target_cpa(conn, brand_id, cycle["objective"], product_ids)
        target_value = target["value"] if target else None
        target_text = f"目標 CPA NT$ {target_value:,.0f}" if target_value else "尚無目標 CPA 依據"
        return {"objective_label": objective_label, "target": target_text, "target_value": target_value,
                "actual_value": kpis.get("cpa"), "metric_label": "CPA", "lower_is_better": True,
                "actual_kpis": kpis, "source": "Meta 自報"}
    rng = target_cpa.non_conversion_range(conn, brand_id, cycle["objective"])
    if rng:
        mid = round((rng["low"] + rng["high"]) / 2, 2)
        target_text = f"建議花費約 NT$ {rng['low']:,.0f}～{rng['high']:,.0f}"
    else:
        mid, target_text = None, "尚無建議花費區間依據"
    spend = ads_performance.totals(conn, brand_id, cycle["id"])["spend"]
    return {"objective_label": objective_label, "target": target_text, "target_value": mid,
            "actual_value": spend, "metric_label": "花費", "lower_is_better": False, "actual_kpis": kpis,
            "source": "Meta 自報"}


def _two_ledger_note(conn, brand_id: str, cycle_id: str) -> str:
    """B0-04：①目標對照的 ROAS／CPA 是 Meta 自己回報的廣告成效；②落差歸因的毛單／淨單
    是訂單系統依「廣告用碼」配對出來的——兩套帳各自統計，數字天生對不起來，畫面要講清楚
    為什麼，不能讓使用者以為資料傳錯了（真機重現：B0-04，FINDINGS.md）。"""
    has_ad_code = any(c["source_type"] == "ad" for c in ads_codes.list_codes(conn, brand_id, cycle_id))
    if not has_ad_code:
        return ("①的 ROAS／成交數是 Meta 自己回報的廣告成效；②的毛單／淨單只算對到「廣告用碼」的"
                "訂單——這期還沒有設定廣告用碼，所以全部訂單都落在「自然單」，兩邊數字不會對得起來。")
    return ("①的 ROAS／成交數是 Meta 自己回報的廣告成效；②的毛單／淨單是訂單系統依「廣告用碼」"
            "配對出來的——兩套系統各自統計，數字不會完全一樣，不代表資料傳錯了。")


def _budget_delta_reason(conn, brand_id: str, cycle_id: str, proposed_budget) -> "str | None":
    """B0-25：下期建議金額補件後悄悄跳號，一個字沒提哪裡變了。在讀取時比對最近兩個判讀
    版次的營收／ROAS（`nextcycle.build()` 每次重判都會無條件覆寫這筆建議，不在寫入時比對
    ——這裡讀時現算比較簡單，也不用碰已經頂在 800 行上限的 `nextcycle.py`）。只有一個版次、
    或營收根本沒變就不附這個欄位，不喊假理由。"""
    delta = ads_settlement.latest_version_delta(conn, brand_id, cycle_id)
    if not delta or not delta["prev_revenue"] or delta["prev_revenue"] == delta["cur_revenue"]:
        return None
    pct = round((delta["cur_revenue"] - delta["prev_revenue"]) / delta["prev_revenue"] * 100)
    sign = "+" if pct >= 0 else ""
    roas_part = (f"（ROAS {delta['prev_roas']:.2f}→{delta['cur_roas']:.2f}）"
                if delta["prev_roas"] is not None and delta["cur_roas"] is not None else "")
    return f"補件後營收{sign}{pct}%{roas_part}，下期建議金額因此調整為 {proposed_budget:,.0f}。"


def _closing_recommendation(conn, brand_id: str, cycle_id: str) -> dict:
    stored = nextcycle.load(conn, brand_id, cycle_id)
    if stored:
        content = stored["content"]
        budget = {"budget_advice": content["budget"]["advice"],
                  "proposed_budget": content["budget"]["proposed_budget"],
                  "rule_cards_created": content.get("rule_cards_created", 0),
                  "echo_chamber": bool(content.get("echo_chamber"))}
    else:
        proposed = nextcycle.propose_budget(conn, brand_id, cycle_id)
        budget = {"budget_advice": proposed["advice"], "proposed_budget": proposed["proposed_budget"],
                  "rule_cards_created": 0, "echo_chamber": False}
    budget["delta_reason"] = _budget_delta_reason(conn, brand_id, cycle_id, budget["proposed_budget"])
    return budget


def compile_closing_review(conn, brand_id: str, cycle_id: str) -> dict:
    """S8.59 純聚合函式：拼裝既有判讀／歸因／學習／建議四段資料，不重算任何判讀邏輯。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    loaded = ads_reading.load(conn, brand_id, cycle_id)
    cycle_reading = loaded["cycle"]
    result = (cycle_reading["result"] if cycle_reading else None) or {}
    kpis = result.get("kpis") or ads_performance.compute_kpis(ads_performance.totals(conn, brand_id, cycle_id))
    hyp_reviews_by_id = {r["id"]: r for r in ((cycle_reading or {}).get("hypothesis_reviews") or [])}

    hypotheses = [
        {"id": h["id"], "statement": h["statement"],
         "verdict": h["status"] if h["status"] in ("supported", "rejected", "inconclusive") else "inconclusive",
         "pending": h["status"] in ads_reading.PENDING_HYPOTHESIS_STATUSES,
         # 預選裁決是判讀當下算好存起來的（`reading.load()["cycle"]["hypothesis_reviews"]`），
         # 這裡只取用、不重算（決策 0035：預選一律看不出來，只有程式算得出方向才預選成立；
         # R2-learning-honesty 契約第 1 點：沒對照資料時預選是 None，不補「看不出來」進去
         # ——None 才是誠實的「空」，前端自己決定怎麼顯示空值）。
         "preselected": (hyp_reviews_by_id[h["id"]]["preselect"]
                        if h["status"] in ads_reading.PENDING_HYPOTHESIS_STATUSES
                        and h["id"] in hyp_reviews_by_id else None),
         # R2-learning-honesty 契約第 2 點：這期真的對照過的切角（切角名／樣本數／CPA／
         # ROAS／花費），簽核畫面拿來並排出示證據，不是只有程式的結論。
         "comparison_cells": (hyp_reviews_by_id[h["id"]]["comparison_cells"]
                             if h["id"] in hyp_reviews_by_id else []),
         # B0-34：已簽核假設判讀翻盤要提示「結論依據已變」，但不能自動改動已簽核的
         # verdict——純讀取端旁註（`ads_reading.stale_note`），非 pending 才可能非 None。
         "stale_note": ads_reading.stale_note(conn, brand_id, cycle_id, h)}
        for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)
    ]
    # 收斂後代表列的 source_cycle_id 可能不是本期（ADR 0026 決定 5：代表列＝原文最長那列，
    # 不一定是本期新入帳那列）——篩選要看 member_ids 對應的原始列裡有沒有本期，不能只看
    # 代表列，否則本期新入帳、跟舊期同義的學習會在自己的覆盤頁消失。
    all_learnings = ads_repo.list_learning_ledger(conn, brand_id)
    learnings_by_id = {e["id"]: e for e in all_learnings}
    ledger_entries = [
        {"text": e["learning_text"], "created_at": e["created_at"]}
        for e in collapse_learnings(all_learnings)
        if any(learnings_by_id[member_id].get("source_cycle_id") == cycle_id
               for member_id in e["member_ids"])
    ]

    return {
        "cycle_id": cycle_id,
        "goal_comparison": _closing_goal_comparison(conn, brand_id, cycle, kpis),
        "gap_attribution": {
            "reasons": result.get("reasons") or [],
            "channel_note": _dict_note(result.get("channel_comparison")),
            "ga4_leak_note": _dict_note(result.get("ga4_leak")),
            "attribution": ads_codes.attribution_summary(conn, brand_id, cycle_id),
            "source": "訂單系統",
            "two_ledger_note": _two_ledger_note(conn, brand_id, cycle_id),
        },
        "learning": {"hypotheses": hypotheses, "ledger_entries": ledger_entries},
        "recommendation": _closing_recommendation(conn, brand_id, cycle_id),
    }


@router.get("/api/campaigns/{brand_id}/{cycle_id}/closing-review")
async def closing_review_get(brand_id: str, cycle_id: str, request: Request):
    main_mod.require_brand(brand_id, main_mod.require_actor(request))
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    if cycle["status"] != "CLOSED":
        return _error(400, "這期還沒有結案，覆盤要等成效判讀跑完期末結算才會出現。")
    return _envelope(compile_closing_review(conn, brand_id, cycle_id))


# ---- 假設結案（L1-01，決策 0030 第一節第 1 點、決策 0035 第三節第 6 點） ----

@router.post("/api/campaigns/{brand_id}/{cycle_id}/hypotheses/resolve")
async def hypotheses_resolve_post(request: Request, brand_id: str, cycle_id: str):
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id, actor)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    # 信任邊界的輸入檢查：壞掉的 body 要回 400 說清楚，不能讓它一路炸成 500。
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — 任何解析失敗都是同一種使用者錯誤
        return JSONResponse({"detail": "送出的內容不是有效的資料格式。"}, status_code=400)
    verdicts = body.get("verdicts") if isinstance(body, dict) else None
    if not isinstance(verdicts, dict):
        return JSONResponse({"detail": "沒有收到要結案的假設。"}, status_code=400)
    try:
        # 業務邏輯全在 resolve_hypotheses 裡（非 pending／偽造 id 忽略、只有成立才入帳、
        # 樣本數與可信度程式帶入）——路由層不 UPDATE、不寫 ledger（票 L1-01）。
        updated = ads_reading.resolve_hypotheses(conn, brand_id, cycle_id, verdicts, actor=str(actor.user_id))
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "updated": updated, "message": "結案完成，成立的已寫進累積智慧。"})
