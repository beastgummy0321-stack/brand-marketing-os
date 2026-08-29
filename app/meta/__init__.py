"""app/meta/__init__.py — single entry point (container contract §1, ticket 04).

Shapes other modules may use:
    register(app) -> None    # mounts /api/meta/*

Everything else in this package (`graph.py`, `repository.py`, `routes.py`) is private —
nothing outside this package imports them directly. Callers: `app/main.py`'s register
loop, and nothing else (ticket 05 will add a second export; not this ticket's job).

Depends on `app.core` (db, audit, cleanup) and `app.shared.web` (conn, require_actor,
require_brand, the ApiError family). Does not touch `app_setting`, any other module's
tables, or `procrastinate_*` (see `04-design-approved.md`). Registers with
`app.core.cleanup` at import time (see `repository.py`'s tail) so a brand's Meta account
bindings are cleaned up on brand deletion — product dimension: none, this module has no
product-layer data.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/meta/* 路由（機械式，比照 app/dashboard/__init__.py 的延遲 import 慣例）。"""
    from app.meta import routes as meta_routes

    app.include_router(meta_routes.router)
