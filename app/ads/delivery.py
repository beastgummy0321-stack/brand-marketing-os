# -*- coding: utf-8 -*-
"""交付前素材確認，狀態保存於既有 campaign_cycle.derived_plan_json 的新增鍵。"""

from app.ads import creative
from app.ads import handoff
from app.ads import repository as ads_repo
from app.core.db import now_utc, jsonb


_STATE_KEY = "delivery_confirmation"


def _state(cycle: dict) -> dict:
    plan = ads_repo.derived_plan(cycle)
    value = plan.get(_STATE_KEY)
    return value if isinstance(value, dict) else {}


def _save_state(conn, cycle: dict, state: dict, *, commit: bool = True) -> None:
    # ponytail: derived_plan_json 是既有延展 JSON；僅新增 namespaced key，不覆寫既有 plan 鍵。
    plan = ads_repo.derived_plan(cycle)
    plan[_STATE_KEY] = state
    conn.execute(
        "UPDATE campaign_cycle SET derived_plan_json = %s, updated_at = %s WHERE id = %s AND brand_id = %s",
        (jsonb(plan), now_utc(), cycle["id"], cycle["brand_id"]),
    )
    if commit:
        conn.commit()


def items(conn, brand_id: str, cycle_id: str) -> list:
    result = []
    for group in creative.group_by_cell(conn, brand_id, cycle_id):
        variants = [item for item in group["variants"] if not item["rejected"]]
        text = next((v["content"] for v in variants if v["variant_type"] == "copy"), "")
        if not text:
            text = next((v["content"] for v in variants if v["variant_type"] == "primary_text"), "")
        if not text:
            text = next((v["content"] for v in variants if v["variant_type"] != "image_prompt"), "")
        prompt = next((v["content"] for v in variants if v["variant_type"] == "image_prompt"), "")
        result.append({
            "id": group["cell"]["id"],
            "copy": text,
            "image_description": prompt,
            "image_prompt": prompt,
            "complete": bool(text and prompt),
        })
    return result


def view(conn, brand_id: str, cycle_id: str) -> dict:
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到檔期")
    material_items = items(conn, brand_id, cycle_id)
    state = _state(cycle)
    invalid = set(state.get("invalidated_item_ids") or [])
    ready_items = [item for item in material_items if item["complete"]]
    incomplete_items = [item for item in material_items if not item["complete"]]
    # 被退回的素材正在補件時，不得把已可交付的其他素材一起擋住。
    pending_replacements = [item for item in incomplete_items if item["id"] in invalid]
    if not ready_items or any(item["id"] not in invalid for item in incomplete_items):
        return {"status": "assembling", "reason": "素材尚未完成", "items": [],
                "checks": {"facts_confirmed": [], "budget_confirmed": False,
                           "budget_cap": cycle.get("budget") or 0}}
    # ponytail: 首次進入時沿用素材反對制——全數預設採用，使用者只退回不採的素材。
    facts = set(state["facts"]) if "facts" in state else {item["id"] for item in ready_items}
    return {
        "status": state.get("status", "ready"),
        "reason": "有素材補件中，其餘可先確認。" if pending_replacements else state.get("reason"),
        "items": [{k: v for k, v in item.items() if k != "complete"} for item in ready_items],
        "checks": {"facts_confirmed": [item["id"] in facts for item in ready_items],
                   "budget_confirmed": bool(state.get("budget")),
                   "budget_cap": cycle.get("budget") or 0},
    }


def confirm(conn, brand_id: str, cycle_id: str, *, facts, budget: bool, actor: str) -> dict:
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        raise ValueError("找不到檔期")
    material_items = items(conn, brand_id, cycle_id)
    ids = {item["id"] for item in material_items if item["complete"]}
    facts = set(facts or [])
    state = _state(cycle)
    budget_confirmed = budget or bool(state.get("budget"))
    if not ids or facts != ids or not budget_confirmed:
        raise ValueError("請完成素材內容與預算兩項確認")
    try:
        delivered = set(state.get("delivered_item_ids") or [])
        replacements = ids - delivered
        creative.approve_selection(conn, brand_id, cycle_id, actor, commit=False)
        handoff.build_packages(conn, brand_id, cycle_id, actor, commit=False)
        final_state = {**state, "facts": sorted(facts), "budget": budget_confirmed,
                       "delivered_item_ids": sorted(delivered | ids),
                       "invalidated_item_ids": sorted(
                           set(state.get("invalidated_item_ids") or []) - replacements),
                       "status": "ready", "reason": None}
        _save_state(conn, cycle, final_state, commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        reason = "交接組裝失敗，請人工檢查後再試。"
        _save_state(conn, cycle, {**state, "facts": sorted(facts), "budget": budget_confirmed,
                                  "status": "failed", "reason": reason})
        return {"status": "failed", "reason": reason, "action_cards": []}
    packages = handoff.list_packages(conn, brand_id, cycle_id)
    if delivered:
        packages = [package for package in packages if package["experiment_cell_id"] in replacements]
        # 同 cell 的已投放舊包須留作外部對帳證據；交付畫面只顯示這次剛重出的最新包。
        newest_by_cell = {}
        for package in packages:
            newest_by_cell[package["experiment_cell_id"]] = package
        packages = list(newest_by_cell.values())
    return {"status": "ready", "reason": None,
            "action_cards": packages}


def reject_item(conn, brand_id: str, cycle_id: str, item_id: str, *, actor: str) -> dict:
    group = next((g for g in creative.group_by_cell(conn, brand_id, cycle_id)
                  if g["cell"]["id"] == item_id), None)
    if group is None:
        raise ValueError("找不到素材")
    for variant in group["variants"]:
        if not variant["rejected"]:
            creative.reject(conn, brand_id, variant["id"], reason_code="off_brand", actor=actor,
                            reason_text="交付確認退回")
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    state = _state(cycle)
    # ponytail: 沒有 facts 鍵代表首次進入的「全勾」哨兵；保留它，讓其餘 ready 素材仍預設勾選。
    if "facts" in state:
        state["facts"] = [item for item in state["facts"] if item != item_id]
    state["invalidated_item_ids"] = sorted(set(state.get("invalidated_item_ids", [])) | {item_id})
    state["delivered_item_ids"] = [item for item in state.get("delivered_item_ids", []) if item != item_id]
    state["status"] = "ready"
    state["reason"] = None
    # 退件後舊交接卡不再可見；補件完成時由既有 handoff 組裝器重出該則的追加卡。
    conn.execute(
        "DELETE FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s "
        "AND experiment_cell_id = %s AND id NOT IN "
        "(SELECT publishing_package_id FROM external_ad_mapping WHERE publishing_package_id IS NOT NULL)",
        (brand_id, cycle_id, item_id),
    )
    _save_state(conn, cycle, state)
    return view(conn, brand_id, cycle_id)
