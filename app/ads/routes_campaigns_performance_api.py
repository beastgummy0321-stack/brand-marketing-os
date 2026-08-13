# -*- coding: utf-8 -*-
"""app/ads/routes_campaigns_performance_api.py — S8 成效＋覆盤 JSON API（票 B4-warroom 接線，
契約 `.scratch/grill/GRILL-B4-warroom.md`＋`GRILL-B4R-performance.md`，型別逐欄對照
`frontend/src/lib/warroomApi.ts`）。

`compile_closing_review()`（S8.59）只有這一個呼叫端，薄聚合既有四塊資料，不獨立成
業務模組檔（ponytail：只有一個呼叫端就直接寫在這裡，出現第 2 個真實呼叫端才抽）。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import codes as ads_codes
from app.ads import health_lights as ads_health_lights
from app.ads import nextcycle
from app.ads import performance as ads_performance
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
        }
        confidence_label = f"{result.get('statistical_level_label', '')}尚未完成對帳三題自答，可信度中等".strip()

    return _envelope({"summary": summary, "reading": reading, "confidence_label": confidence_label})


@router.post("/api/campaigns/{brand_id}/{cycle_id}/performance/simulate")
async def performance_simulate(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    ok, note = simulation.generate(main_mod.conn, brand_id, cycle_id, actor)
    if not ok:
        return _error(400, note)
    return JSONResponse(None, status_code=204)


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
