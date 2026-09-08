"""app/workbench/__init__.py — single entry point (container contract §1, ticket
workbench/02/03, ADR 0068).

Shapes other modules may use:
    register(app: FastAPI) -> None       # mounts /api/workbench/* (routes.py, ticket 03)
    register_tasks() -> None             # idempotently registers `background.workbench_generate`
                                          # against the current app.background.app()
    submit_brief(conn, org_id, brand_id, brief: dict, *, created_by: str) -> str
    briefs_for_source(conn, org_id, brand_id, source_kind: str, source_ref: dict) -> list[dict]
    adopted_output(conn, org_id, brand_id, brief_id: str, part: str) -> dict | None

Everything else in this package (`repository.py`, `jobs.py`, `prompts.py`, `validate.py`,
`routes.py`) is private — nothing outside this package imports them.
Callers: `app/main.py`'s register loop (first two, called once right after the loop, same spot
as `schedule_module.register_tasks()`) and `app/tests` (which call `register_tasks()` again
after they get their own test module's fresh `background.app()` — same reason `app/schedule/
jobs.py`'s `register_tasks()` docstring already documents). `app.schedule.jobs` becomes a caller
of `submit_brief` (once per deepest tree node after a tree succeeds) and `app.schedule.state`/
`app.schedule.performance` of `briefs_for_source`/`adopted_output` once ticket 05 lands the
schedule handoff (ADR 0068 rule 2: dependency is one-way, schedule imports workbench, never the
reverse).

Depends on `app.core`, `app.background`, `app.llm`, `app.shared.web`, `app.identity`,
`app.brand_intelligence.repository` (read-only) — docs/contracts/workbench.md "Allowed
dependencies". Does not import or touch `app.schedule`, `app.main`, `app.meta`,
`app.dashboard`, or another module's tables directly: a `source_ref` is stored and compared,
never interpreted (contract "Must not import or touch"). `repository.list_coordinate_vocabulary`
reads `app.schedule`'s `brand_coordinate`/`feedback` tables by raw SQL, not by importing that
package — container contract rule 5 allows duplicating a query across modules.

`app.core.cleanup` registration (this ticket): `repository.py`'s module tail registers
「素材工作檯」, covering `workbench_brief`/`workbench_output`; brand dimension only — this
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


def submit_brief(conn, org_id: str, brand_id: str, brief: dict, *, created_by: str) -> str:
    """寫一列 `workbench_brief`，依 `brief["kind"]`／`brief["request"]` 排進要生成的
    part，回傳 brief id。見 `docs/contracts/workbench.md` Exported shapes。"""
    from app.workbench import repository as workbench_repo

    return workbench_repo.submit_brief(conn, org_id, brand_id, brief, created_by=created_by)


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
