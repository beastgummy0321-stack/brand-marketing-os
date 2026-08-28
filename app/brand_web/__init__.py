"""品牌智庫的 web 層路由。"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）。"""
    from app.brand_web.routes import router as brand_intelligence_router
    from app.brand_web.routes_inbox import router as inbox_router
    from app.brand_web.routes_library import router as library_router
    from app.brand_web.routes_library_write import router as library_write_router
    from app.brand_web.routes_products import router as products_router
    from app.brand_web.routes_report_api import router as report_api_router

    app.include_router(brand_intelligence_router)
    app.include_router(inbox_router)
    app.include_router(library_router)
    app.include_router(library_write_router)
    app.include_router(products_router)
    app.include_router(report_api_router)
