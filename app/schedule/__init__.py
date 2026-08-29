"""app/schedule/__init__.py — single entry point (container contract §1, ticket 07).

Shapes other modules may use:
    register(app: FastAPI) -> None    # mounts /api/schedule/*

Everything else in this package (`plan.py`, `tree.py`, `creative.py`, `routes.py`) is private —
nothing outside this package imports them. Callers: `app/main.py`'s register loop, and nothing
else.

Depends on `app.core` (db, rule_cards), `app.llm` (gateway, providers, context_compiler,
methodology), `app.shared.web`, `app.brand_intelligence.repository`. Does not import or
touch `app.main`, any other module's tables, or `procrastinate_*`.

No `app.core.cleanup` registration: this module owns no table of its own — the record is
`llm_task` (ADR 0032), which lives in `app.llm`'s territory — so a brand deletion has
nothing here of its own to cascade.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/schedule/* 路由（機械式，比照 app/meta/__init__.py 的延遲 import 慣例）。"""
    from app.schedule import routes as schedule_routes

    app.include_router(schedule_routes.router)
