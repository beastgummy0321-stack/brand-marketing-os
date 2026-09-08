"""app/schedule/__init__.py — single entry point (container contract §1, ticket 07, 票 05-1)。

Shapes other modules may use:
    register(app: FastAPI) -> None    # mounts /api/schedule/*
    register_tasks() -> None          # idempotently registers the three generation
                                       # procrastinate tasks against the current
                                       # app.background.app() (票 05-1)
    imported_ad_count(conn, org_id, brand_id) -> int
                                       # 票 past-ads/03（ADR 0067）：這個品牌標了幾則老廣告，
                                       # 給 app.dashboard 的引導卡用（ticket 04）

Everything else in this package (`plan.py`, `tree.py`, `creative.py`, `routes.py`,
`jobs.py`) is private — nothing outside this package imports
them. Callers: `app/main.py`'s register loop (both exports, `register_tasks()` called once
right after the loop, same spot as `meta_module.register_task()`) and app/tests (which call
`register_tasks()` again after they get their own test module's fresh `background.app()` —
see `app/schedule/jobs.py`'s `register_tasks()` docstring for why that second call is needed,
not optional, same reason `app/meta/daily_pull.py` already documents).

Depends on `app.core` (db, rule_cards), `app.llm` (gateway, providers, context_compiler,
methodology), `app.shared.web`, `app.brand_intelligence.repository`, `app.meta`
(graph, repository），
`app.background` (forward dependency for `enqueue()`/`register_tasks()`'s target App,
LAYER_ORDER already allows it — same pattern `app.meta` uses). Does not import or touch
`app.main`, any other module's tables, or `procrastinate_*` internals directly —
`app.background` is the only door to procrastinate, this package's own module docstring in
`routes.py` promises that.

`app.core.cleanup` registration (ticket T1b, ADR 0049): this module owns five tables now —
`brand_coordinate`, `creative_slot`, `creative_candidate`, `creative_candidate_item`,
`feedback` (see `app/schedule/repository.py`'s module docstring) — registered as
「創意座標與素材候選」, so a brand deletion cascades into all five.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/schedule/* 路由（機械式，比照 app/meta/__init__.py 的延遲 import 慣例）。"""
    from app.schedule import routes as schedule_routes

    app.include_router(schedule_routes.router)


def register_tasks() -> None:
    """票 05-1：掛三個生成 task（出方案／展開活動樹／產內容），冪等。見 jobs.py。"""
    from app.schedule import jobs as schedule_jobs

    schedule_jobs.register_tasks()


def imported_ad_count(conn, org_id: str, brand_id: str) -> int:
    """票 past-ads/03（ADR 0067）：這個品牌已經標了幾則老廣告——延遲 import，比照
    `register()`。"""
    from app.schedule import history as schedule_history

    return schedule_history.imported_ad_count(conn, org_id, brand_id)
