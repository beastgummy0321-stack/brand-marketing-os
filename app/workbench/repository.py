"""app/workbench/repository.py — private DB access for `workbench_brief`/`workbench_output`
(ticket workbench/02/03, ADR 0068 §1). Private to app/workbench (container contract §1): only
`jobs.py`, `__init__.py` and `routes.py` import this; nothing outside the package does.

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


def _validate_on_image_texts(request: dict) -> None:
    """票 03 §2：`kind='image_prompt'` 手動送出時，圖上文字沒有 copy 輸出可以接——
    必須是使用者自己填的 1～5 則、每則 27 字以內（creative-matrix.md §3.1：「」文字
    必須來自使用者，不是模型現編）。"""
    texts = request.get("on_image_texts")
    valid = (
        isinstance(texts, list) and 1 <= len(texts) <= 5
        and all(isinstance(t, str) and 0 < len(t) <= 27 for t in texts)
    )
    if not valid:
        raise ValueError("on_image_texts_required")


def submit_brief(conn, org_id: str, brand_id: str, brief: dict, *,
                  created_by: str) -> str:
    """寫一列 `workbench_brief`（`_parts_for()` 排到東西才 `status='queued'`，沒排到
    就是 `'done'`——沒有 part 要跑的 brief 是閒置的，不是在等佇列），依 `_parts_for()`
    排進 `background.workbench_generate`，回傳 brief id（契約頁 Exported shapes）。

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
    image_prompt_count = request.get("image_prompt_count")
    if image_prompt_count is not None and not (
        isinstance(image_prompt_count, int) and 1 <= image_prompt_count <= 30
    ):
        # 票 03 §2：範圍檢查在送出當下就做，不留到 worker 才發現——不管 kind 是什麼，
        # 只要 image_prompt_count 有值就會排 image_prompt part（`_parts_for()` 檔頭）。
        raise ValueError("count_out_of_range")
    if brief["kind"] == "image_prompt":
        _validate_on_image_texts(request)
    brief_id = new_id("wbb")
    parts = _parts_for(brief["kind"], request)
    # 沒有 part 要跑（例如 kind='image_prompt' 沒給 image_prompt_count）就沒有東西在排隊——
    # 這種 brief 是閒置的，不是「等佇列」，寫 'queued' 會讓 UI 顯示處理中卻永遠不會翻狀態
    # （walk 04 步驟 4：`round_running` 也會誤擋使用者第一次按產出）。
    status = "queued" if parts else "done"

    conn.execute(
        "INSERT INTO workbench_brief (id, org_id, brand_id, kind, source_kind, source_ref,"
        " product_id, audience_key, pain_key, angle_key, hook_key, proof_key, offer_key,"
        " format_key, coordinates_snapshot_json, visual_tone, visual_concept, style_key,"
        " request_json, status, created_by)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s)",
        (
            brief_id, org_id, brand_id, brief["kind"], brief["source_kind"],
            jsonb(brief.get("source_ref") or {}), product_id,
            coordinates.get("audience"), coordinates.get("pain"), coordinates.get("angle"),
            coordinates.get("hook"), coordinates.get("proof"), coordinates.get("offer"),
            coordinates.get("format"), jsonb(coordinates), brief.get("visual_tone"),
            brief.get("visual_concept"), style_key, jsonb(request), status, created_by,
        ),
    )
    for part in parts:
        count = request.get("image_prompt_count") if part == "image_prompt" else None
        background_enqueue(
            "background.workbench_generate", org_id=org_id,
            lock=f"workbench:{brief_id}:{part}",
            brand_id=brand_id, brief_id=brief_id, part=part, count=count,
        )
    conn.commit()
    return brief_id


_CREATABLE_KINDS = frozenset({"copy", "image_prompt", "video_script", "free"})


def create_brief(conn, org_id: str, brand_id: str, brief: dict, *, created_by: str) -> str:
    """`POST /briefs`（票 03）專屬入口：`kind='ad_creative'` 是 `app.schedule` 那邊
    （票 05 之後）直接呼叫 `submit_brief()` 才用的 kind，這支 HTTP 端點不開放
    （契約頁「Routes」）——`submit_brief()` 本身的簽章與行為對其他呼叫端保持不變，不
    在那裡加這道檢查。其餘驗證（style_key／product_id／image_prompt_count／
    on_image_texts）都在 `submit_brief()` 裡，這裡不重複。"""
    if brief.get("kind") not in _CREATABLE_KINDS:
        raise ValueError("kind_unknown")
    return submit_brief(conn, org_id, brand_id, brief, created_by=created_by)


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


# ---------------------------------------------------------------------------
# 票 03：routes.py 專用——list/detail/mutate。跟上面 `briefs_for_source()`／
# `adopted_output()`（app.schedule 之後會呼叫）不是同一組：這裡的 `parts` 形狀是給
# 這個模組自己的畫面（latest_round／adopted_round／running），那兩支是給排程模組的
# 摘要（latest_round／adopted bool）——兩邊各自的呼叫端要的東西不一樣，不合併。
# ---------------------------------------------------------------------------

_LIST_STATUS_FILTERS = {
    "active": "closed_at IS NULL", "closed": "closed_at IS NOT NULL", "all": "TRUE",
}


def _part_summaries(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                     status: str) -> dict:
    rows = conn.execute(
        "SELECT part, MAX(generation_round) AS latest_round,"
        " MAX(generation_round) FILTER (WHERE adopted_at IS NOT NULL) AS adopted_round"
        " FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
        " GROUP BY part",
        (org_id, brand_id, brief_id),
    ).fetchall()
    # 沒有每個 part 自己的狀態欄（一張 brief 只有一個 status），round_running 也是照
    # brief 這個欄位判斷（`run_part()` 檔頭）——這裡老實回報同一個值，不假裝有更細的
    # 顆粒度。
    running = status in ("queued", "running")
    return {
        r["part"]: {"latest_round": r["latest_round"], "adopted_round": r["adopted_round"],
                     "running": running}
        for r in (dict(row) for row in rows)
    }


def _brief_summary(conn, brand_id: str, row: dict) -> dict:
    # `conn` 這裡不標 `_AnyConn`，理由跟 `submit_brief()` 檔頭一樣：`bi_repo.get_product()`
    # 簽章吃 `Conn`（非 `ConnProxy`），留白讓 pyright 用型別不定（Unknown）通過。
    product_id = row["product_id"]
    product = bi_repo.get_product(conn, brand_id, product_id) if product_id else None
    return {
        "id": row["id"], "kind": row["kind"], "source_kind": row["source_kind"],
        "source_ref": row["source_ref"], "product_id": product_id,
        "product_name": product["name"] if product else None,
        "style_key": row["style_key"], "status": row["status"],
        "last_error": row["last_error"], "closed_at": row["closed_at"],
        "created_at": row["created_at"],
        "parts": _part_summaries(conn, row["org_id"], brand_id, row["id"], row["status"]),
    }


def list_briefs(conn: _AnyConn, org_id: str, brand_id: str, status: str = "active") -> list:
    """`GET /briefs?status=`（票 03）：`ValueError("status_unknown")` for anything other
    than active／closed／all. 「有沒有關閉」讀 `closed_at`（不是 `status`）——`reopen_brief()`
    兩欄一起改，這裡才對得上（票面 contradiction check 第二條）。"""
    if status not in _LIST_STATUS_FILTERS:
        raise ValueError("status_unknown")
    rows = conn.execute(
        f"SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
        f" AND {_LIST_STATUS_FILTERS[status]} ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    return [_brief_summary(conn, brand_id, dict(r)) for r in rows]


def brief_detail(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> dict | None:
    """`GET /briefs/{id}`（票 03）：summary 加上全部輪次的 outputs，找不到回 `None`
    （路由把 `None` 轉成 404 `brief_unknown`）。"""
    row = get_brief(conn, org_id, brand_id, brief_id)
    if row is None:
        return None
    detail = _brief_summary(conn, brand_id, row)
    detail["coordinates"] = row["coordinates_snapshot_json"]
    detail["visual_tone"] = row["visual_tone"]
    detail["visual_concept"] = row["visual_concept"]
    detail["request"] = row["request_json"]
    output_rows = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
        " ORDER BY part, generation_round",
        (org_id, brand_id, brief_id),
    ).fetchall()
    detail["outputs"] = [
        {"id": r["id"], "part": r["part"], "generation_round": r["generation_round"],
         "adopted_at": r["adopted_at"], "body_json": r["body_json"],
         "coordinates_json": r["coordinates_json"], "llm_task_id": r["llm_task_id"],
         "created_at": r["created_at"]}
        for r in (dict(rr) for rr in output_rows)
    ]
    return detail


_PARTS_BY_KIND = {
    "ad_creative": frozenset({"copy", "image_prompt"}), "copy": frozenset({"copy"}),
    "image_prompt": frozenset({"image_prompt"}), "video_script": frozenset({"video_script"}),
    "free": frozenset({"free"}),
}


def run_part(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str, part: str, *,
             count: int | None = None) -> None:
    """`POST .../parts/{part}/run`（票 03 §2）：`submit_brief()` 排隊那一半的重跑版——
    這裡跟它共用同一個 lock 字串（`workbench:{brief_id}:{part}`）跟 `queued` 寫法，一個
    地方決定。`ValueError`：`brief_unknown`／`part_unknown`／`brief_closed`／
    `round_running`／`count_out_of_range`／`on_image_texts_required`（routes.py 逐一
    對照成 HTTP 狀態碼）。

    `round_running` 只看 brief 這一欄 `status`（不是「這個 part 有沒有活躍的鎖」）——
    一張 brief 只有一個 status 欄，這裡老實照它判斷；一個 job 卡在 running 沒有寫回
    failed（例如 process 被殺）會讓這張 brief 再也跑不了下一輪，是已知、未在這張票修的
    缺口（票面 contradiction check 第一條，日後才加逾時）。"""
    from app.background import enqueue as background_enqueue

    brief = get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise ValueError("brief_unknown")
    if part not in _PARTS_BY_KIND.get(brief["kind"], frozenset()):
        raise ValueError("part_unknown")
    if brief["closed_at"] is not None:
        raise ValueError("brief_closed")
    if brief["status"] in ("queued", "running"):
        raise ValueError("round_running")
    if part == "image_prompt":
        if count is None or not (1 <= count <= 30):
            raise ValueError("count_out_of_range")
        headlines_output = adopted_output(conn, org_id, brand_id, brief_id, "copy")
        headlines = (headlines_output or {}).get("body_json", {}).get("headlines") or []
        on_image_texts = (brief.get("request_json") or {}).get("on_image_texts") or []
        if not headlines and not on_image_texts:
            # 跟 jobs.py `_run()` 同一條規則（票 03 §3），但這裡先擋在 enqueue 之前——
            # 不花那通一定會被拒絕的 LLM 呼叫的錢。
            raise ValueError("on_image_texts_required")
    mark_brief_status(conn, org_id, brand_id, brief_id, "queued")
    background_enqueue(
        "background.workbench_generate", org_id=org_id,
        lock=f"workbench:{brief_id}:{part}",
        brand_id=brand_id, brief_id=brief_id, part=part, count=count,
    )


def adopt_output_for_brief(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                            output_id: str) -> None:
    """`POST .../outputs/{output_id}/adopt`（票 03）：確認 brief 存在、未關閉、
    output 真的屬於這張 brief，才呼叫既有 `adopt_output()`（票 02，簽章與行為不
    變——`app/tests/test_workbench.py` 直接呼叫它）做真正的 UPDATE。`ValueError`：
    `brief_unknown`／`brief_closed`／`output_unknown`。"""
    brief = get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise ValueError("brief_unknown")
    if brief["closed_at"] is not None:
        raise ValueError("brief_closed")
    output = conn.execute(
        "SELECT id FROM workbench_output WHERE org_id = %s AND brand_id = %s"
        " AND brief_id = %s AND id = %s",
        (org_id, brand_id, brief_id, output_id),
    ).fetchone()
    if output is None:
        raise ValueError("output_unknown")
    adopt_output(conn, org_id, brand_id, output_id)


def close_brief(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> None:
    """`POST .../close`（票 03）：關閉，隱藏在預設列表外（`list_briefs` 的 active 濾
    器）；已採用的內容仍算數（契約頁「Module-local」段）。`ValueError("brief_unknown")`
    when not found."""
    row = conn.execute(
        "UPDATE workbench_brief SET status = 'closed', closed_at = now(), updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s RETURNING id",
        (org_id, brand_id, brief_id),
    ).fetchone()
    conn.commit()
    if row is None:
        raise ValueError("brief_unknown")


def reopen_brief(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> None:
    """`POST .../reopen`（票 03）：清 `closed_at`；關閉前的 status 沒有存下來，所以
    ——票面決定，可逆——這張 brief 有任何 output 就回 `'done'`，否則 `'failed'`
    （`last_error` 不動）。兩欄（`status`／`closed_at`）一起改，`list_briefs()` 的
    `active` 濾器只看 `closed_at` 才會對得上（票面 contradiction check 第二條）。
    `ValueError("brief_unknown")` when not found."""
    brief = get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise ValueError("brief_unknown")
    exists_row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM workbench_output"
        " WHERE org_id = %s AND brand_id = %s AND brief_id = %s) AS e",
        (org_id, brand_id, brief_id),
    ).fetchone()
    has_output = bool(exists_row["e"]) if exists_row is not None else False
    conn.execute(
        "UPDATE workbench_brief SET status = %s, closed_at = NULL, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        ("done" if has_output else "failed", org_id, brand_id, brief_id),
    )
    conn.commit()


def delete_brief(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> None:
    """`DELETE /briefs/{id}`（票 03）：outputs 靠 `ON DELETE CASCADE`（migration）跟著
    刪，這裡不用另外下一次 DELETE。`ValueError("brief_unknown")` when not found."""
    row = conn.execute(
        "DELETE FROM workbench_brief WHERE org_id = %s AND brand_id = %s AND id = %s"
        " RETURNING id",
        (org_id, brand_id, brief_id),
    ).fetchone()
    conn.commit()
    if row is None:
        raise ValueError("brief_unknown")


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
