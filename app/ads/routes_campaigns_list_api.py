# -*- coding: utf-8 -*-
"""app/ads/routes_campaigns_list_api.py — S7 檔期清單 JSON API（票 B4-campaigns 接線，
契約 `.scratch/grill/GRILL-B4-campaigns.md`，型別逐欄對照 `frontend/src/lib/campaignsApi.ts`）。

網址沿用 `/api/campaigns/brands/{brand_id}/...`（含字面 "brands" 這一段）——跟
`routes_campaigns_open_api.py` 的 `/api/campaigns/{brand_id}/...`（無 "brands" 段）
路徑形狀不同，但兩者都是四段式（`api/campaigns/X/Y`），有真實品牌 id 恰好等於字面
"brands" 時才會混淆（理論上不會發生）；仍照 `mocks/warroomHandlers.ts` 既有慣例，本檔
的具名 "brands" 路徑在 `routes.py` 裡排在通用萬用路由之前註冊，先到先贏。

對外進入點：本檔的 `router`。誰依賴它：只有 `app/ads/routes.py`。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import interview as ads_interview
from app.ads import repository as ads_repo
from app.ads.routes_common import _closed_cycle_reading, _cycle_view, _history_trend_rows, _hub_stage_info
from app.core.creative_assets import delete_folder as _delete_creative_folder

router = APIRouter()


def _envelope(data) -> dict:
    from datetime import datetime, timezone
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _cycle_label(cycle: dict) -> str:
    return f"{cycle['start_date']} ～ {cycle['end_date']}"


def _list_item(conn, brand_id: str, cycle: dict, vs_previous_by_id: dict) -> dict:
    view = _cycle_view(conn, brand_id, cycle)
    bucket = "archived" if cycle["archived"] else ("closed" if cycle["status"] == "CLOSED" else "in_progress")

    stage_index = stage_label = days_left = None
    if bucket == "in_progress":
        info = _hub_stage_info(conn, brand_id, cycle)
        stage_index, stage_label, days_left = info["stage_index"], info["stage_label"], info["days_left"]

    roas = status_label_reading = verdict_kind = data_grade = None
    trend_daily_budgets = None
    if bucket == "closed":
        reading = _closed_cycle_reading(conn, brand_id, cycle)
        if reading:
            roas = reading["roas"]
            status_label_reading = reading["status_label"]
            verdict_kind = reading["verdict_kind"]
            data_grade = reading["data_grade"]
            budgets = view.get("daily_budgets") or []
            if budgets:
                trend_daily_budgets = [d["budget"] for d in budgets]

    return {
        "id": cycle["id"], "start_date": cycle["start_date"], "end_date": cycle["end_date"],
        "status": cycle["status"], "status_label": view["status_label"], "bucket": bucket,
        "phase_label": view["phase_label"], "objective_label": view["objective_label"],
        "funnel_stage_label": view["funnel_stage_label"], "budget": cycle["budget"],
        "product_names": view["product_names"],
        "stage_index": stage_index, "stage_label": stage_label, "days_left": days_left,
        "roas": roas, "status_label_reading": status_label_reading, "verdict_kind": verdict_kind,
        "data_grade": data_grade, "vs_previous": vs_previous_by_id.get(cycle["id"]),
        "trend_daily_budgets": trend_daily_budgets,
    }


@router.get("/api/campaigns/brands/{brand_id}")
async def campaign_list(brand_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycles = ads_repo.list_cycles(conn, brand_id, include_archived=True)
    closed_non_archived = [c for c in cycles if c["status"] == "CLOSED" and not c["archived"]]
    trend_rows = _history_trend_rows(conn, brand_id, closed_non_archived)
    vs_previous_by_id = {row["id"]: row["vs_previous"] for row in trend_rows}
    items = [_list_item(conn, brand_id, cycle, vs_previous_by_id) for cycle in cycles]
    return _envelope(items)


@router.post("/api/campaigns/brands/{brand_id}/{cycle_id}/archive")
async def campaign_archive(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        return _error(404, "找不到這期檔期")
    ads_repo.set_cycle_archived(conn, brand_id, cycle_id, archived=not cycle["archived"], actor=actor)
    return JSONResponse(None, status_code=204)


@router.get("/api/campaigns/brands/{brand_id}/{cycle_id}/delete-impact")
async def campaign_delete_impact(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        return _error(404, "找不到這期檔期")
    rows = ads_repo.count_cycle_data(conn, brand_id, cycle_id)
    return _envelope([{"label": label, "count": n} for label, n in rows if n > 0])


@router.post("/api/campaigns/brands/{brand_id}/{cycle_id}/delete")
async def campaign_delete(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        return _error(404, "找不到這期檔期")
    if not cycle["archived"]:
        return _error(400, "要先把檔期封存，才能永久刪除。")
    try:
        body = await request.json()
    except Exception:
        body = {}
    confirm_name = main_mod.clean(str(body.get("confirm_name") or "")) if isinstance(body, dict) else ""
    if confirm_name != _cycle_label(cycle):
        return _error(400, "輸入的檔期名稱跟上面顯示的不一樣，請照著再打一次。")

    ads_repo.delete_cycle(conn, brand_id, cycle_id, actor=actor)
    _delete_creative_folder(conn, brand_id, cycle_id)
    return JSONResponse(None, status_code=204)


@router.post("/api/campaigns/brands/{brand_id}/interview")
async def campaign_interview_submit(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn
    try:
        body = await request.json()
    except Exception:
        body = {}
    bad = (body.get("bad") or {}) if isinstance(body, dict) else {}
    good = (body.get("good") or {}) if isinstance(body, dict) else {}
    note = body.get("note") if isinstance(body, dict) else None

    result = ads_interview.submit(conn, brand_id, bad=bad, good=good, note=note, actor=actor)
    return {
        "rule_card_count": len(result["rule_cards"]),
        "hypothesis_count": len(result["hypotheses"]),
        "conflicts": result["conflicts"],
    }
