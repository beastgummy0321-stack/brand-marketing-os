# -*- coding: utf-8 -*-
"""累積智慧的 JSON API（票 T5-02）。

對外進入點：本檔的 ``router``，以及供舊 Jinja 路由共用的讀取／動作函式。
輸入輸出形狀：GET 回 ``{data: LearningSections, generated_at: str}``；POST 成功回
``{ok: true, message: str}``，可預期失敗回 ``{detail: str}``。
誰依賴它：``app/main.py`` 註冊 router；``app.ads.routes_interview`` 沿用讀取與動作函式。
不碰：不改 ``context_compiler``、``nextcycle``、``rule_lifecycle``，不依賴前端或 Jinja 模板。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.ads import nextcycle
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi
from app.llm import context_compiler

router = APIRouter()

_PENDING_HYPOTHESIS_LABELS = {"proposed": "待驗證", "testing": "驗證中"}


def learning_meta_line(conn, brand_id: str, entry: dict) -> str:
    """組已確認學習的來源說明；這是既有舊頁的顯示規則，沒有補算任何資料。"""
    parts = []
    if entry["product_id"]:
        product = bi.get_product(conn, brand_id, entry["product_id"])
        parts.append(product["name"] if product else "已刪除的產品")
    else:
        parts.append("品牌整體")
    if entry["source_cycle_id"]:
        cycle = ads_repo.get_cycle(conn, brand_id, entry["source_cycle_id"])
        if cycle:
            parts.append(f"來源：{cycle['start_date']} 期")
    if entry["sample_size"]:
        parts.append(f"樣本 {entry['sample_size']}")
    if entry["confidence"]:
        parts.append(ads_reading.LEDGER_CONFIDENCE_LABELS.get(entry["confidence"], entry["confidence"]))
    if entry["needs_revalidation"]:
        parts.append("建議找機會重新驗證")
    return " ・ ".join(parts)


def learning_sections(conn, brand_id: str) -> dict:
    """依舊頁既有順序讀取七段資料；待確認規則必須先觸發逾期掃描。"""
    learnings = ads_repo.list_learning_ledger(conn, brand_id)
    for entry in learnings:
        entry["meta_line"] = learning_meta_line(conn, brand_id, entry)

    pending_reconfirm_rules = bi.list_pending_reconfirm_rules(conn, brand_id)
    active_bans = nextcycle.list_active_bans(conn, brand_id)
    pending_cards = nextcycle.list_pending_rule_cards(conn, brand_id)
    observing_signals = nextcycle.list_observing_signals(conn, brand_id)
    pending_hypotheses = [
        {**hypothesis, "status_label": _PENDING_HYPOTHESIS_LABELS.get(hypothesis["status"], hypothesis["status"])}
        for hypothesis in bi.list_strategy_hypotheses(conn, brand_id)
        if hypothesis["status"] in ads_reading.PENDING_HYPOTHESIS_STATUSES
    ]
    overflow_rules = context_compiler.list_overflow_rules(conn, brand_id)
    return {
        "learnings": learnings,
        "active_bans": active_bans,
        "pending_reconfirm_rules": pending_reconfirm_rules,
        "pending_cards": pending_cards,
        "observing_signals": observing_signals,
        "pending_hypotheses": pending_hypotheses,
        "overflow_rules": overflow_rules,
    }


def deactivate_ledger(conn, brand_id: str, entry_id: str, actor: str) -> dict:
    try:
        ads_repo.deactivate_learning_ledger_entry(conn, brand_id, entry_id, actor=actor)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "已下架這條學習，之後生成內容不會再引用它。"}


def deactivate_rule(conn, brand_id: str, rule_id: str, actor: str) -> dict:
    try:
        bi.deactivate_rule(conn, brand_id, rule_id, actor=actor)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "已下架這條禁令，之後生成內容不會再避開它。"}


def reconfirm_rule(conn, brand_id: str, rule_id: str, actor: str) -> dict:
    try:
        bi.reconfirm_rule(conn, brand_id, rule_id, actor=actor)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": "已延續這條規則，重新進入生成內容的判斷依據。"}


def _envelope(data: dict) -> dict:
    return {"data": data, "generated_at": datetime.now(timezone.utc).isoformat()}


def _action_response(result: dict) -> dict | JSONResponse:
    if not result["ok"]:
        return JSONResponse({"detail": result["message"]}, status_code=400)
    return result


@router.get("/api/campaigns/brands/{brand_id}/learnings")
async def list_learnings(brand_id: str):
    main_mod.require_brand(brand_id)
    return _envelope(learning_sections(main_mod.conn, brand_id))


@router.post("/api/campaigns/brands/{brand_id}/learnings/ledger/{entry_id}/deactivate")
async def deactivate_learning(request: Request, brand_id: str, entry_id: str):
    main_mod.require_brand(brand_id)
    return _action_response(deactivate_ledger(main_mod.conn, brand_id, entry_id, main_mod.require_actor(request)))


@router.post("/api/campaigns/brands/{brand_id}/learnings/rules/{rule_id}/deactivate")
async def deactivate_active_ban(request: Request, brand_id: str, rule_id: str):
    main_mod.require_brand(brand_id)
    return _action_response(deactivate_rule(main_mod.conn, brand_id, rule_id, main_mod.require_actor(request)))


@router.post("/api/campaigns/brands/{brand_id}/learnings/rules/{rule_id}/reconfirm")
async def reconfirm_pending_rule(request: Request, brand_id: str, rule_id: str):
    main_mod.require_brand(brand_id)
    return _action_response(reconfirm_rule(main_mod.conn, brand_id, rule_id, main_mod.require_actor(request)))
