# -*- coding: utf-8 -*-
"""品牌人物誌的資料入口；不依賴 LLM 或 intake。"""

import sqlite3

from app.core import cleanup
from app.core.db import new_id, now_iso


PERSONA_FIELDS = ("title", "when_needed", "care_about", "hesitation", "where_to_find")


def list_personas(conn: sqlite3.Connection, brand_id: str, *, limit: int = None) -> list:
    # 同一批通常在同一微秒寫入；rowid 保留模型回傳順序，不能拿同毫秒帶亂數的 id 排。
    sql = "SELECT * FROM persona WHERE brand_id = ? ORDER BY created_at, rowid"
    params = [brand_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(int(limit), 0))
    return [dict(row) for row in conn.execute(sql, params)]


def replace_personas(conn: sqlite3.Connection, brand_id: str, rows: list) -> list:
    """新一批先完整驗證，通過後才取代舊批；不會先清空再發現資料壞掉。"""
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("人物誌格式不完整。")
        clean = {field: str(row.get(field) or "").strip() for field in PERSONA_FIELDS}
        if any(not clean[field] for field in PERSONA_FIELDS):
            raise ValueError("人物誌五個欄位都要有內容。")
        normalized.append(clean)
    try:
        conn.execute("DELETE FROM persona WHERE brand_id = ?", (brand_id,))
        for row in normalized:
            conn.execute(
                "INSERT INTO persona (id, brand_id, title, when_needed, care_about, hesitation, "
                "where_to_find, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("psn"), brand_id, row["title"], row["when_needed"], row["care_about"],
                 row["hesitation"], row["where_to_find"], now_iso()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return list_personas(conn, brand_id)


def count_brand_data(conn, brand_id: str) -> list:
    count = conn.execute("SELECT COUNT(*) FROM persona WHERE brand_id = ?", (brand_id,)).fetchone()[0]
    return [("人物誌", count)] if count else []


def delete_brand_data(conn, brand_id: str) -> dict:
    counts = dict(count_brand_data(conn, brand_id))
    conn.execute("DELETE FROM persona WHERE brand_id = ?", (brand_id,))
    return counts


cleanup.register(
    "人物誌", count_brand=count_brand_data, delete_brand=delete_brand_data,
    brand_tables={"persona"}, count_product=None, delete_product=None, product_tables=frozenset(),
)
