"""app/meta/__init__.py — single entry point (container contract §1, ticket 04, 05).

Shapes other modules may use:
    register(app) -> None        # mounts /api/meta/*
    register_task() -> None      # idempotently registers the daily-spend-pull procrastinate
                                  # task against the current app.background.app() (ticket 05)

Everything else in this package (`graph.py`, `repository.py`, `routes.py`, `daily_pull.py`)
is private — nothing outside this package imports them directly. Callers: `app/main.py`'s
register loop (both exports, `register_task()` called once right after the loop) and
app/tests/test_meta_daily_spend.py (which calls `register_task()` again after it gets its
own test module's fresh `background.app()` — see `daily_pull.py`'s docstring for why that
second call is needed, not optional).

Depends on `app.core` (db, audit, cleanup) and `app.shared.web` (conn, require_actor,
require_brand, the ApiError family); `daily_pull.py` also depends on `app.background`
(forward dependency, LAYER_ORDER already allows it). Does not touch `app_setting`, any
other module's tables, or `procrastinate_*` internals directly (see `04-design-approved.md`
and `daily_pull.py`). Registers with `app.core.cleanup` at import time (see
`repository.py`'s tail) so a brand's Meta account bindings are cleaned up on brand
deletion — product dimension: none, this module has no product-layer data.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/meta/* 路由（機械式，比照 app/dashboard/__init__.py 的延遲 import 慣例）。"""
    from app.meta import routes as meta_routes

    app.include_router(meta_routes.router)


def register_task() -> None:
    """票 05：掛每日 Meta 花費拉取的 procrastinate task（冪等）。見 daily_pull.py。"""
    from app.meta import daily_pull

    daily_pull.register_task()
