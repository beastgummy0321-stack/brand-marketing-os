"""品牌人物誌的資料入口；不依賴 LLM 或 intake。"""


from app.core import cleanup
from app.core.audit import write_audit
from app.core.db import DEV_ORG_ID, Conn, new_id, now_utc

PERSONA_FIELDS = ("title", "when_needed", "care_about", "hesitation", "where_to_find")
PERSONA_FIELD_LABELS = {
    "title": "怎麼稱呼",
    "when_needed": "什麼時候需要",
    "care_about": "在意什麼",
    "hesitation": "猶豫什麼",
    "where_to_find": "去哪裡找他",
}


def list_personas(conn: Conn, brand_id: str, *, limit: int = None) -> list:
    # 票 02-3a：Postgres 無 rowid，改用 created_at, id 排序。原註解：同一批通常在同一
    # 微秒寫入，rowid 保留模型回傳順序，id 帶亂數不能當 tie-break——這個 tie-break 精度
    # 損失是拿掉 rowid 的已知代價（見 app/ads/plan.py list_cell_angles 同款取捨）。
    sql = "SELECT * FROM persona WHERE brand_id = %s ORDER BY created_at, id"
    params = [brand_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(max(int(limit), 0))
    return [dict(row) for row in conn.execute(sql, params)]


def replace_personas(conn: Conn, brand_id: str, rows: list) -> list:
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
        conn.execute("DELETE FROM persona WHERE brand_id = %s", (brand_id,))
        for row in normalized:
            conn.execute(
                "INSERT INTO persona (id, org_id, brand_id, title, when_needed, care_about, hesitation, "
                "where_to_find, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id("psn"), DEV_ORG_ID, brand_id, row["title"], row["when_needed"], row["care_about"],
                 row["hesitation"], row["where_to_find"], now_utc()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return list_personas(conn, brand_id)


def update_persona(conn: Conn, brand_id: str, persona_id: str, fields: dict, *, actor: str) -> dict:
    """人工修改一張人物誌；五欄齊全才落檔，並保留前後審計。"""
    clean = {field: str(fields.get(field) or "").strip() for field in PERSONA_FIELDS}
    missing = next((field for field in PERSONA_FIELDS if not clean[field]), None)
    if missing:
        raise ValueError(f"請填寫「{PERSONA_FIELD_LABELS[missing]}」。")
    before_row = conn.execute(
        "SELECT * FROM persona WHERE id = %s AND brand_id = %s", (persona_id, brand_id),
    ).fetchone()
    if before_row is None:
        raise LookupError("找不到這位典型客人。")
    before = dict(before_row)
    try:
        conn.execute(
            "UPDATE persona SET title = %s, when_needed = %s, care_about = %s, hesitation = %s, "
            "where_to_find = %s WHERE id = %s AND brand_id = %s",
            (*[clean[field] for field in PERSONA_FIELDS], persona_id, brand_id),
        )
        after = dict(conn.execute(
            "SELECT * FROM persona WHERE id = %s AND brand_id = %s", (persona_id, brand_id),
        ).fetchone())
        write_audit(conn, brand_id=brand_id, entity_type="persona", entity_id=persona_id,
                    action="update", actor=actor, before=before, after=after)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return after


def count_brand_data(conn, brand_id: str) -> list:
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM persona WHERE brand_id = %s", (brand_id,)).fetchone()["n"]
    return [("人物誌", count)] if count else []


def delete_brand_data(conn, brand_id: str) -> dict:
    counts = dict(count_brand_data(conn, brand_id))
    conn.execute("DELETE FROM persona WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register(
    "人物誌", count_brand=count_brand_data, delete_brand=delete_brand_data,
    brand_tables={"persona"}, count_product=None, delete_product=None, product_tables=frozenset(),
)
