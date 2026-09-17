"""app/workbench/__init__.py — single entry point (container contract §1, ticket
workbench/02/03, ADR 0068).

Shapes other modules may use:
    register(app: FastAPI) -> None       # mounts /api/workbench/* (routes.py, ticket 03)
    register_tasks() -> None             # idempotently registers `background.workbench_generate`
                                          # against the current app.background.app()
    submit_pack(conn, org_id, brand_id, pack: dict) -> str
    pack_for_source(conn, org_id, brand_id, source_kind: str, source_ref: dict) -> dict | None
    briefs_for_source(conn, org_id, brand_id, source_kind: str, source_ref: dict) -> list[dict]
    adopted_output(conn, org_id, brand_id, brief_id: str, part: str) -> dict | None

Everything else in this package (`repository.py`, `jobs.py`, `prompts.py`, `validate.py`,
`routes.py`) is private — nothing outside this package imports them. F02-I02 (ARCHITECTURE.md
§5.1-§5.4, 2026-09-12 reset): `submit_brief` is **not** a public entry any more — a 素材組 only
exists inside a 任務包 (`workbench_pack`), so the one way in for an upstream is
`submit_pack(conn, org_id, brand_id, pack)`, one call, one or more `sets` (ARCHITECTURE.md §5.4
names the pack/set shape). `pack_for_source` is the read the upstream uses to learn "is this
pack approved yet" — a state read, never a callback (ARCHITECTURE.md §5.5), same JSONB
containment match as `briefs_for_source`.
Callers: `app/main.py`'s register loop (first two, called once right after the loop, same spot
as `schedule_module.register_tasks()`) and `app/tests` (which call `register_tasks()` again
after they get their own test module's fresh `background.app()` — same reason `app/schedule/
jobs.py`'s `register_tasks()` docstring already documents). `app.schedule.jobs` is the first
caller of `submit_pack` (once per expanded tree, one set per deepest node) and `app.schedule.
state`/`app.schedule.performance` of `briefs_for_source`/`adopted_output`; `app.schedule.state`
(and 檔期規劃's approval button, once that lands) becomes a caller of `pack_for_source` (ADR
0068 rule 2: dependency is one-way, schedule imports workbench, never the reverse).

Depends on `app.core`, `app.background`, `app.llm`, `app.shared.web`, `app.identity`,
`app.brand_intelligence.repository` (read-only) — docs/contracts/workbench.md "Allowed
dependencies". Does not import or touch `app.schedule`, `app.main`, `app.meta`,
`app.dashboard`, or another module's tables directly: a `source_ref` is stored and compared,
never interpreted (contract "Must not import or touch"). `repository.list_coordinate_vocabulary`
reads `app.schedule`'s `brand_coordinate`/`feedback` tables by raw SQL, not by importing that
package — container contract rule 5 allows duplicating a query across modules.

`app.core.cleanup` registration (this ticket): `repository.py`'s module tail registers
「素材工作檯」, covering `workbench_brief`/`workbench_output`/`workbench_pack`; brand
dimension only — this
module has no product-layer data, so `count_product`/`delete_product` are explicitly `None`
and `product_tables` is an explicit empty `frozenset()` (see `app/core/cleanup.py`'s own
docstring for why "explicit None" and "omitted" are not the same thing here).
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/workbench/* 路由（機械式，比照 app/schedule/__init__.py 的延遲 import
    慣例）。票 03：router 搬進 routes.py 本身，這裡只負責掛。"""
    from app.workbench import routes as workbench_routes

    app.include_router(workbench_routes.router)


def register_tasks() -> None:
    """票 workbench/02：掛 `background.workbench_generate`，冪等。見 jobs.py。"""
    from app.workbench import jobs as workbench_jobs

    workbench_jobs.register_tasks()


def submit_pack(conn, org_id: str, brand_id: str, pack: dict) -> str:
    """寫一份任務包（一個 `workbench_pack` 列 + 每個 `pack["sets"]` 一份
    `workbench_brief`），回傳 pack id。ARCHITECTURE.md §5.4：`pack` 帶 `source`
    （`source_kind` ＋不解讀的 `source_ref`）、`name`、`context`、`summary`（摘要）、
    `sets`（每個：`name`／`source_ref`／`coordinates`／`product_id`／
    `required_outputs`＝`{產物類型: 需要選定的版本數}`／每種產出的生成參數放在
    `request`；`request.variant_count`＝②變體要另外生成幾張，F07-I09 之後 `style_key`
    這個鍵接了就丟，不再是有意義的欄位）。`context` 可以帶 `origin_label`
    （例如「投放中心 → Beast Gummy｜9 月新客開發 → Meta → 新客｜Broad」）跟
    `origin_href`（app 內相對路徑）——兩者皆選填、
    原樣存在既有的 `context_json` 欄位，工作檯不解讀，只在 `pack_detail`／`set_detail`
    原樣吐回（F03-I07）。`required_outputs` 只收 `copy`／`image_prompt`／`video_script`——
    `free` 是退休的舊 part，出現在這裡一律 `ValueError("part_retired")`（那是自由創作
    用 `source_kind="free_job"` 標識自己，兩者不撞名）。一個 set 沒過驗證，這支整個
    不寫任何一列（見 `repository.submit_pack` 檔頭的完整錯誤代碼清單）。"""
    from app.workbench import repository as workbench_repo

    return workbench_repo.submit_pack(conn, org_id, brand_id, pack)


def pack_for_source(conn, org_id: str, brand_id: str, source_kind: str, source_ref: dict):
    """那個 `source_ref`（JSONB containment，包含給定 dict 全部鍵）最新的一個 pack，附上
    `sets_total`／`sets_done`／`state`，找不到回 `None`。ARCHITECTURE.md §5.5：上游讀
    「核准了沒」用這支——狀態讀取，不是 callback，工作檯完全不知道上游是誰。"""
    from app.workbench import repository as workbench_repo

    return workbench_repo.pack_for_source(conn, org_id, brand_id, source_kind, source_ref)


def briefs_for_source(conn, org_id: str, brand_id: str, source_kind: str,
                       source_ref: dict) -> list:
    """`source_ref` 包含給定 dict 全部鍵的那些 brief，各自附上 status 與每個 part 最新
    一輪的摘要。見契約頁 Exported shapes。"""
    from app.workbench import repository as workbench_repo

    return workbench_repo.briefs_for_source(conn, org_id, brand_id, source_kind, source_ref)


def adopted_output(conn, org_id: str, brand_id: str, brief_id: str, part: str):
    """那個 part 已採用的一列，否則最新一輪，否則 `None`；shape = 那一列本身外加
    `is_adopted`。見契約頁 Exported shapes。"""
    from app.workbench import repository as workbench_repo

    return workbench_repo.adopted_output(conn, org_id, brand_id, brief_id, part)


def set_action_url(conn, org_id: str, brand_id: str, brief_id: str) -> str | None:
    """Return a concrete studio destination only for a set in this tenant and brand."""
    from app.workbench import repository as workbench_repo

    brief = workbench_repo.get_brief(conn, org_id, brand_id, brief_id)
    if brief is None or not brief.get("pack_id"):
        return None
    return f"/app/brands/{brand_id}/workbench/packs/{brief['pack_id']}/sets/{brief_id}"
