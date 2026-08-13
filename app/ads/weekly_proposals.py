# -*- coding: utf-8 -*-
"""把既有判讀與下期建議收斂成最多三張週提案卡。"""

import json

from app.ads import nextcycle
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.core import interrupts as core_interrupts
from app.core.audit import write_audit
from app.core.db import new_id, now_iso


RECOMMENDATION_TYPE = "weekly_proposal"


def _instruction(action: str, target: str) -> str:
    verb = {"停掉": "暫停投放", "加碼": "提高預算", "換素材": "替換素材"}[action]
    return f"前往 Meta 廣告後台，找到「{target}」並{verb}。"


def _budget_impact(action: str, budget: dict) -> str:
    current = budget.get("current_budget") or 0
    proposed = budget.get("proposed_budget") or 0
    if action == "加碼" and proposed > current:
        return f"下期總預算增加 NT${proposed - current:,.0f}，且不超過既有增幅上限"
    if action == "停掉" and proposed < current:
        return f"下期總預算減少 NT${current - proposed:,.0f}，先守住停損線"
    return {
        "停掉": "避免低於停損門檻的項目繼續消耗預算",
        "加碼": "把下期預算優先移向已達加碼門檻的產品",
    }[action]


def select_cards(product_readings: list, budget: dict, historical_cells: list) -> list:
    """只挑已有規則訊號的停掉、加碼、換素材；沒有訊號就不硬湊。"""
    cards = []
    for status, action in (
        ("pause_candidate", "停掉"),
        ("scale_candidate", "加碼"),
    ):
        reading = next((row for row in product_readings if row.get("status") == status), None)
        if reading is None:
            continue
        reasons = (reading.get("result") or {}).get("reasons") or []
        cards.append({
            "action": action,
            "target": reading.get("product_name") or "未命名產品",
            "reason": reasons[0] if reasons else "既有成效判讀已達行動門檻",
            "impact": _budget_impact(action, budget),
            "product_id": reading.get("product_id"),
            "performance_reading_id": reading.get("id"),
        })

    tired_cell = next((cell for cell in historical_cells if cell.get("underperforming")), None)
    if tired_cell is not None:
        cards.append({
            "action": "換素材",
            "target": tired_cell.get("creative_angle") or "未命名切角",
            "reason": "這個切角花費已達一半預算，仍沒有帶來成交",
            "impact": "先換一批素材再測，不直接放大目前的低效花費",
            "product_id": None,
            "performance_reading_id": None,
        })
    return cards[:3]


def _card_from_row(row) -> dict:
    content = json.loads(row["content_json"] or "{}")
    return {"id": row["id"], **content, "status": row["status"]}


def list_cards(conn, brand_id: str, cycle_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ? ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    return [_card_from_row(row) for row in rows]


def generate(conn, brand_id: str, cycle_id: str) -> list:
    """依最新判讀建卡；同一期已建過就直接沿用，不重複通知。"""
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    existing = list_cards(conn, brand_id, cycle_id)
    if existing:
        return existing

    loaded = ads_reading.load(conn, brand_id, cycle_id)
    budget = nextcycle.propose_budget(conn, brand_id, cycle_id)
    historical_cells = nextcycle.historical_cell_performance(
        conn, brand_id, exclude_cycle_id=cycle_id)
    cards = select_cards(loaded["products"], budget, historical_cells)
    ts = now_iso()
    for card in cards:
        content = {key: card[key] for key in ("action", "target", "reason", "impact")}
        content["instruction"] = _instruction(card["action"], card["target"])
        conn.execute(
            "INSERT INTO recommendation (id, brand_id, campaign_cycle_id, product_id,"
            " performance_reading_id, recommendation_type, content_json, status, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'GENERATED', ?, ?)",
            (new_id("rec"), brand_id, cycle_id, card["product_id"],
             card["performance_reading_id"], RECOMMENDATION_TYPE,
             json.dumps(content, ensure_ascii=False), ts, ts),
        )
    if cards:
        core_interrupts.enqueue(
            conn, category="weekly_proposal_ready",
            dedupe_key=f"weekly_proposal_ready:{cycle_id}",
            message="本週優化提案已整理好，等你核可",
            brand_id=brand_id, campaign_cycle_id=cycle_id,
            action_url=f"/brands/{brand_id}",
        )
    conn.commit()
    return list_cards(conn, brand_id, cycle_id)


def view(conn, brand_id: str, cycle_id: str) -> dict:
    cards = list_cards(conn, brand_id, cycle_id)
    return {
        "proposals": [card for card in cards if card["status"] == "GENERATED"],
        "execution_checklist": [
            card for card in cards if card["status"] in ("ACCEPTED", "APPLIED")
        ],
    }


def approve(conn, brand_id: str, cycle_id: str, *, actor: str) -> dict:
    """一鍵核可同一期全部 GENERATED 卡；重送時直接回現況。"""
    if ads_repo.get_cycle(conn, brand_id, cycle_id) is None:
        raise ValueError("找不到廣告檔期")
    rows = conn.execute(
        "SELECT * FROM recommendation WHERE brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ? AND status = 'GENERATED' ORDER BY created_at, id",
        (brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchall()
    ts = now_iso()
    for row in rows:
        conn.execute(
            "UPDATE recommendation SET status = 'ACCEPTED', updated_at = ? WHERE id = ?",
            (ts, row["id"]),
        )
        write_audit(
            conn, brand_id=brand_id, entity_type="recommendation", entity_id=row["id"],
            action="accept_weekly_proposal", actor=actor,
            before={"status": row["status"]}, after={"status": "ACCEPTED"},
        )
    for interrupt in core_interrupts.list_open(
            conn, brand_id=brand_id, category="weekly_proposal_ready", archive_stale=False):
        if interrupt["campaign_cycle_id"] == cycle_id:
            core_interrupts.resolve(conn, interrupt["id"], actor=actor)
    conn.commit()
    return view(conn, brand_id, cycle_id)


def complete(conn, brand_id: str, cycle_id: str, recommendation_id: str, *, actor: str) -> dict:
    """把一張已核可卡標成完成；重送已完成的卡不重寫、不重複稽核。"""
    row = conn.execute(
        "SELECT * FROM recommendation WHERE id = ? AND brand_id = ? AND campaign_cycle_id = ?"
        " AND recommendation_type = ?",
        (recommendation_id, brand_id, cycle_id, RECOMMENDATION_TYPE),
    ).fetchone()
    if row is None:
        raise ValueError("找不到這張週提案卡")
    if row["status"] == "APPLIED":
        return _card_from_row(row)
    if row["status"] != "ACCEPTED":
        raise ValueError("這張週提案卡還沒核可")

    ts = now_iso()
    conn.execute(
        "UPDATE recommendation SET status = 'APPLIED', updated_at = ? WHERE id = ?",
        (ts, recommendation_id),
    )
    write_audit(
        conn, brand_id=brand_id, entity_type="recommendation", entity_id=recommendation_id,
        action="apply_weekly_proposal", actor=actor,
        before={"status": "ACCEPTED"}, after={"status": "APPLIED"},
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM recommendation WHERE id = ?", (recommendation_id,)).fetchone()
    return _card_from_row(updated)
