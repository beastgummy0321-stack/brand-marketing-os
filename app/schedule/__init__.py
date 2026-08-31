"""app/schedule/__init__.py — single entry point (container contract §1, ticket 07, 票 05-1)。

Shapes other modules may use:
    register(app: FastAPI) -> None    # mounts /api/schedule/*
    register_tasks() -> None          # idempotently registers the three generation
                                       # procrastinate tasks against the current
                                       # app.background.app() (票 05-1)

Everything else in this package (`plan.py`, `tree.py`, `creative.py`, `routes.py`, `jobs.py`,
`onboarding.py`, `onboarding_routes.py`) is private — nothing outside this package imports
them. Callers: `app/main.py`'s register loop (both exports, `register_tasks()` called once
right after the loop, same spot as `meta_module.register_task()`) and app/tests (which call
`register_tasks()` again after they get their own test module's fresh `background.app()` —
see `app/schedule/jobs.py`'s `register_tasks()` docstring for why that second call is needed,
not optional, same reason `app/meta/daily_pull.py` already documents).

票 S2：`onboarding_routes.py` 是第二個 `APIRouter`（自己的 `/api/schedule` prefix），跟
`routes.py` 一起掛在 `register()` 裡——不是把「開帳讀歷史」三支端點塞進 `routes.py` 那個
既有的 router（見 `onboarding_routes.py` 檔頭：那個檔案已經在 `FILE_LINE_CAP` 邊上）。
`register_tasks()` 掛的第四個 task（`onboarding.TASK_TYPE`）住在 `app/schedule/jobs.py`
的 `_JOBS` 表裡，這裡的呼叫端一行都不用改。

Depends on `app.core` (db, rule_cards), `app.llm` (gateway, providers, context_compiler,
methodology), `app.shared.web`, `app.brand_intelligence.repository`, `app.meta`
(graph, repository — 票 S2 起 `onboarding.py` 直接呼叫，同 `routes.py` 既有依賴），
`app.background` (forward dependency for `enqueue()`/`register_tasks()`'s target App,
LAYER_ORDER already allows it — same pattern `app.meta` uses). Does not import or touch
`app.main`, any other module's tables, or `procrastinate_*` internals directly —
`app.background` is the only door to procrastinate, this package's own module docstring in
`routes.py` promises that.

No `app.core.cleanup` registration: this module owns no table of its own — the record is
`llm_task` (ADR 0032), which lives in `app.llm`'s territory — so a brand deletion has
nothing here of its own to cascade.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/schedule/* 路由（機械式，比照 app/meta/__init__.py 的延遲 import 慣例）。
    票 S2：第二個 router（`onboarding_routes.py`）跟既有的一起掛，兩個 router 共用同一個
    `/api/schedule` prefix，路徑不會撞（見該檔三支端點的完整路徑）。"""
    from app.schedule import onboarding_routes
    from app.schedule import routes as schedule_routes

    app.include_router(schedule_routes.router)
    app.include_router(onboarding_routes.router)


def register_tasks() -> None:
    """票 05-1：掛三個生成 task（出方案／展開活動樹／產內容），冪等。見 jobs.py。"""
    from app.schedule import jobs as schedule_jobs

    schedule_jobs.register_tasks()
