"""app/orders — 訂單模組（票 03-1 補上模組文件字串：原本是空檔）。"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）。"""
    from app.orders import routes as orders_routes
    from app.orders import routes_api as orders_routes_api

    app.include_router(orders_routes.router)
    app.include_router(orders_routes_api.router)
