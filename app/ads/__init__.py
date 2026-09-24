"""app/ads/__init__.py — single public entry point (container contract §1,
ARCHITECTURE.md §2/§4/§6, ticket F03-I01).

Shapes other modules may use:
    register(app: FastAPI) -> None       # mounts /api/ads/* (routes.py)
    register_tasks() -> None             # idempotently registers `background.ads_close_expired`
                                          # (+ its periodic dispatch) against the current
                                          # app.background.app() — F03-I12, see jobs.py. Despite
                                          # the name, it never closes a campaign on its own
                                          # (F16-I05): it only enqueues runtime monitoring for
                                          # campaigns past their end date; close-out is a user
                                          # action.
    launch_readiness(conn, org_id, brand_id) -> dict
                                          # F05-I04: the launch readiness checklist
                                          # (ARCHITECTURE.md §8 第 5 條). This is the only `ads`
                                          # shape `intake` is allowed to use (manifest
                                          # `may_depend_on`).

Everything else in this package (`repository.py`, `routes.py`) is private — nothing outside
this package imports them. This module owns `ads_campaign`/`ads_delivery_group`/`ads_ad`/
`ads_action`/`ads_outcome_daily` and may depend on `app.workbench` (readiness/handoff, existing
public entries only — §0's "Workbench handoff" rule) plus the usual `app.core`/`app.shared.web`/
`app.identity`/`app.brand_intelligence` (read-only) facades every module reaches through. It
does not import or touch `app.schedule`, `app.meta`, `app.main`, or another module's tables
directly — matching data is read through `app.meta.repository`'s public functions, never a raw
SQL join into `meta_*` tables (ARCHITECTURE.md §0 "Outcome ingest"/"Matching is by exact name").

Callers: `app/main.py`'s register loop (next to `schedule`/`workbench`, same pattern).

`app.core.cleanup` registration (this ticket): `repository.py`'s module tail registers
「投放中心」, covering the five `ads_*` tables; brand dimension only — this module has no
product-layer data, so `count_product`/`delete_product` are explicitly `None` and
`product_tables` is an explicit empty `frozenset()`.
"""

from fastapi import FastAPI


def register(app: FastAPI) -> None:
    """掛 /api/ads/* 路由（機械式，比照 app/workbench/__init__.py 的延遲 import 慣例）。"""
    from app.ads import (
        angle_routes,
        change_routes,
        external_routes,
        handoff_routes,
        home_overview_routes,
        learning_routes,
        material_routes,
        month_budget_routes,
        month_summary_routes,
        review_monitor_routes,
        review_routes,
        runtime_routes,
        status_routes,
        user_assets_routes,
    )
    from app.ads import routes as ads_routes

    # F28-I06: mounted before `routes.py`, whose F04-I08 `GET /brands/{b}/home` (no frontend
    # caller left) answers the same path -- the home-overview contract owns it now.
    app.include_router(home_overview_routes.router)
    app.include_router(ads_routes.router)
    app.include_router(external_routes.router)
    app.include_router(user_assets_routes.router)
    app.include_router(change_routes.router)
    app.include_router(month_budget_routes.router)
    app.include_router(month_summary_routes.router)
    app.include_router(review_routes.router)
    app.include_router(material_routes.router)
    app.include_router(handoff_routes.router)
    app.include_router(review_monitor_routes.router)
    app.include_router(runtime_routes.router)
    app.include_router(angle_routes.router)
    app.include_router(learning_routes.router)
    app.include_router(status_routes.router)


def register_tasks() -> None:
    """F03-I12：掛 `background.ads_close_expired`＋每日 periodic dispatch，冪等。名字留著是
    相容既有排入佇列的工作，實際行為（F16-I05 確認）只是替過了 end_date 的 Campaign 排監控
    任務，從不自己結案——結案永遠是使用者動作。見 `app/ads/jobs.py` 檔頭。"""
    from app.ads import angles, review_jobs
    from app.ads import jobs as ads_jobs

    ads_jobs.register_tasks()
    review_jobs.register_tasks()
    angles.register_tasks()


def bootstrap_runtime(conn, timestamp: int, *, limit=100) -> dict:
    """Only the worker holding its schema's exclusive session lock may call this."""
    from app.ads import runtime

    return runtime.bootstrap(conn, timestamp, limit=limit)


def dispatch_runtime(timestamp: int, *, limit=100) -> dict:
    """Periodic read-only sync/health and condition-based review scheduling."""
    from app.ads import runtime

    return runtime.dispatch(timestamp, limit=limit)


def launch_readiness(conn, org_id: str, brand_id: str) -> dict:
    """F05-I04：可投放檢查表，見 `app/ads/readiness.py` 檔頭。純讀取，`intake` 唯一被允許用到
    的 `ads` 東西。"""
    from app.ads import readiness as ads_readiness

    return ads_readiness.launch_readiness(conn, org_id, brand_id)
