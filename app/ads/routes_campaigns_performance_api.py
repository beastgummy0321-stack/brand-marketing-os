# -*- coding: utf-8 -*-
"""app/ads/routes_campaigns_performance_api.py — S8 成效＋覆盤 JSON API（票 B4-warroom 接線，
契約 `.scratch/grill/GRILL-B4-warroom.md`＋`GRILL-B4R-performance.md`，型別逐欄對照
`frontend/src/lib/warroomApi.ts`）。

`compile_closing_review()`（S8.59）只有這一個呼叫端，薄聚合既有四塊資料，不獨立成
業務模組檔（ponytail：只有一個呼叫端就直接寫在這裡，出現第 2 個真實呼叫端才抽）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import codes as ads_codes
from app.ads import health_lights as ads_health_lights
from app.ads import nextcycle
from app.ads import pacing as ads_pacing
from app.ads import performance as ads_performance
from app.ads import performance_batches
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import simulation
from app.ads import target_cpa
from app.ads.routes_common import OBJECTIVE_LABELS, _require_cycle

router = APIRouter()


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _dict_note(d) -> "str | None":
    if not isinstance(d, dict):
        return None
    return d.get("note") or d.get("reason")


# ---- 成效（S8.51-58） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/performance")
async def performance_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)

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

    return _envelope({"summary": summary, "reading": reading,
                      "confidence_label": confidence_label, "last_synced_at": last_synced_at})


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/simulate")
async def performance_simulate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    ok, note = simulation.generate(main_mod.conn, brand_id, cycle_id, actor)
    if not ok:
        return _error(400, note)
    return JSONResponse(None, status_code=204)


_MANUAL_NUMBER_FIELDS = ("spend", "impressions", "clicks", "conversions", "revenue", "reach")


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/manual")
async def performance_manual(request: Request, brand_id: str, cycle_id: str):
    """使用者自己填成效數字——API 掛掉、CSV 也匯不進來時的最後退路（原
    `ads_performance_manual`，T4 清倉刪掉 Jinja 路由後恢復成 JSON 版本）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    body = await request.json()

    values = {}
    for key in _MANUAL_NUMBER_FIELDS:
        value, ok = main_mod.parse_number(body.get(key))
        if not ok:
            return _error(400, "數字欄位請只填數字。")
        values[key] = value
    values["date_start"] = body.get("date_start") or None
    values["date_stop"] = body.get("date_stop") or None

    result = ads_performance.import_manual(main_mod.conn, brand_id, cycle_id, values, actor=actor)
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
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/csv")
async def performance_csv(request: Request, brand_id: str, cycle_id: str,
                          perf_file: UploadFile = File(None)):
    """Meta CSV 匯出檔匯入（原 `ads_performance_csv`，同上恢復成 JSON 版本）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
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

    result = ads_performance.import_csv(main_mod.conn, brand_id, cycle_id, text, actor=actor,
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
    })


# ---- 現在結算＋匯入整批撤銷（票 S1-01） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/settle-now")
async def settle_now_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    can_settle, reason, already_closed = performance_batches.can_settle(conn, brand_id, cycle_id, cycle)
    return _envelope({
        "can_settle": can_settle, "reason": reason,
        "estimated_cost": ads_reading.estimated_run_cost(conn), "already_closed": already_closed,
    })


@router.post("/api/campaigns/{brand_id}/{cycle_id}/settle-now")
async def settle_now_post(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    can_settle, reason, _already_closed = performance_batches.can_settle(conn, brand_id, cycle_id, cycle)
    if not can_settle:
        return JSONResponse({"detail": reason}, status_code=400)
    ok, err = ads_reading.finalize(conn, brand_id, cycle_id, actor)
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    return JSONResponse({"ok": True, "message": "收帳完成，覆盤可以看了。"})


@router.get("/api/campaigns/{brand_id}/{cycle_id}/performance/batches")
async def performance_batches_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    _require_cycle(brand_id, cycle_id)
    items = performance_batches.list_batches(conn, brand_id, cycle_id)
    return _envelope({"items": items, "estimated_rerun_cost": ads_reading.estimated_run_cost(conn)})


@router.delete("/api/campaigns/{brand_id}/{cycle_id}/performance/batches/{batch_id}")
async def performance_batch_delete(request: Request, brand_id: str, cycle_id: str, batch_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)

    deleted = ads_performance.delete_snapshots(conn, brand_id, cycle_id, batch_id=batch_id)
    if deleted == 0:
        return JSONResponse({"detail": "找不到這批匯入"}, status_code=404)

    if cycle["status"] == "CLOSED":
        result = ads_reading.rerun_for_late_data(conn, brand_id, cycle_id, actor=actor)
        rerun = "late_data" if result else "skipped"
        message = (f"撤銷了 {deleted} 筆，結論已重新算過。" if result
                   else f"撤銷了 {deleted} 筆，這批數字不影響結論，沒有重新算過。")
    else:
        ok, err = ads_reading.run(conn, brand_id, cycle_id, actor)
        rerun = "done" if ok else "skipped"
        message = (f"撤銷了 {deleted} 筆，結論已重新算過。" if ok
                   else f"撤銷了 {deleted} 筆，但重新判讀失敗：{err}")
    return JSONResponse({"ok": True, "deleted": deleted, "rerun": rerun, "message": message})


# ---- 檔期健康燈號（S8R.20-21） ----

@router.get("/api/campaigns/{brand_id}/{cycle_id}/health-lights")
async def health_lights_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
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
                "actual_kpis": kpis}
    rng = target_cpa.non_conversion_range(conn, brand_id, cycle["objective"])
    if rng:
        mid = round((rng["low"] + rng["high"]) / 2, 2)
        target_text = f"建議花費約 NT$ {rng['low']:,.0f}～{rng['high']:,.0f}"
    else:
        mid, target_text = None, "尚無建議花費區間依據"
    spend = ads_performance.totals(conn, brand_id, cycle["id"])["spend"]
    return {"objective_label": objective_label, "target": target_text, "target_value": mid,
            "actual_value": spend, "metric_label": "花費", "lower_is_better": False, "actual_kpis": kpis}


def _closing_recommendation(conn, brand_id: str, cycle_id: str) -> dict:
    stored = nextcycle.load(conn, brand_id, cycle_id)
    if stored:
        content = stored["content"]
        return {"budget_advice": content["budget"]["advice"],
                "proposed_budget": content["budget"]["proposed_budget"],
                "rule_cards_created": content.get("rule_cards_created", 0),
                "echo_chamber": bool(content.get("echo_chamber"))}
    budget = nextcycle.propose_budget(conn, brand_id, cycle_id)
    return {"budget_advice": budget["advice"], "proposed_budget": budget["proposed_budget"],
            "rule_cards_created": 0, "echo_chamber": False}


def compile_closing_review(conn, brand_id: str, cycle_id: str) -> dict:
    """S8.59 純聚合函式：拼裝既有判讀／歸因／學習／建議四段資料，不重算任何判讀邏輯。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    loaded = ads_reading.load(conn, brand_id, cycle_id)
    cycle_reading = loaded["cycle"]
    result = (cycle_reading["result"] if cycle_reading else None) or {}
    kpis = result.get("kpis") or ads_performance.compute_kpis(ads_performance.totals(conn, brand_id, cycle_id))

    hypotheses = [
        {"statement": h["statement"],
         "verdict": h["status"] if h["status"] in ("supported", "rejected", "inconclusive") else "inconclusive"}
        for h in ads_repo.list_cycle_hypotheses(conn, brand_id, cycle_id)
    ]
    ledger_entries = [
        {"text": e["learning_text"], "created_at": e["created_at"]}
        for e in ads_repo.list_learning_ledger(conn, brand_id)
        if e.get("source_cycle_id") == cycle_id
    ]

    return {
        "cycle_id": cycle_id,
        "goal_comparison": _closing_goal_comparison(conn, brand_id, cycle, kpis),
        "gap_attribution": {
            "reasons": result.get("reasons") or [],
            "channel_note": _dict_note(result.get("channel_comparison")),
            "ga4_leak_note": _dict_note(result.get("ga4_leak")),
            "attribution": ads_codes.attribution_summary(conn, brand_id, cycle_id),
        },
        "learning": {"hypotheses": hypotheses, "ledger_entries": ledger_entries},
        "recommendation": _closing_recommendation(conn, brand_id, cycle_id),
    }


@router.get("/api/campaigns/{brand_id}/{cycle_id}/closing-review")
async def closing_review_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    if cycle["status"] != "CLOSED":
        return _error(400, "這期還沒有結案，覆盤要等成效判讀跑完期末結算才會出現。")
    return _envelope(compile_closing_review(conn, brand_id, cycle_id))
