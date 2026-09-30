"""app/intake/repository.py — intake_draft / intake_item 兩張表的存取層。

介面契約與欄位權威原文件皆已被 5eca0db 清除；欄位權威現在是
supabase/migrations/ 本身。一律 conn 開頭、一律帶 brand_id 過濾
（§3A.4 第 5 點：本模組不開無 brand 過濾的入口）。

F42-I14 removed the paste-back／review／truth-card writers of intake_item (`resolve_item` and
friends); the table and its rows stay (test data, no migration in that issue).
"""


from app.brand_intelligence import repository as bi_repo
from app.core import cleanup, db
from app.core import settings as coresettings

# intake_item.kind（內部代碼）↔ 畫面中文（原對照表已被 5eca0db 清除，這份 dict 就是權威）
KIND_TO_HUMAN = {
    "brand_fact": "品牌事實",
    "product_fact": "產品事實",
    "rule": "限制規則",
    "claim": "宣稱",
    "customer_voice": "顧客原話",
}
HUMAN_TO_KIND = {v: k for k, v in KIND_TO_HUMAN.items()}

# update_draft 只允許 03 §3A.2 列出的欄位（id / brand_id / created_at 除外）
_DRAFT_FIELDS = {
    "status", "current_step", "current_question_no", "description", "photos_json",
    "research_urls_json", "scan_sources_json", "scan_impressions_json", "scan_llm_task_id",
    "qa_json", "scan_products_json", "handoff_depth", "handoff_prompt", "handoff_generated_at", "paste_raw",
    "paste_validation_json", "repair_llm_task_id", "cost_limit", "llm_task_refs_json",
    "completed_at", "offerings_choice_json", "prefill_json",
}


def _row_to_dict(row) -> dict | None:
    return dict(row) if row is not None else None


def count_brand_data(conn: db.Conn, brand_id: str) -> list:
    """回傳 [(中文名稱, 筆數)]，給品牌刪除確認頁列出本模組會被清掉的資料。"""
    return [
        ("建檔精靈草稿", conn.execute(
            "SELECT COUNT(*) AS n FROM intake_draft WHERE brand_id = %s", (brand_id,)).fetchone()["n"]),
        ("建檔精靈逐條紀錄", conn.execute(
            "SELECT COUNT(*) AS n FROM intake_item WHERE brand_id = %s", (brand_id,)).fetchone()["n"]),
    ]


def delete_brand_data(conn: db.Conn, brand_id: str) -> dict:
    """品牌被刪除時，清掉本模組掛在該品牌下的草稿與逐條紀錄（決策 0015）。

    稽核由呼叫端（品牌刪除那筆 audit_log）一起記，這裡不另外寫。
    只下 DELETE，不 commit、不 rollback——交易的開關統一在最外層的
    brand_intelligence.delete_brand()（Q4 全有全無）。
    """
    counts = dict(count_brand_data(conn, brand_id))
    conn.execute("DELETE FROM intake_item WHERE brand_id = %s", (brand_id,))
    conn.execute("DELETE FROM intake_draft WHERE brand_id = %s", (brand_id,))
    return counts


def create_draft(conn: db.Conn, brand_id: str, description: str,
                 photos: list, research_urls: list, actor: str,
                 cost_limit: float | None = None) -> dict:
    """建立一份進行中草稿。photos 為 §3A.2 形狀 [{file_path, display_name, size_bytes}]。

    一品牌一份進行中草稿由 DB 部分唯一索引擋（§3A.4 第 1 點），這裡不重複檢查。
    """
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    if cost_limit is None:
        cost_limit = coresettings.get_intake_budget_limit(conn, org_id=org_id)
    draft_id = db.new_id("idr")
    ts = db.now_utc()
    conn.execute(
        """INSERT INTO intake_draft (
            id, org_id, brand_id, status, current_step, current_question_no, description,
            photos_json, research_urls_json, cost_limit, llm_task_refs_json,
            created_at, updated_at
        ) VALUES (%s, %s, %s, 'draft', 2, 0, %s, %s, %s, %s, '[]', %s, %s)""",
        (draft_id, org_id, brand_id, description, db.jsonb(photos),
         db.jsonb(research_urls), cost_limit, ts, ts),
    )
    conn.commit()
    return get_draft(conn, brand_id, draft_id)


def get_active_draft(conn: db.Conn, brand_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = %s AND status = 'draft'", (brand_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_latest_completed_draft(conn: db.Conn, brand_id: str) -> dict | None:
    """重新調研的預帶來源：最近一輪已完成的草稿（issue #1）。"""
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = %s AND status = 'completed' "
        "ORDER BY completed_at DESC LIMIT 1", (brand_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_draft(conn: db.Conn, brand_id: str, draft_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM intake_draft WHERE brand_id = %s AND id = %s", (brand_id, draft_id)
    ).fetchone()
    return _row_to_dict(row)


def update_draft(conn: db.Conn, brand_id: str, draft_id: str, **fields) -> dict:
    """`*_json` 欄位傳原生 dict/list 即可，這裡統一包一層 `db.jsonb()`——呼叫端（state.py）
    不必自己 json.dumps（02-3b：單一收口，不逐一呼叫端轉換）。"""
    unknown = set(fields) - _DRAFT_FIELDS
    if unknown:
        raise ValueError(f"intake_draft 不允許更新欄位：{sorted(unknown)}")
    if fields:
        fields = {k: (db.jsonb(v) if k.endswith("_json") and v is not None else v)
                  for k, v in fields.items()}
        sets = ", ".join(f"{k} = %s" for k in fields)
        conn.execute(
            f"UPDATE intake_draft SET {sets}, updated_at = %s WHERE brand_id = %s AND id = %s",
            (*fields.values(), db.now_utc(), brand_id, draft_id),
        )
        conn.commit()
    return get_draft(conn, brand_id, draft_id)


def complete_draft(conn: db.Conn, brand_id: str, draft_id: str) -> dict:
    return update_draft(conn, brand_id, draft_id, status="completed", completed_at=db.now_utc())


def add_llm_task_ref(conn: db.Conn, brand_id: str, draft_id: str,
                     llm_task_id: str, purpose: str) -> None:
    """只存 id 與人話用途，不存金額副本（03 §3A.5 第 5 點）。"""
    draft = get_draft(conn, brand_id, draft_id)
    refs = draft["llm_task_refs_json"] or []
    refs.append({"llm_task_id": llm_task_id, "purpose": purpose})
    update_draft(conn, brand_id, draft_id, llm_task_refs_json=refs)


def list_llm_cost_items(conn: db.Conn, draft: dict) -> list:
    """花費明細：依 refs 逐筆讀 llm_task 的 cost / status，即時算、不存副本。"""
    items = []
    for ref in draft["llm_task_refs_json"] or []:
        row = conn.execute(
            "SELECT cost, status FROM llm_task WHERE id = %s", (ref["llm_task_id"],)
        ).fetchone()
        if row is None:
            continue
        failed = row["status"] != "succeeded"
        items.append({"label": ref["purpose"], "amount": float(row["cost"] or 0), "failed": failed})
    return items


# ---------------------------------------------------------------------------
# intake_item: the retired paste-back rows (F42-I14 removed the paste/review/truth-card flow).
# The table stays in the schema with its test data; nothing in the app writes it any more.
# `create_items` is kept only so the brand-delete test can seed a row the cleanup registry must
# wipe (app/tests/test_brand_delete.py).
# ---------------------------------------------------------------------------

def _category_to_internal(kind_human: str, label: str) -> str:
    from app.core import vocab as md

    source = {
        "品牌事實": md.BRAND_FACT_TYPES,
        "產品事實": md.PRODUCT_FACT_TYPES,
        "限制規則": md.RULE_TYPES,
        "宣稱": md.CLAIM_TYPES,
        "顧客原話": list(md.CUSTOMER_VOICE_TASK_LAYERS.items()),
    }[kind_human]
    return next((internal for internal, human in source if human == label), label)


def create_items(conn: db.Conn, brand_id: str, draft_id: str, rows: list) -> int:
    """Write `rows` ({kind, category, title, content, scope, evidence}, Chinese kind/category)
    as pending intake_item rows in one transaction; returns how many were written."""
    ts = db.now_utc()
    org_id = bi_repo.get_brand(conn, brand_id)["org_id"]
    try:
        for i, r in enumerate(rows, start=1):
            conn.execute(
                """INSERT INTO intake_item (
                    id, org_id, intake_draft_id, brand_id, row_no, raw_row, kind, category, title,
                    content, scope_raw, evidence_source, outcome, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)""",
                (db.new_id("iit"), org_id, draft_id, brand_id, i,
                 " | ".join([r["kind"], r["category"], r["title"], r["content"], r["scope"], r["evidence"]]),
                 HUMAN_TO_KIND[r["kind"]], _category_to_internal(r["kind"], r["category"]),
                 r["title"], r["content"], r["scope"], r["evidence"], ts),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


# ---------------------------------------------------------------------------
# 向清理登記處報到（決策：清理登記處 Q2 各模組自我登記）
# 刪品牌時由登記處統一呼叫，本模組不必再被別人手寫死「記得通知它」。
# ---------------------------------------------------------------------------

cleanup.register("建檔精靈", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={"intake_draft", "intake_item"},
                 count_product=None, delete_product=None, product_tables=frozenset())
