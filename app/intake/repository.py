# -*- coding: utf-8 -*-
"""app/intake/repository.py — intake_draft / intake_item 兩張表的存取層。

介面契約見 docs/design/07-settings-and-intake-contract.md §4；欄位權威見
docs/design/03-data-model.md §3A。一律 conn 開頭、一律帶 brand_id 過濾
（§3A.4 第 5 點：本模組不開無 brand 過濾的入口）。

resolve_item 是唯一改 outcome 的入口：套用人工修改（edits）、寫目標表（Brand
Intelligence 既有四張表）、寫 audit_log（entity_type='intake_item'）都在裡面完成，
呼叫端不各自實作。R10 強制客戶證實來源已由決策 0013 廢止（用戶優先，不擋確認）。
"""

import json
import sqlite3
from typing import Optional

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core import db
from app.core.audit import write_audit
from app.core import settings as coresettings

# intake_item.kind（內部代碼）↔ 畫面中文（DESIGN.md §19.7 對照）
KIND_TO_HUMAN = {
    "brand_fact": "品牌事實",
    "product_fact": "產品事實",
    "rule": "限制規則",
    "claim": "宣稱",
}
HUMAN_TO_KIND = {v: k for k, v in KIND_TO_HUMAN.items()}

# update_draft 只允許 03 §3A.2 列出的欄位（id / brand_id / created_at 除外）
_DRAFT_FIELDS = {
    "status", "current_step", "current_question_no", "description", "photos_json",
    "research_urls_json", "scan_sources_json", "scan_impressions_json", "scan_llm_task_id",
    "qa_json", "scan_products_json", "handoff_depth", "handoff_prompt", "handoff_generated_at", "paste_raw",
    "paste_validation_json", "repair_llm_task_id", "cost_limit", "llm_task_refs_json",
    "completed_at",
}


def _row_to_dict(row) -> Optional[dict]:
    return dict(row) if row is not None else None


def count_brand_data(conn: sqlite3.Connection, brand_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給品牌刪除確認頁列出本模組會被清掉的資料。"""
    return [
        ("建檔精靈草稿", conn.execute(
            "SELECT COUNT(*) FROM intake_draft WHERE brand_id = ?", (brand_id,)).fetchone()[0]),
        ("建檔精靈逐條紀錄", conn.execute(
            "SELECT COUNT(*) FROM intake_item WHERE brand_id = ?", (brand_id,)).fetchone()[0]),
    ]


def delete_brand_data(conn: sqlite3.Connection, brand_id: str) -> dict:
    """品牌被刪除時，清掉本模組掛在該品牌下的草稿與逐條紀錄（決策 0015）。

    稽核由呼叫端（品牌刪除那筆 audit_log）一起記，這裡不另外寫。
    只下 DELETE，不 commit、不 rollback——交易的開關統一在最外層的
    brand_intelligence.delete_brand()（Q4 全有全無）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    conn.execute("DELETE FROM intake_item WHERE brand_id = ?", (brand_id,))
    conn.execute("DELETE FROM intake_draft WHERE brand_id = ?", (brand_id,))
    return counts


def create_draft(conn: sqlite3.Connection, brand_id: str, description: str,
                 photos: list, research_urls: list, actor: str,
                 cost_limit: Optional[float] = None) -> dict:
    """建立一份進行中草稿。photos 為 §3A.2 形狀 [{file_path, display_name, size_bytes}]。

    一品牌一份進行中草稿由 DB 部分唯一索引擋（§3A.4 第 1 點），這裡不重複檢查。
    """
    if cost_limit is None:
        cost_limit = coresettings.get_intake_budget_limit(conn)
    draft_id = db.new_id("idr")
    ts = db.now_iso()
    conn.execute(
        """INSERT INTO intake_draft (
            id, brand_id, status, current_step, current_question_no, description,
            photos_json, research_urls_json, cost_limit, llm_task_refs_json,
            created_at, updated_at
        ) VALUES (?, ?, 'draft', 2, 0, ?, ?, ?, ?, '[]', ?, ?)""",
        (draft_id, brand_id, description, json.dumps(photos, ensure_ascii=False),
         json.dumps(research_urls, ensure_ascii=False), cost_limit, ts, ts),
    )
    conn.commit()
    return get_draft(conn, brand_id, draft_id)


def get_active_draft(conn: sqlite3.Connection, brand_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = ? AND status = 'draft'", (brand_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_latest_completed_draft(conn: sqlite3.Connection, brand_id: str) -> Optional[dict]:
    """重新調研的預帶來源：最近一輪已完成的草稿（issue #1）。"""
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = ? AND status = 'completed' "
        "ORDER BY completed_at DESC LIMIT 1", (brand_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_draft(conn: sqlite3.Connection, brand_id: str, draft_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = ? AND id = ?", (brand_id, draft_id)
    ).fetchone()
    return _row_to_dict(row)


def update_draft(conn: sqlite3.Connection, brand_id: str, draft_id: str, **fields) -> dict:
    unknown = set(fields) - _DRAFT_FIELDS
    if unknown:
        raise ValueError(f"intake_draft 不允許更新欄位：{sorted(unknown)}")
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE intake_draft SET {sets}, updated_at = ? WHERE brand_id = ? AND id = ?",
            (*fields.values(), db.now_iso(), brand_id, draft_id),
        )
        conn.commit()
    return get_draft(conn, brand_id, draft_id)


def complete_draft(conn: sqlite3.Connection, brand_id: str, draft_id: str) -> dict:
    return update_draft(conn, brand_id, draft_id, status="completed", completed_at=db.now_iso())


def add_llm_task_ref(conn: sqlite3.Connection, brand_id: str, draft_id: str,
                     llm_task_id: str, purpose: str) -> None:
    """只存 id 與人話用途，不存金額副本（03 §3A.5 第 5 點）。"""
    draft = get_draft(conn, brand_id, draft_id)
    refs = json.loads(draft["llm_task_refs_json"] or "[]")
    refs.append({"llm_task_id": llm_task_id, "purpose": purpose})
    update_draft(conn, brand_id, draft_id, llm_task_refs_json=json.dumps(refs, ensure_ascii=False))


def list_llm_cost_items(conn: sqlite3.Connection, draft: dict) -> list:
    """花費明細：依 refs 逐筆讀 llm_task 的 cost / status，即時算、不存副本。"""
    items = []
    for ref in json.loads(draft["llm_task_refs_json"] or "[]"):
        row = conn.execute(
            "SELECT cost, status FROM llm_task WHERE id = ?", (ref["llm_task_id"],)
        ).fetchone()
        if row is None:
            continue
        failed = row["status"] != "succeeded"
        items.append({"label": ref["purpose"], "amount": row["cost"] or 0.0, "failed": failed})
    return items


def get_draft_spend(conn: sqlite3.Connection, draft_id: str) -> float:
    row = conn.execute(
        "SELECT llm_task_refs_json FROM intake_draft WHERE id = ?", (draft_id,)
    ).fetchone()
    if row is None:
        return 0.0
    ids = [r["llm_task_id"] for r in json.loads(row["llm_task_refs_json"] or "[]")]
    if not ids:
        return 0.0
    placeholders = ",".join("?" for _ in ids)
    total = conn.execute(
        f"SELECT SUM(cost) FROM llm_task WHERE id IN ({placeholders}) AND status = 'succeeded'",
        ids,
    ).fetchone()[0]
    return float(total or 0.0)


# ---------------------------------------------------------------------------
# intake_item
# ---------------------------------------------------------------------------

def create_items(conn: sqlite3.Connection, brand_id: str, draft_id: str, rows: list) -> list:
    """整批一次寫；任何一筆失敗整批回滾（§19.2(e) 規則 4：部分成功不落地）。

    rows：paste_parse 的輸出（中文 kind／category），這裡轉成內部代碼存。
    重貼會先清掉這份草稿還沒處理的（outcome='pending'）舊列；已處理的列保留當追溯。
    """
    from app.intake import paste_parse  # 延遲 import 避免循環（paste_parse → mock_data）

    ts = db.now_iso()
    try:
        conn.execute(
            "DELETE FROM intake_item WHERE intake_draft_id = ? AND brand_id = ? AND outcome = 'pending'",
            (draft_id, brand_id),
        )
        for i, r in enumerate(rows, start=1):
            kind = HUMAN_TO_KIND[r["kind"]]
            category = _category_to_internal(r["kind"], r["category"])
            conn.execute(
                """INSERT INTO intake_item (
                    id, intake_draft_id, brand_id, row_no, raw_row, kind, category, title,
                    content, scope_raw, evidence_source, outcome, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (db.new_id("iit"), draft_id, brand_id, i,
                 r.get("raw_row") or " | ".join([r["kind"], r["category"], r["title"],
                                                  r["content"], r["scope"], r["evidence"]]),
                 kind, category, r["title"], r["content"], r["scope"], r["evidence"], ts),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return list_pending_items(conn, brand_id, draft_id)


def _item_to_display(row) -> dict:
    """DB 內部代碼列 → 畫面用的中文 dict（沿用 Mock 時代 review 模板的欄位名）。"""
    from app.intake import paste_parse

    d = dict(row)
    kind_h = KIND_TO_HUMAN[d["kind"]]
    category_h = next(
        (label for code, label in paste_parse.KIND_CATEGORY_SOURCE[kind_h] if code == d["category"]),
        d["category"],
    )
    return {
        "id": d["id"], "i": d["row_no"], "kind": kind_h, "category": category_h,
        "title": d["title"], "content": d["content"], "scope": d["scope_raw"],
        "evidence": d["evidence_source"], "outcome": d["outcome"],
        "status": "open" if d["outcome"] == "pending" else d["outcome"],
        "landed": d["target_id"] is not None,
        "landed_pending": d["outcome"] == "pending_saved" and d["target_id"] is not None,
    }


def list_pending_items(conn: sqlite3.Connection, brand_id: str, draft_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM intake_item WHERE brand_id = ? AND intake_draft_id = ? "
        "AND outcome = 'pending' ORDER BY row_no", (brand_id, draft_id),
    ).fetchall()
    return [_item_to_display(r) for r in rows]


def list_items(conn: sqlite3.Connection, brand_id: str, draft_id: str) -> list:
    rows = conn.execute(
        "SELECT * FROM intake_item WHERE brand_id = ? AND intake_draft_id = ? ORDER BY row_no",
        (brand_id, draft_id),
    ).fetchall()
    return [_item_to_display(r) for r in rows]


def count_items_by_outcome(conn: sqlite3.Connection, brand_id: str, draft_id: str) -> dict:
    rows = conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM intake_item WHERE brand_id = ? AND intake_draft_id = ? "
        "GROUP BY outcome", (brand_id, draft_id),
    ).fetchall()
    return {r["outcome"]: r["n"] for r in rows}


def _category_to_internal(kind_human: str, label: str) -> str:
    from app.intake import paste_parse

    for internal, human in paste_parse.KIND_CATEGORY_SOURCE[kind_human]:
        if human == label:
            return internal
    return label


def _ensure_product(conn, brand_id: str, actor: str, name: str) -> str:
    if name == "整個品牌":
        # 防呆：曾經把「整個品牌」四個字當產品名建檔（Beast Gummy 事件三）。
        raise ValueError("產品層的資料需要指定一個真正的產品，不能掛在「整個品牌」。")
    for p in bi_repo.list_products(conn, brand_id):
        if p["name"] == name:
            return p["id"]
    return bi_repo.create_product(conn, brand_id, name=name, actor=actor)["id"]


def _make_source(conn, brand_id: str, actor: str, text: Optional[str],
                 note: Optional[str] = None) -> Optional[str]:
    from datetime import datetime, timezone

    text = (text or "").strip()
    if not text or text == "無":
        return None
    row = bi_repo.create_source_reference(
        conn, brand_id, actor=actor, title=text, source_type="other",
        captured_date=datetime.now(timezone.utc).date().isoformat(), note=(note or None),
    )
    return row["id"]


def resolve_item(conn: sqlite3.Connection, brand_id: str, item_id: str, outcome: str,
                 processed_by: str, client_evidence: Optional[str] = None,
                 target_table: Optional[str] = None, target_id: Optional[str] = None,
                 edits: Optional[dict] = None, rule_severity: Optional[str] = None) -> dict:
    """三種出口共用的唯一入口（03 §3A.3）。outcome：confirmed / pending_saved / discarded。

    寫目標表（依 kind）、回填 target_table/target_id、寫 audit_log 都在這裡完成。
    edits：人工修改後的欄位（title/content/category/scope_raw），先寫回 intake_item 再落地
    ——AI 的原始列（raw_row）不動，追溯照舊（決策 0013 用戶優先，取代 R10 強制來源）。
    """
    if outcome not in ("confirmed", "pending_saved", "discarded"):
        raise ValueError(f"不支援的出口：{outcome}")
    row = conn.execute(
        "SELECT * FROM intake_item WHERE brand_id = ? AND id = ?", (brand_id, item_id)
    ).fetchone()
    if row is None:
        raise ValueError("找不到這筆待處理內容")
    item = dict(row)
    if item["outcome"] != "pending":
        raise ValueError("這筆已經處理過了")

    actor = processed_by

    # 人工修改先寫回 intake_item（raw_row 保留 AI 原文），之後才依修改後的值落地
    if edits:
        allowed = {k: v for k, v in edits.items()
                   if k in ("title", "content", "category", "scope_raw") and v is not None}
        changed = {k: v for k, v in allowed.items() if item.get(k) != v}
        if changed:
            sets = ", ".join(f"{k} = ?" for k in changed)
            conn.execute(f"UPDATE intake_item SET {sets} WHERE id = ? AND brand_id = ?",
                         (*changed.values(), item_id, brand_id))
            item.update(changed)

    client_evidence = (client_evidence or "").strip() or None
    kind, category = item["kind"], item["category"]

    if outcome == "confirmed" and target_id is None:
        # 宣稱的 content 是查核脈絡說明，不是宣稱語句本身；有建 source 時存進它的 note。
        # 決策 0013：不再強制客戶證實來源——有提供就用，沒提供就用 AI 附的依據。
        evidence_text = client_evidence or item["evidence_source"]
        source_note = item["content"] if kind == "claim" else None
        src_id = _make_source(conn, brand_id, actor, evidence_text, note=source_note)
        if kind == "brand_fact":
            target = bi_repo.create_brand_fact(
                conn, brand_id, actor=actor, fact_type=category, label=item["title"],
                value=item["content"], status="confirmed", source_reference_id=src_id,
                confirmed_by=processed_by)
            target_table, target_id = "brand_fact", target["id"]
        elif kind == "product_fact":
            product_id = _ensure_product(conn, brand_id, actor, item["scope_raw"])
            target = bi_repo.create_product_fact(
                conn, brand_id, product_id, actor=actor, fact_type=category,
                label=item["title"], value=item["content"], status="confirmed",
                source_reference_id=src_id, confirmed_by=processed_by)
            target_table, target_id = "product_fact", target["id"]
        elif kind == "rule":
            product_id = (None if item["scope_raw"] == "整個品牌"
                          else _ensure_product(conn, brand_id, actor, item["scope_raw"]))
            # rule 表沒有標題欄：把標題併進 content 開頭「標題：內容」，不讓它憑空消失。
            title = (item["title"] or "").strip()
            rule_content = f"{title}：{item['content']}" if title else item["content"]
            # 嚴重度由逐條頁的把關人選擇（issue #1）；沒選就是「建議遵守」。
            target = bi_repo.create_rule(
                conn, brand_id, actor=actor, rule_type=category, content=rule_content,
                severity=(rule_severity if rule_severity in ("hard", "soft") else "soft"),
                product_id=product_id, source_reference_id=src_id)
            target_table, target_id = "rule", target["id"]
        else:  # claim（evidence_text 即 client_evidence，src_id 已含查核脈絡 note）
            product_id = (None if item["scope_raw"] == "整個品牌"
                          else _ensure_product(conn, brand_id, actor, item["scope_raw"]))
            target = bi_repo.create_claim(
                conn, brand_id, actor=actor, claim_text=item["title"], claim_type=category,
                product_id=product_id, evidence_source_reference_id=src_id)
            target_table, target_id = "claim", target["id"]

    elif outcome == "pending_saved" and target_id is None:
        if kind in ("brand_fact", "product_fact"):
            src_id = _make_source(conn, brand_id, actor, item["evidence_source"])
            if kind == "brand_fact":
                target = bi_repo.create_brand_fact(
                    conn, brand_id, actor=actor, fact_type=category, label=item["title"],
                    value=item["content"], status="pending", source_reference_id=src_id)
            else:
                product_id = _ensure_product(conn, brand_id, actor, item["scope_raw"])
                target = bi_repo.create_product_fact(
                    conn, brand_id, product_id, actor=actor, fact_type=category,
                    label=item["title"], value=item["content"], status="pending",
                    source_reference_id=src_id)
            target_table, target_id = kind, target["id"]
        # rule / claim 沒有待確認狀態（03 §3A.3）：留在本表等人再處理，不寫目標表。

    conn.execute(
        """UPDATE intake_item SET outcome = ?, client_evidence = ?, target_table = ?,
           target_id = ?, processed_by = ?, processed_at = ? WHERE brand_id = ? AND id = ?""",
        (outcome, client_evidence, target_table, target_id, processed_by, db.now_iso(),
         brand_id, item_id),
    )
    write_audit(
        conn, brand_id=brand_id, entity_type="intake_item", entity_id=item_id,
        action={"confirmed": "confirm", "pending_saved": "save_pending", "discarded": "discard"}[outcome],
        actor=processed_by, before={"outcome": "pending"},
        after={"outcome": outcome, "target_table": target_table, "target_id": target_id},
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM intake_item WHERE brand_id = ? AND id = ?", (brand_id, item_id)
    ).fetchone()
    return _item_to_display(row)


# ---------------------------------------------------------------------------
# 向清理登記處報到（決策：清理登記處 Q2 各模組自我登記）
# 刪品牌時由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
# ---------------------------------------------------------------------------

cleanup.register("建檔精靈", count_brand=count_brand_data, delete_brand=delete_brand_data)
