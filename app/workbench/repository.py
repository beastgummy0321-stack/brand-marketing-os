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
from datetime import UTC, datetime
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


_PART_NAMES = frozenset({"copy", "image_prompt", "video_script", "free"})
_COPY_LENGTHS = frozenset({"short", "medium", "long"})


def submit_brief(conn, org_id: str, brand_id: str, brief: dict, *, pack_id: str,
                  name: str | None = None, required_outputs: dict | None = None) -> str:
    """寫一列 `workbench_brief`。`request["parts"]` 是唯一權威來源（ARCHITECTURE.md
    §5.4）：非空列表，`_PART_NAMES` 的子集，缺欄／空／不是 list／有未知名稱一律
    `ValueError("parts_unknown")`。`kind` 在這裡衍生（多於一個 part -> `"ad_creative"`，
    否則就是那個唯一的 part 名），只為顯示而寫進欄位，`create_brief`／`run_part` 都不
    再靠它做決定。`parts` 永遠非空，所以 status 永遠是 `"queued"`。

    F02-I02：私有——「a set only exists inside a pack」(ARCHITECTURE.md §5.4)，呼叫端
    (`create_brief()`／`submit_pack()`) 一定要帶 `pack_id`。`name`／`required_outputs`
    是任務包重置新加的兩欄（`workbench_brief.name`／`required_outputs_json`），沒帶就落成
    `None`／`{}`——`create_brief()` 走舊的單一 part 路徑，這兩欄本來就沒有意義。

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
    parts = request.get("parts")
    if not isinstance(parts, list) or not parts or any(p not in _PART_NAMES for p in parts):
        raise ValueError("parts_unknown")
    copy_length = request.get("copy_length", "short")
    if copy_length not in _COPY_LENGTHS:
        raise ValueError("copy_length_unknown")
    image_prompt_count = request.get("image_prompt_count")
    if "image_prompt" in parts and not (
        isinstance(image_prompt_count, int) and 1 <= image_prompt_count <= 30
    ):
        # 票 03 §2：範圍檢查在送出當下就做，不留到 worker 才發現。
        raise ValueError("count_out_of_range")
    video_script_count = request.get("video_script_count")
    if "video_script" in parts and not (
        isinstance(video_script_count, int) and 1 <= video_script_count <= 5
    ):
        # 票 workbench/06：跟上面 image_prompt_count 同一條規則，鏡它的範圍檢查。
        raise ValueError("count_out_of_range")
    brief_id = new_id("wbb")
    kind = "ad_creative" if len(parts) > 1 else parts[0]
    status = "queued"

    conn.execute(
        "INSERT INTO workbench_brief (id, org_id, brand_id, kind, source_kind, source_ref,"
        " product_id, coordinates_snapshot_json, visual_tone, visual_concept, style_key,"
        " request_json, status, pack_id, name, required_outputs_json)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            brief_id, org_id, brand_id, kind, brief["source_kind"],
            jsonb(brief.get("source_ref") or {}), product_id,
            jsonb(coordinates), brief.get("visual_tone"),
            brief.get("visual_concept"), style_key, jsonb(request), status,
            pack_id, name, jsonb(required_outputs or {}),
        ),
    )
    for part in parts:
        if part == "image_prompt":
            count = request.get("image_prompt_count")
        elif part == "video_script":
            count = request.get("video_script_count")
        else:
            count = None
        background_enqueue(
            "background.workbench_generate", org_id=org_id,
            lock=f"workbench:{brief_id}:{part}",
            brand_id=brand_id, brief_id=brief_id, part=part, count=count,
        )
    conn.commit()
    return brief_id


_REQUIRED_PART_NAMES = frozenset({"copy", "image_prompt", "video_script"})


def create_pack(conn, org_id: str, brand_id: str, pack: dict) -> str:
    """寫一列 `workbench_pack`，不驗證 `sets`（那是 `submit_pack()` 的事）——單純的列
    寫入，讓 `create_brief()`（舊的單一素材組入口）跟 `submit_pack()` 共用同一支寫法。"""
    pack_id = new_id("wbp")
    conn.execute(
        "INSERT INTO workbench_pack (id, org_id, brand_id, name, source_kind, source_ref,"
        " summary_json, context_json, constraints_json)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            pack_id, org_id, brand_id, pack.get("name") or "",
            pack["source_kind"], jsonb(pack.get("source_ref") or {}),
            jsonb(pack.get("summary") or {}), jsonb(pack.get("context") or {}),
            jsonb(pack.get("constraints") or {}),
        ),
    )
    conn.commit()
    return pack_id


def submit_pack(conn, org_id: str, brand_id: str, pack: dict) -> str:
    """ARCHITECTURE.md §5.4：上游一次交棒一整個任務包——`pack["sets"]` 每一項是一份
    `workbench_brief`（素材組）；`required_outputs`（那個 part 要選定幾版才算完成）跟
    `request` 裡的產出數量是兩件事，這裡不混：`request["parts"]` 由
    `required_outputs.keys()` 衍生，不是呼叫端自己列。全部 set 先驗證完才落筆——
    任何一個 set 不合格，這支不寫任何一列：`sets_unknown`（空／不是 list）、
    `required_outputs_unknown`（缺欄／空／不是 dict）、`part_retired`（`free` 出現在
    `required_outputs`——`free` 是舊 part，新 pack 一律不收，見 repository.py 檔頭與
    `app/departments/workbench/free.md`）、`parts_unknown`（不是 copy／image_prompt／
    video_script）、`count_out_of_range`（非 ≥1 整數）。"""
    sets = pack.get("sets")
    if not isinstance(sets, list) or not sets:
        raise ValueError("sets_unknown")
    for s in sets:
        if not isinstance(s, dict):
            raise ValueError("sets_unknown")
        required_outputs = s.get("required_outputs")
        if not isinstance(required_outputs, dict) or not required_outputs:
            raise ValueError("required_outputs_unknown")
        for part, count in required_outputs.items():
            if part == "free":
                raise ValueError("part_retired")
            if part not in _REQUIRED_PART_NAMES:
                raise ValueError("parts_unknown")
            if not isinstance(count, int) or count < 1:
                raise ValueError("count_out_of_range")

    # F02-I03 fix：`workbench_brief.source_kind` 跟 `workbench_pack.source_kind` 是兩套不同
    # 的 CHECK 詞彙（brief 只收 `schedule_node`／`manual`，pack 只收 `schedule_node`／
    # `free_job`）——直接把 pack 的值原樣塞給 brief 在 `source_kind="free_job"` 時會炸
    # `workbench_brief_source_kind_check`（自由創作的 pack 之前沒有測試路徑走到這裡）。
    # `free_job` pack 底下的 set 沒有樹可言，對 brief 這一層就是 `manual`。
    brief_source_kind = "schedule_node" if pack["source_kind"] == "schedule_node" else "manual"
    pack_id = create_pack(conn, org_id, brand_id, pack)
    for s in sets:
        required_outputs = s["required_outputs"]
        request = dict(s.get("request") or {})
        request["parts"] = list(required_outputs.keys())
        brief = {
            "source_kind": brief_source_kind, "source_ref": s.get("source_ref") or {},
            "product_id": s.get("product_id"), "coordinates": s.get("coordinates") or {},
            "visual_tone": s.get("visual_tone"), "visual_concept": s.get("visual_concept"),
            "style_key": s.get("style_key") or "ugc", "request": request,
        }
        submit_brief(
            conn, org_id, brand_id, brief, pack_id=pack_id, name=s.get("name"),
            required_outputs=required_outputs,
        )
    return pack_id


def create_brief(conn, org_id: str, brand_id: str, brief: dict) -> str:
    """`POST /briefs`（票 03）專屬入口：`kind` 不再由呼叫端決定什麼可以建立——`kind`
    是 `submit_brief()` 從 `request["parts"]` 衍生的顯示欄位，這裡不檢查、也不理會
    `brief` 裡任何 `kind` 值。其餘驗證（style_key／product_id／parts／copy_length／
    image_prompt_count／video_script_count）都在 `submit_brief()` 裡，這裡不重複。

    F02-I02：一份 brief 現在一定屬於一個 pack（「a set only exists inside a pack」，
    ARCHITECTURE.md §5.4）——這裡先開一個只裝這一組的任務包，讓這條舊路徑（含 `free`，
    `submit_pack()` 不收的那個 legacy part）繼續運作，`required_outputs` 就是
    `request["parts"]` 各自需要選定 1 版（沒有更細的『幾版才算完成』設定，跟
    `submit_pack()` 的嚴格檢查不是同一條路）。`workbench_pack.source_kind` 只收
    `schedule_node`／`free_job` 兩個值（migration CHECK），這條舊路徑的 `manual`
    briefs 落在 `free_job`（沒有上游樹，概念上最接近自由創作）。"""
    request = brief.get("request") or {}
    parts = request.get("parts")
    required_outputs = {p: 1 for p in parts} if isinstance(parts, list) else {}
    pack_source_kind = (
        "schedule_node" if brief.get("source_kind") == "schedule_node" else "free_job"
    )
    pack_id = create_pack(conn, org_id, brand_id, {
        "source_kind": pack_source_kind, "source_ref": brief.get("source_ref") or {},
        "name": "工作檯工單",
    })
    return submit_brief(
        conn, org_id, brand_id, brief, pack_id=pack_id, required_outputs=required_outputs,
    )


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


def update_brief_visual(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str,
                         visual_tone: str | None, visual_concept: str | None) -> None:
    """票 05（ADR 0068 §5 amendment）：文案任務跟著回 `visual_tone`／`visual_concept`——
    寫角度的人順手命名畫面。一份有效回覆寫回這兩欄，讓之後重新產出的 `prompts.brief_text()`
    看得到延續語氣的既有視覺方向（跟既有座標欄同一套「工單記得上一輪」慣例）。"""
    conn.execute(
        "UPDATE workbench_brief SET visual_tone = %s, visual_concept = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (visual_tone, visual_concept, org_id, brand_id, brief_id),
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
                  generation_round: int, body_json: dict | list, coordinates_json: dict | None,
                  llm_task_id: str | None):
    """F02-I02（ARCHITECTURE.md §5.2）：version-aware——`body_json` 是一個 dict 就寫一列
    （`version_index=1`，跟舊呼叫端相容：`app/tests/test_workbench_api.py`／
    `test_schedule.py` 的既有直接呼叫都還是單一 dict），是一個 list 就一項一列，
    `version_index` 按清單順序 1..n（`jobs.py` 這裡傳一輪的每一版：copy 一輪 5 版、
    image_prompt 一輪 1 版、video_script 一輪一支腳本一版）。回傳型別跟著輸入：單一
    dict 進來回單一 dict，list 進來回 list（依 `version_index` 排序）。"""
    single = isinstance(body_json, dict)
    bodies = [body_json] if single else list(body_json)
    output_ids = []
    for version_index, body in enumerate(bodies, start=1):
        output_id = new_id("wbo")
        conn.execute(
            "INSERT INTO workbench_output (id, org_id, brand_id, brief_id, part,"
            " generation_round, version_index, body_json, coordinates_json, llm_task_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                output_id, org_id, brand_id, brief_id, part, generation_round, version_index,
                jsonb(body), jsonb(coordinates_json) if coordinates_json is not None else None,
                llm_task_id,
            ),
        )
        output_ids.append(output_id)
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s"
        " AND id = ANY(%s) ORDER BY version_index",
        (org_id, brand_id, output_ids),
    ).fetchall()
    assert len(rows) == len(output_ids)  # 剛寫進去的那幾列，找不到代表資料庫壞了
    result = [dict(r) for r in rows]
    return result[0] if single else result


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


def _output_with_brief(conn: _AnyConn, org_id: str, brand_id: str, output_id: str) -> dict:
    """`select_version`／`deselect_version` 共用的守門讀取：output 找不到
    `ValueError("output_unknown")`；brief 已關閉 `ValueError("brief_closed")`；brief 所屬的
    pack 已核准 `ValueError("pack_approved")`（ARCHITECTURE.md §5.5：核准後鎖住選定）。"""
    row = conn.execute(
        "SELECT o.*, b.closed_at AS brief_closed_at, b.pack_id AS brief_pack_id"
        " FROM workbench_output o JOIN workbench_brief b ON b.id = o.brief_id"
        " WHERE o.org_id = %s AND o.brand_id = %s AND o.id = %s",
        (org_id, brand_id, output_id),
    ).fetchone()
    if row is None:
        raise ValueError("output_unknown")
    output = dict(row)
    if output["brief_closed_at"] is not None:
        raise ValueError("brief_closed")
    pack_id = output["brief_pack_id"]
    if pack_id is not None:
        pack = conn.execute(
            "SELECT approved_at FROM workbench_pack WHERE org_id = %s AND brand_id = %s"
            " AND id = %s", (org_id, brand_id, pack_id),
        ).fetchone()
        if pack is not None and pack["approved_at"] is not None:
            raise ValueError("pack_approved")
    return output


def select_version(conn: _AnyConn, org_id: str, brand_id: str, output_id: str) -> dict:
    """`POST .../versions/{v}/select`（F02-I03）：那一版標成已選定。`ValueError`：
    `output_unknown`／`brief_closed`／`pack_approved`（§5.5：核准整包之後鎖住選定）。"""
    _output_with_brief(conn, org_id, brand_id, output_id)
    result = adopt_output(conn, org_id, brand_id, output_id)
    assert result is not None
    return result


def deselect_version(conn: _AnyConn, org_id: str, brand_id: str, output_id: str) -> dict:
    """`DELETE .../versions/{v}/select`（F02-I03）：清那一版的已選定。同
    `select_version()` 的守門，見那支檔頭。"""
    _output_with_brief(conn, org_id, brand_id, output_id)
    conn.execute(
        "UPDATE workbench_output SET adopted_at = NULL"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, output_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, output_id),
    ).fetchone()
    assert row is not None
    return dict(row)


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
    """契約頁 Exported shapes：那個 part **最早被選定**的一列（`adopted_at` 最早），否則
    最新一輪最新一版，否則 `None`；回傳值是那一列本身外加 `is_adopted`。F02-I02（多選
    版本，ARCHITECTURE.md §5.4「Multi-select 不改 `adopted_output` 的意義跟形狀」）：一輪
    現在可能有不只一列（`version_index`），選定不再保證整輪只有一列被標記——這裡的
    「最早」讀 `adopted_at` 時間戳本身，不是 `generation_round`，這樣不管哪一輪被選、
    選了幾版，排程模組讀到的永遠是同一列（先選的那個），跟舊版單列時期的行為相容。"""
    row = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
        " AND part = %s AND adopted_at IS NOT NULL ORDER BY adopted_at ASC LIMIT 1",
        (org_id, brand_id, brief_id, part),
    ).fetchone()
    is_adopted = row is not None
    if row is None:
        row = conn.execute(
            "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s"
            " AND brief_id = %s AND part = %s"
            " ORDER BY generation_round DESC, version_index DESC LIMIT 1",
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
# 狀態衍生 —— ARCHITECTURE.md §5.3：product／set／pack 的狀態一律衍生，不另存第二份。
# 只有這裡算一次，F02-I03 的 API／F02-I04 的排程讀都呼叫這裡，不各自重寫規則。
# ---------------------------------------------------------------------------


def _versions_by_part(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str) -> dict:
    """那份 brief 目前每一列版本，依 part 分組——只帶 `product_state`／`set_table_cell`
    要用的欄位（有沒有被選定），不是完整的 output 列。"""
    rows = conn.execute(
        "SELECT part, adopted_at FROM workbench_output"
        " WHERE org_id = %s AND brand_id = %s AND brief_id = %s",
        (org_id, brand_id, brief_id),
    ).fetchall()
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row["part"], []).append(bool(row["adopted_at"]))
    return grouped


def product_state(required: int, adopted_flags: list) -> str:
    """ARCHITECTURE.md §5.3：`未生成`（沒有版本）／`待選定`（有版本，選定數 < 需要）／
    `已選定`（選定數 ≥ 需要）。`adopted_flags`：那個 part 每一列版本是否已選定的清單。"""
    if not adopted_flags:
        return "未生成"
    selected = sum(1 for a in adopted_flags if a)
    return "已選定" if selected >= required else "待選定"


def set_table_cell(required_outputs: dict, versions_by_part: dict, part: str) -> dict:
    """ARCHITECTURE.md §5.3：任務包頁「素材組進度」表格的一格——`{"state", "text"}`，
    `text` 就是畫面直接渲染的字串（沒有第二份拼字規則）：這個 set 不需要這個 part -> `「—」`；
    需要但沒有版本 -> `未生成`；否則 `已選定／需要`（例：`2／5`）。"""
    if part not in required_outputs:
        return {"state": "not_required", "text": "—"}
    required = required_outputs[part]
    adopted_flags = versions_by_part.get(part) or []
    state = product_state(required, adopted_flags)
    if state == "未生成":
        return {"state": state, "text": "未生成"}
    selected = sum(1 for a in adopted_flags if a)
    return {"state": state, "text": f"{selected}／{required}"}


def set_state(required_outputs: dict, versions_by_part: dict) -> str:
    """ARCHITECTURE.md §5.3：`待開始`（沒有一個 product 有版本）／`等待決定`（部分產出中）／
    `已完成`（每個 required product 都已選定）。"""
    states = [
        product_state(required_outputs[part], versions_by_part.get(part) or [])
        for part in required_outputs
    ]
    if states and all(s == "已選定" for s in states):
        return "已完成"
    if any(s != "未生成" for s in states):
        return "等待決定"
    return "待開始"


def pack_state(approved_at, set_states: list) -> str:
    """ARCHITECTURE.md §5.3：`待處理`（沒有一個 set 開始）／`進行中`／`待核准`（每個 set 都
    已完成，還沒核准）／`已完成`（已核准）。"""
    if approved_at is not None:
        return "已完成"
    if set_states and all(s == "已完成" for s in set_states):
        return "待核准"
    if any(s != "待開始" for s in set_states):
        return "進行中"
    return "待處理"


def pack_for_source(conn: _AnyConn, org_id: str, brand_id: str, source_kind: str,
                     source_ref: dict) -> dict | None:
    """契約頁 Exported shapes（ARCHITECTURE.md §5.5）：上游讀「這個 pack 現在怎麼樣」的
    狀態查詢，不是 callback——`source_ref` 包含給定 dict 全部鍵（JSONB containment，
    `@>`）的最新一個 pack，附上 `sets_total`／`sets_done`／`state`；找不到回 `None`。"""
    row = conn.execute(
        "SELECT * FROM workbench_pack WHERE org_id = %s AND brand_id = %s"
        " AND source_kind = %s AND source_ref @> %s ORDER BY created_at DESC LIMIT 1",
        (org_id, brand_id, source_kind, jsonb(source_ref)),
    ).fetchone()
    if row is None:
        return None
    pack = dict(row)
    set_rows = conn.execute(
        "SELECT id, required_outputs_json FROM workbench_brief"
        " WHERE org_id = %s AND brand_id = %s AND pack_id = %s",
        (org_id, brand_id, pack["id"]),
    ).fetchall()
    set_states = [
        set_state(
            s["required_outputs_json"] or {},
            _versions_by_part(conn, org_id, brand_id, s["id"]),
        )
        for s in set_rows
    ]
    pack["sets_total"] = len(set_states)
    pack["sets_done"] = sum(1 for s in set_states if s == "已完成")
    pack["state"] = pack_state(pack["approved_at"], set_states)
    return pack


# ---------------------------------------------------------------------------
# F02-I03: routes.py 專用——`run_part` is the mutate-a-part primitive shared by the pack/set
# API's `run_product()` below (it adds the `pack_approved` lock on top). The brief-shaped
# list/detail/adopt/close/reopen/delete functions this section used to hold are retired with
# their endpoints (`.work/features/F02.md` Decisions: "replaced, not kept in parallel") — their
# only caller was the old `routes.py`, which no longer exists in this shape.
# ---------------------------------------------------------------------------


def run_part(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str, part: str, *,
             count: int | None = None) -> None:
    """`POST .../parts/{part}/run`（票 03 §2）：`submit_brief()` 排隊那一半的重跑版——
    這裡跟它共用同一個 lock 字串（`workbench:{brief_id}:{part}`）跟 `queued` 寫法，一個
    地方決定。任何一個 part 名（`_PART_NAMES`）都可以重跑，不再照 `kind` 篩——一張
    brief 可能產出它當初沒請求過的 part，那筆 output 就是紀錄本身。`ValueError`：
    `brief_unknown`／`part_unknown`／`brief_closed`／`round_running`／
    `count_out_of_range`（routes.py 逐一對照成 HTTP 狀態碼）。這裡不改
    `request_json.parts`——它記的是「當初請求了什麼」，不是「現在跑過什麼」。

    `round_running` 只看 brief 這一欄 `status`（不是「這個 part 有沒有活躍的鎖」）——
    一張 brief 只有一個 status 欄，這裡老實照它判斷；一個 job 卡在 running 沒有寫回
    failed（例如 process 被殺）會讓這張 brief 再也跑不了下一輪，是已知、未在這張票修的
    缺口（票面 contradiction check 第一條，日後才加逾時）。"""
    from app.background import enqueue as background_enqueue

    brief = get_brief(conn, org_id, brand_id, brief_id)
    if brief is None:
        raise ValueError("brief_unknown")
    if part not in _PART_NAMES:
        raise ValueError("part_unknown")
    if brief["closed_at"] is not None:
        raise ValueError("brief_closed")
    if brief["status"] in ("queued", "running"):
        raise ValueError("round_running")
    if part == "image_prompt":
        if count is None or not (1 <= count <= 30):
            raise ValueError("count_out_of_range")
    if part == "video_script":
        # 票 workbench/06 §3：跟 image_prompt 一樣，張數是使用者的、沒有預設值——
        # 「再產一輪」重跑一樣要帶（同一個表單欄位、同一條規則）。
        if count is None or not (1 <= count <= 5):
            raise ValueError("count_out_of_range")
    mark_brief_status(conn, org_id, brand_id, brief_id, "queued")
    background_enqueue(
        "background.workbench_generate", org_id=org_id,
        lock=f"workbench:{brief_id}:{part}",
        brand_id=brand_id, brief_id=brief_id, part=part, count=count,
    )


# ---------------------------------------------------------------------------
# F02-I03: the pack/set/product/version JSON surface (ARCHITECTURE.md §5.1-§5.5, `.work/
# features/F02.md` "API surface"/"Shapes"). Every field here is assembled from the state
# derivations above (`product_state`/`set_state`/`pack_state`/`set_table_cell`) — no second
# copy of any rule, `routes.py` just wraps whatever this returns.
# ---------------------------------------------------------------------------

_PART_LABELS = {"copy": "文案", "image_prompt": "圖片", "video_script": "腳本"}
_PART_ORDER = ("copy", "image_prompt", "video_script")
_STATE_TO_STATUS = {
    "待處理": "pending", "進行中": "running", "待核准": "awaiting_approval", "已完成": "done",
}
_LIST_STATUS_VALUES = frozenset({"all", "pending", "running", "awaiting_approval", "done"})
_LIST_SORT_VALUES = frozenset({"updated", "created", "progress"})
_COMPLETION_ITEMS = (
    ("required_outputs_met", "完成所有素材組的必要文案與圖片"),
    ("brand_rules_checked", "確認內容符合品牌規範"),
    ("ready_to_report", "可核准整包並回報上游"),
)
_COMPLETION_KEYS = frozenset(key for key, _label in _COMPLETION_ITEMS)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_pack_row(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM workbench_pack WHERE org_id = %s AND brand_id = %s AND id = %s",
        (org_id, brand_id, pack_id),
    ).fetchone()
    return dict(row) if row is not None else None


def _pack_sets_full(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str) -> list:
    """Every set of a pack with its `required_outputs`／`versions_by_part`／derived `state` —
    the one shared read `_pack_card_and_sets()`／`pack_detail()`／completion／approve all build
    on, so the set-state rule (§5.3) is computed once per call, not re-derived per screen."""
    rows = conn.execute(
        "SELECT id, name, required_outputs_json FROM workbench_brief"
        " WHERE org_id = %s AND brand_id = %s AND pack_id = %s ORDER BY created_at",
        (org_id, brand_id, pack_id),
    ).fetchall()
    sets = []
    for row in rows:
        row = dict(row)
        required_outputs = row["required_outputs_json"] or {}
        versions_by_part = _versions_by_part(conn, org_id, brand_id, row["id"])
        sets.append({
            "id": row["id"], "name": row["name"], "required_outputs": required_outputs,
            "versions_by_part": versions_by_part,
            "state": set_state(required_outputs, versions_by_part),
        })
    return sets


def _pack_counts(sets: list) -> list:
    counts = []
    for part in _PART_ORDER:
        relevant = [s for s in sets if part in s["required_outputs"]]
        if not relevant:
            continue
        selected = sum(
            1 for s in relevant if product_state(
                s["required_outputs"][part], s["versions_by_part"].get(part) or [],
            ) == "已選定"
        )
        counts.append({
            "part": part, "label": _PART_LABELS[part], "selected": selected,
            "required": len(relevant),
        })
    return counts


def _pack_next_step(sets: list) -> dict | None:
    for s in sets:
        if s["state"] == "已完成":
            continue
        for part in _PART_ORDER:
            if part not in s["required_outputs"]:
                continue
            adopted_flags = s["versions_by_part"].get(part) or []
            state = product_state(s["required_outputs"][part], adopted_flags)
            if state == "已選定":
                continue
            suffix = "待生成" if state == "未生成" else "待選定"
            return {
                "set_id": s["id"], "set_name": s["name"], "part": part,
                "label": f"{_PART_LABELS[part]}{suffix}",
            }
    return None


def _pack_card_and_sets(conn: _AnyConn, org_id: str, brand_id: str, pack_row: dict) -> tuple:
    sets = _pack_sets_full(conn, org_id, brand_id, pack_row["id"])
    set_states = [s["state"] for s in sets]
    state = pack_state(pack_row["approved_at"], set_states)
    sets_total = len(sets)
    sets_done = sum(1 for s in set_states if s == "已完成")
    pct = round(sets_done / sets_total * 100) if sets_total else 0
    summary = pack_row["summary_json"] or {}
    card = {
        "id": pack_row["id"], "name": pack_row["name"],
        "subtitle": summary.get("情境") or "",
        "source_kind": pack_row["source_kind"],
        "source_label": "廣告排程" if pack_row["source_kind"] == "schedule_node" else "自由創作",
        "status": _STATE_TO_STATUS[state],
        "sets_total": sets_total, "sets_done": sets_done, "progress_pct": pct,
        "next_step": _pack_next_step(sets), "counts": _pack_counts(sets),
        "updated_at": pack_row["updated_at"],
    }
    return card, sets


def list_packs(conn: _AnyConn, org_id: str, brand_id: str, *, status: str = "all",
                q: str | None = None, sort: str = "updated") -> list:
    """`GET /packs?status=&q=&sort=`. `ValueError("status_unknown"/"sort_unknown")` for
    anything outside the enums. Filtering/sorting happen in Python, not SQL — a brand's pack
    count is small (one workbench, one screen) and every field is a derivation, not a column
    (ponytail: revisit with a SQL WHERE/ORDER BY if a brand ever has hundreds of packs)."""
    if status not in _LIST_STATUS_VALUES:
        raise ValueError("status_unknown")
    if sort not in _LIST_SORT_VALUES:
        raise ValueError("sort_unknown")
    rows = conn.execute(
        "SELECT * FROM workbench_pack WHERE org_id = %s AND brand_id = %s",
        (org_id, brand_id),
    ).fetchall()
    entries = []
    for row in rows:
        row = dict(row)
        card, sets = _pack_card_and_sets(conn, org_id, brand_id, row)
        if status != "all" and card["status"] != status:
            continue
        if q:
            q_lower = q.lower()
            haystack = [card["name"], *(s["name"] for s in sets)]
            haystack += [str(v) for v in (row["summary_json"] or {}).values() if v]
            if not any(q_lower in h.lower() for h in haystack if h):
                continue
        entries.append((row, card))
    if sort == "created":
        entries.sort(key=lambda e: e[0]["created_at"], reverse=True)
    elif sort == "progress":
        entries.sort(key=lambda e: e[1]["progress_pct"], reverse=True)
    else:
        entries.sort(key=lambda e: e[0]["updated_at"], reverse=True)
    return [card for _row, card in entries]


def _pack_completion(pack_row: dict, sets_done: int, sets_total: int) -> tuple:
    stored = pack_row["completion_json"] or {}
    computed_ok = sets_total > 0 and sets_done == sets_total
    items = []
    for key, label in _COMPLETION_ITEMS:
        entry = stored.get(key) or {}
        checked = bool(entry.get("checked"))
        if key == "required_outputs_met":
            ok = computed_ok or checked
            overridden = checked and not computed_ok
        else:
            ok = checked
            overridden = False
        items.append({"key": key, "label": label, "ok": ok, "overridden": overridden})
    can_approve = all(item["ok"] for item in items)
    missing = sets_total - sets_done
    blocking_text = f"尚有 {missing} 個素材組未完成" if missing > 0 else ""
    return items, can_approve, blocking_text


def pack_detail(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str) -> dict | None:
    """`GET /packs/{p}`. `.work/features/F02.md` "Shapes": 摘要 only renders the keys 檔期規劃
    actually fills（情境／重點訊息 today）— empty keys are omitted, never placeholder text."""
    row = _get_pack_row(conn, org_id, brand_id, pack_id)
    if row is None:
        return None
    card, sets = _pack_card_and_sets(conn, org_id, brand_id, row)
    context = row["context_json"] or {}
    summary_raw = row["summary_json"] or {}
    completion, can_approve, blocking_text = _pack_completion(
        row, card["sets_done"], card["sets_total"],
    )
    detail = dict(card)
    detail["created_at"] = row["created_at"]
    detail["source_ref"] = row["source_ref"]
    detail["meta"] = {
        "platform": context.get("platform"), "goal": context.get("goal"),
        "sets_required": card["sets_total"],
    }
    summary_map = {
        "situation": summary_raw.get("情境"), "angle": summary_raw.get("角度"),
        "style": summary_raw.get("風格"), "audience": summary_raw.get("目標受眾"),
        "key_messages": summary_raw.get("重點訊息"), "reference_link": summary_raw.get("參考連結"),
    }
    detail["summary"] = {k: v for k, v in summary_map.items() if v}
    detail["completion"] = completion
    detail["can_approve"] = can_approve
    detail["blocking_text"] = blocking_text
    detail["sets"] = [
        {
            "id": s["id"], "name": s["name"], "status": s["state"],
            "cells": [_cell(s["required_outputs"], s["versions_by_part"], part)
                      for part in _PART_ORDER],
        }
        for s in sets
    ]
    return detail


def _cell(required_outputs: dict, versions_by_part: dict, part: str) -> dict:
    base = set_table_cell(required_outputs, versions_by_part, part)
    adopted_flags = versions_by_part.get(part) or []
    return {
        "part": part, "label": _PART_LABELS[part], "state": base["state"],
        "selected": sum(1 for a in adopted_flags if a),
        "required": required_outputs.get(part), "text": base["text"],
    }


def set_pack_completion(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str, key: str,
                         checked: bool) -> dict:
    """`POST /packs/{p}/completion`. `ValueError`：`key_unknown`（400）／`pack_unknown`
    （404）。Ticking `required_outputs_met` while it is computed-false records an override —
    the warning that produces is the frontend's job (F02-I08), this just remembers the fact."""
    if key not in _COMPLETION_KEYS:
        raise ValueError("key_unknown")
    row = _get_pack_row(conn, org_id, brand_id, pack_id)
    if row is None:
        raise ValueError("pack_unknown")
    completion = dict(row["completion_json"] or {})
    entry: dict = {"checked": bool(checked), "at": _now_iso()}
    if key == "required_outputs_met" and checked:
        sets = _pack_sets_full(conn, org_id, brand_id, pack_id)
        computed_ok = bool(sets) and all(s["state"] == "已完成" for s in sets)
        if not computed_ok:
            entry["overridden"] = True
    completion[key] = entry
    conn.execute(
        "UPDATE workbench_pack SET completion_json = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb(completion), org_id, brand_id, pack_id),
    )
    conn.commit()
    detail = pack_detail(conn, org_id, brand_id, pack_id)
    assert detail is not None
    return detail


def approve_pack(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str) -> dict:
    """`POST /packs/{p}/approve`. `ValueError`：`pack_unknown`（404）／`completion_incomplete`
    （409，「還有完成條件沒有滿足。」）. Approving twice is idempotent — no un-approve
    (§5.5, nobody has asked for one)."""
    row = _get_pack_row(conn, org_id, brand_id, pack_id)
    if row is None:
        raise ValueError("pack_unknown")
    if row["approved_at"] is None:
        detail = pack_detail(conn, org_id, brand_id, pack_id)
        assert detail is not None
        if not detail["can_approve"]:
            raise ValueError("completion_incomplete")
        conn.execute(
            "UPDATE workbench_pack SET approved_at = now(), updated_at = now()"
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            (org_id, brand_id, pack_id),
        )
        conn.commit()
    detail = pack_detail(conn, org_id, brand_id, pack_id)
    assert detail is not None
    return detail


def close_pack(conn: _AnyConn, org_id: str, brand_id: str, pack_id: str) -> dict:
    """`POST /packs/{p}/close`（⋯ 選單的「關閉任務包」）. `ValueError("pack_unknown")`."""
    row = conn.execute(
        "UPDATE workbench_pack SET closed_at = now(), updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s RETURNING id",
        (org_id, brand_id, pack_id),
    ).fetchone()
    conn.commit()
    if row is None:
        raise ValueError("pack_unknown")
    detail = pack_detail(conn, org_id, brand_id, pack_id)
    assert detail is not None
    return detail


def _next_free_pack_name(conn: _AnyConn, org_id: str, brand_id: str) -> str:
    row = conn.execute(
        "SELECT count(*) AS n FROM workbench_pack WHERE org_id = %s AND brand_id = %s"
        " AND source_kind = 'free_job'",
        (org_id, brand_id),
    ).fetchone()
    return f"自由工作 #{(row['n'] if row is not None else 0) + 1}"


def create_free_pack(conn: _AnyConn, org_id: str, brand_id: str, body: dict) -> str:
    """`POST /packs`（自由創作 only）— goes through `submit_pack()`, no second write path
    (`.work/features/F02.md` "自由創作's 「AI 解析結果」..."). `source_kind` is forced to
    `"free_job"` here; a client may not pick it. Per-part generation counts default to the
    same number as `required_outputs[type]` (user ruling 2026-09-12: 「五張」 asks for 5
    required *and* one round of 5) unless the set's own `request` already names a count."""
    sets_in = body.get("sets")
    if not isinstance(sets_in, list) or not sets_in:
        raise ValueError("sets_unknown")
    name = body.get("name") or _next_free_pack_name(conn, org_id, brand_id)
    pack_sets = []
    for s in sets_in:
        if not isinstance(s, dict):
            raise ValueError("sets_unknown")
        required_outputs = s.get("required_outputs") or {}
        request = dict(s.get("request") or {})
        if "image_prompt" in required_outputs:
            request.setdefault("image_prompt_count", required_outputs["image_prompt"])
        if "video_script" in required_outputs:
            request.setdefault("video_script_count", required_outputs["video_script"])
        pack_sets.append({
            "name": s.get("name"), "source_ref": s.get("source_ref") or {},
            "coordinates": s.get("coordinates") or {},
            "product_id": s.get("product_id", body.get("product_id")),
            "style_key": s.get("style_key") or body.get("style_key") or "ugc",
            "required_outputs": required_outputs, "request": request,
        })
    pack = {
        "source_kind": "free_job", "source_ref": {"free_text": body.get("free_text")},
        "name": name, "summary": body.get("summary") or {}, "sets": pack_sets,
    }
    return submit_pack(conn, org_id, brand_id, pack)


def run_product(conn: _AnyConn, org_id: str, brand_id: str, set_id: str, part: str, *,
                 count: int | None = None) -> dict:
    """`POST /sets/{s}/products/{part}/run`. Reuses `run_part()`'s errors and adds
    `pack_approved`（409，「這個任務包已核准，選定已鎖定。」）on top — §5.5 locks selections
    once a pack is approved."""
    brief = get_brief(conn, org_id, brand_id, set_id)
    if brief is not None and brief["pack_id"] is not None:
        pack_row = _get_pack_row(conn, org_id, brand_id, brief["pack_id"])
        if pack_row is not None and pack_row["approved_at"] is not None:
            raise ValueError("pack_approved")
    run_part(conn, org_id, brand_id, set_id, part, count=count)
    detail = set_detail(conn, org_id, brand_id, set_id)
    assert detail is not None
    return detail


def _slice_body(part: str, body_json, version_index: int):
    """A copy round's `body_json` is the whole round's reply shared by all 5 rows (`sets`
    array); a video_script round shares `scripts` the same way (`.work/features/F02.md`
    "Shapes"). This slices out version *i*'s own piece, once, here — the browser never
    indexes into a round. Out-of-range/missing -> `None`, not a crash."""
    if not isinstance(body_json, dict):
        return None
    if part == "copy":
        items = body_json.get("sets") or []
        idx = version_index - 1
        if not (0 <= idx < len(items)) or not isinstance(items[idx], dict):
            return None
        item = items[idx]
        return {
            "body": item.get("body"), "headline": item.get("headline"),
            "description": item.get("description"),
            "validation": body_json.get("validation"), "warnings": body_json.get("warnings"),
        }
    if part == "video_script":
        items = body_json.get("scripts") or []
        idx = version_index - 1
        if not (0 <= idx < len(items)):
            return None
        item = items[idx]
        result = dict(item) if isinstance(item, dict) else {"script": item}
        result["validation"] = body_json.get("validation")
        return result
    return body_json


def _part_versions(conn: _AnyConn, org_id: str, brand_id: str, brief_id: str, part: str) -> list:
    rows = conn.execute(
        "SELECT * FROM workbench_output WHERE org_id = %s AND brand_id = %s AND brief_id = %s"
        " AND part = %s ORDER BY generation_round DESC, version_index ASC",
        (org_id, brand_id, brief_id, part),
    ).fetchall()
    return [
        {
            "id": r["id"], "version_index": r["version_index"],
            "generation_round": r["generation_round"], "selected_at": r["adopted_at"],
            "body": _slice_body(part, r["body_json"], r["version_index"]),
        }
        for r in (dict(row) for row in rows)
    ]


def _generation_settings(part: str, request_json: dict | None) -> dict:
    request_json = request_json or {}
    if part == "copy":
        return {"copy_length": request_json.get("copy_length", "short")}
    if part == "image_prompt":
        return {"count": request_json.get("image_prompt_count")}
    if part == "video_script":
        return {"count": request_json.get("video_script_count")}
    return {}


def set_detail(conn: _AnyConn, org_id: str, brand_id: str, set_id: str) -> dict | None:
    """`GET /sets/{s}`. `image_generation.connected` is hard `False` here — the port is
    reserved, not filled (§5.11); `image_generation.reason` carries the shipped-text reserved-
    seat line so the browser never re-spells it."""
    brief = get_brief(conn, org_id, brand_id, set_id)
    if brief is None or brief["pack_id"] is None:
        return None
    pack_row = _get_pack_row(conn, org_id, brand_id, brief["pack_id"])
    if pack_row is None:
        return None
    required_outputs = brief["required_outputs_json"] or {}
    versions_by_part = _versions_by_part(conn, org_id, brand_id, set_id)
    coordinates = brief["coordinates_snapshot_json"] or {}
    try:
        style = get_style(brief["style_key"])
    except ValueError:
        style = None
    sibling_rows = conn.execute(
        "SELECT id, name, coordinates_snapshot_json, required_outputs_json"
        " FROM workbench_brief WHERE org_id = %s AND brand_id = %s AND pack_id = %s"
        " ORDER BY created_at",
        (org_id, brand_id, brief["pack_id"]),
    ).fetchall()
    siblings = []
    for r in sibling_rows:
        r = dict(r)
        sib_versions = _versions_by_part(conn, org_id, brand_id, r["id"])
        siblings.append({
            "id": r["id"], "name": r["name"],
            "angle": (r["coordinates_snapshot_json"] or {}).get("angle"),
            "status": set_state(r["required_outputs_json"] or {}, sib_versions),
        })
    required_parts = [part for part in _PART_ORDER if part in required_outputs]
    products = {
        part: {
            "state": product_state(required_outputs[part], versions_by_part.get(part) or []),
            "selected": sum(1 for a in (versions_by_part.get(part) or []) if a),
            "required": required_outputs[part],
            "generation_settings": _generation_settings(part, brief["request_json"]),
            "versions": _part_versions(conn, org_id, brand_id, set_id, part),
        }
        for part in required_parts
    }
    return {
        "id": brief["id"], "pack_id": pack_row["id"], "pack_name": pack_row["name"],
        "name": brief["name"], "status": set_state(required_outputs, versions_by_part),
        "chips": {
            "platform": pack_row["context_json"].get("platform")
            if pack_row["context_json"] else None,
            "style": style["label"] if style else brief["style_key"],
            "size": coordinates.get("format"),
        },
        "siblings": siblings, "required_parts": required_parts, "products": products,
        "image_generation": {
            "connected": False,
            "reason": "圖片生成服務未接上，這裡先保留席位；接上後同一個畫面直接顯示成果。",
        },
    }


_CHILD_TABLES = (
    ("workbench_output", "工作檯產出"),
    ("workbench_brief", "工作檯工單"),
    ("workbench_pack", "工作檯任務包"),
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
    brand_tables=frozenset({"workbench_brief", "workbench_output", "workbench_pack"}),
    count_product=None,
    delete_product=None,
    product_tables=frozenset(),
)
