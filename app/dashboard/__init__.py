"""app/dashboard — 駕駛艙（只讀、跨分支彙總）（票 03-1 補上模組文件字串：原本是空檔）。"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）。"""
    from app.dashboard.routes import router as dashboard_router
    from app.dashboard.routes_jobs_api import router as jobs_active_router

    app.include_router(dashboard_router)
    app.include_router(jobs_active_router)
