"""app/workbench/repository.py — private DB access for `workbench_brief`/`workbench_output`
(ticket workbench/02, ADR 0068 §1). Private to app/workbench (container contract §1): only
`jobs.py` and `__init__.py` import this; nothing outside the package does.

`list_coordinate_vocabulary()` reads `brand_coordinate`/`feedback` — tables `app.schedule`
owns — by raw SQL, never by importing `app.schedule` (contract "Must not import or touch":
app.schedule; container contract rule 5 allows duplicating the query, the precedent being
`scripts/workbench_probe.py`'s own copy of the same read, ticket 01). Read-only: unlike
`app.schedule.repository.list_coordinates()`, this never calls `ensure_coordinates_seeded()` —
seeding a brand's coordinate vocabulary is schedule's job, not something a prompt-builder
should trigger as a side effect of reading.
"""

import json
from pathlib import Path

from app.brand_intelligence import repository as bi_repo
from app.core import cleanup
from app.core.db import Conn, ConnProxy, jsonb, new_id

_AnyConn = Conn | ConnProxy

_STYLES_PATH = Path(__file__).resolve().parent / "image_styles.json"
STYLES: list = json.loads(_STYLES_PATH.read_text(encoding="utf-8"))


def get_style(style_key: str) -> dict:
    """`ValueError("style_unknown")` for a key not in `image_styles.json`
    (routes.py maps it to 400 in ticket 03)."""
    for style in STYLES:
        if style["key"] == style_key:
            return style
    raise ValueError("style_unknown")


def _parts_for(kind: str, request: dict) -> list:
    """哪些 part 現在就要排隊生成（票 §2）：`ad_creative`／`copy` 排 `copy`；
    `request_json.image_prompt_count` 有值就排 `image_prompt`（跟 kind 是不是
    `image_prompt` 無關——一張 `ad_creative` 工單同時要文案跟圖時，兩個 part 都排）；
    `video_script`／`free` 各自的 kind 排自己那個 part。沒有給張數的 `image_prompt` 工單
    先不排任何 job（ADR 0068 §7：張數是使用者的，沒有預設值）。"""
    parts = []
    if kind in ("ad_creative", "copy"):
        parts.append("copy")
    if request.get("image_prompt_count"):
        parts.append("image_prompt")
    if kind == "video_script":
        parts.append("video_script")
    if kind == "free":
        parts.append("free")
    return parts


def submit_brief(conn, org_id: str, brand_id: str, brief: dict, *,
                  created_by: str) -> str:
    """寫一列 `workbench_brief`（`status='queued'`），依 `_parts_for()` 排進
    `background.workbench_generate`，回傳 brief id（契約頁 Exported shapes）。

    `conn` 這裡不標 `_AnyConn`：`bi_repo.get_product()` 簽章吃 `Conn`（非
    `ConnProxy`），比照 `app/schedule/routes.py:29-33` 既有寫法——`conn` 參數留白
    讓 pyright 用型別不定（Unknown）通過，呼叫端只在真正呼叫這裡的地方傳入
    `web.conn`（`ConnProxy`）或一條真的 `Conn`。"""
    from app.background import enqueue as background_enqueue

    style_key = brief.get("style_key") or "ugc"
    get_style(style_key)  # 未知 style_key 在這裡就炸，不留到生成 job 才發現
    product_id = brief.get("product_id")
    if product_id is not None and bi_repo.get_product(conn, brand_id, product_id) is None:
        # 租戶界線先於資料寫入：product_id 指向別的品牌就在這裡炸，不留到 INSERT
        # 之後（`workbench_baseline.sql` 的 REFERENCES product(id) 不分品牌，
        # 同 app/schedule/routes.py:145-158 的 `_validate_products` 做法）。
        raise ValueError("product_unknown")
    coordinates = brief.get("coordinates") or {}
    request = brief.get("request") or {}
    brief_id = new_id("wbb")

    conn.execute(
        "INSERT INTO workbench_brief (id, org_id, brand_id, kind, source_kind, source_ref,"
        " product_id, audience_key, pain_key, angle_key, hook_key, proof_key, offer_key,"
        " format_key, coordinates_snapshot_json, visual_tone, visual_concept, style_key,"
        " request_json, status, created_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, 'queued', %s)",
        (
            brief_id, org_id, brand_id, brief["kind"], brief["source_kind"],
            jsonb(brief.get("source_ref") or {}), product_id,
            coordinates.get("audience"), coordinates.get("pain"), coordinates.get("angle"),
            coordinates.get("hook"), coordinates.get("proof"), coordinates.get("offer"),
            coordinates.get("format"), jsonb(coordinates), brief.get("visual_tone"),
            brief.get("visual_concept"), style_key, jsonb(request), created_by,
        ),
    )
    for part in _parts_for(brief["kind"], request):
        count = request.get("image_prompt_count") if part == "image_prompt" else None
        background_enqueue(
            "background.workbench_generate", org_id=org_id,
            lock=f"workbench:{brief_id}:{part}",
            brand_id=brand_id, brief_id=brief_id, part=part, count=count,
        )
    conn.commit()
    return brief_id


def get_brief(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, brief_id),
    ).fetchone()
    return dict(row) if row is not None else None


def mark_brief_status(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                       status: str) -> None:
    conn.execute(
        "UPDATE workbench_brief SET status = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (status, org_id, brand_id, brief_id),
    )
    conn.commit()


def mark_brief_failed(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                       last_error: str) -> None:
    conn.execute(
        "UPDATE workbench_brief SET status = 'failed', last_error = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (last_error, org_id, brand_id, brief_id),
    )
    conn.commit()


def next_round(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str, part: str) -> int:
    """這個 brief 這個 part 目前最大的 `generation_round` + 1（第一次是 1）。"""
    row = conn.execute(
        "SELECT COALESCE(MAX(generation_round), 0) AS n FROM workbench_output"
        " WHERE org_id = %s AND brand_id = %s AND brief_id = %s AND part = %s",
        (org_id, brand_id, brief_id, part),
    ).fetchone()
    return (row["n"] if row is not None else 0) + 1


def write_output(conn: _AnyConn, *, org_id: str, brand_id: str, brief_id: str, part: str,
                  generation_round: int, body_json: dict, coordinates_json: dict | None,
                  llm_task_id: str | None) -> dict:
    output_id = new_id("wbo")
    conn.execute(
        "INSERT INTO workbench_output (id, org_id, brand_id, brief_id, part, generation_round,"
        " body_json, coordinates_json, llm_task_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            output_id, org_id, brand_id, brief_id, part, generation_round,
            jsonb(body_json), jsonb(coordinates_json) if coordinates_json is not None else None,
            llm_task_id,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, output_id),
    ).fetchone()
    assert row is not None  # 剛寫進去的那一列，找不到代表資料庫壞了，不是正常分支
    return dict(row)


def adopt_output(conn: _AnyConn, org_id: str, brand_id: str, output_id: str) -> dict | None:
    """把這一列標成已採用（`adopted_at`）。這支不是五個匯出之一（契約頁只講讀
    `adopted_output()`），路由層的採用端點是票 03 的事——這裡先把寫入面備好，供票 03 的
    路由與這張票的測試（case 4：round 1 採用之後 round 2 不算數）直接呼叫。"""
    conn.execute(
        "UPDATE workbench_output SET adopted_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, output_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, output_id),
    ).fetchone()
    return dict(row) if row is not None else None


def briefs_for_source(conn: _AnyConn, org_id: str, brand_id: str, source_kind: str,
                       source_ref: dict) -> list:
    """契約頁 Exported shapes：`source_ref` 包含給定 dict 全部鍵的那些 brief（JSONB
    containment，`@>`），各自附上 status 與每個 part 目前最新一輪的摘要。"""
    rows = conn.execute(
        "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s AND source_kind = %s"
        " AND source_ref @> %s ORDER BY created_at",
        (org_id, brand_id, source_kind, jsonb(source_ref)),
    ).fetchall()
    briefs = [dict(r) for r in rows]
    for brief in briefs:
        parts_rows = conn.execute(
            "SELECT part, MAX(generation_round) AS latest_round,"
            " bool_or(adopted_at IS NOT NULL) AS has_adopted"
            " FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
            " GROUP BY part",
            (org_id, brand_id, brief["id"]),
        ).fetchall()
        brief["parts"] = {
            r["part"]: {"latest_round": r["latest_round"], "adopted": bool(r["has_adopted"])}
            for r in parts_rows
        }
    return briefs


def adopted_output(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                    part: str) -> dict | None:
    """契約頁 Exported shapes：那個 part 已採用的一列，否則最新一輪，否則 `None`；回傳值
    是那一列本身外加 `is_adopted`。"""
    row = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
        " AND part = %s AND adopted_at IS NOT NULL ORDER BY generation_round DESC LIMIT 1",
        (org_id, brand_id, brief_id, part),
    ).fetchone()
    is_adopted = row is not None
    if row is None:
        row = conn.execute(
            "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s"
            " AND brief_id = %s AND part = %s ORDER BY generation_round DESC LIMIT 1",
            (org_id, brand_id, brief_id, part),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["is_adopted"] = is_adopted
    return result


def list_coordinate_vocabulary(conn: _AnyConn, org_id: str, brand_id: str) -> list:
    """跟 `scripts/workbench_probe.py::_coordinate_rows`／`app.schedule.repository.
    list_coordinates()` 同一份查法（複製，不 import——app.schedule 私有；不呼叫
    `ensure_coordinates_seeded()`，見本檔檔頭）。"""
    rows = conn.execute(
        "SELECT c.*, EXISTS (SELECT 1 FROM feedback f WHERE f.scope = 'coordinate'"
        " AND f.coordinate_id = c.id AND f.lifted_at IS NULL) AS rejected"
        " FROM brand_coordinate c WHERE c.org_id = %s AND c.brand_id = %s"
        " ORDER BY c.dimension, c.category NULLS LAST, c.label",
        (org_id, brand_id),
    ).fetchall()
    return [
        {"dimension": r["dimension"], "label": r["label"],
         "attributes": r["attributes_json"] or {}, "disabled_at": r["disabled_at"],
         "rejected": bool(r["rejected"])}
        for r in (dict(row) for row in rows)
    ]


_CHILD_TABLES = (
    ("workbench_output", "工作檯產出"),
    ("workbench_brief", "工作檯工單"),
)


def _count_brand(conn: _AnyConn, brand_id: str) -> list:
    counts = []
    for table, label in _CHILD_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()
        counts.append((label, row["n"] if row is not None else 0))
    return counts


def _delete_brand(conn: _AnyConn, brand_id: str) -> dict:
    counts = dict(_count_brand(conn, brand_id))
    for table, _label in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register(
    "素材工作檯",
    count_brand=_count_brand,
    delete_brand=_delete_brand,
    brand_tables=frozenset({"workbench_brief", "workbench_output"}),
    count_product=None,
    delete_product=None,
    product_tables=frozenset(),
)
