"""品牌智庫的 web 層路由。

票 08：品牌智庫抽原話／產品調研／顧問報告三種背景工作搬上 `app.background` 佇列
（`docs/contracts/background.md`）。`register(app)` 仍是本模組唯一的對外進入點——
task 註冊沒有另開第二個匯出，而是併進同一支函式：路由掛載只在第一次呼叫真的執行
（`_routes_mounted` 旗標，`main.app` 全程只有一顆，重複掛等於把七個路由多掛一次），
task 註冊每次呼叫都重做（冪等，`if name not in a.tasks`）——跟 `app/schedule/jobs.py`
`register_tasks()` 檔頭同一個理由：`app.background.app()` 的 DSN 換了會整顆重建，
只註冊一次在 DSN 換過之後悄悄失效；測試模組換 schema 後要能重呼叫 `register(app)`
補回這三個 task，又不能把路由重複掛一次，兩件事因此拆成旗標各管各的時機。
"""

_routes_mounted = False


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）＋掛三個背景 task（票 08）。"""
    global _routes_mounted
    if not _routes_mounted:
        from app.brand_web.routes import router as brand_intelligence_router
        from app.brand_web.routes_brand_settings import router as brand_settings_router
        from app.brand_web.routes_inbox import router as inbox_router
        from app.brand_web.routes_library import router as library_router
        from app.brand_web.routes_library_write import router as library_write_router
        from app.brand_web.routes_products import router as products_router
        from app.brand_web.routes_report_api import router as report_api_router

        app.include_router(brand_intelligence_router)
        app.include_router(brand_settings_router)
        app.include_router(inbox_router)
        app.include_router(library_router)
        app.include_router(library_write_router)
        app.include_router(products_router)
        app.include_router(report_api_router)
        _routes_mounted = True

    from app.background import app as background_app
    from app.brand_web.routes_library import background_customer_voice_extraction
    from app.brand_web.routes_products import background_product_scan
    from app.brand_web.routes_report_api import background_brand_report

    # 個別列出、不放進一個共用 tuple／dict 迴圈裡：三支 task body 簽章不同，pyright 會把
    # 迴圈變數的型別統一成交集失敗的 Union，逐支呼叫 `a.task(name=...)(func)` 才留得住
    # 各自正確的型別。
    a = background_app()
    if "background.customer_voice_extraction" not in a.tasks:
        a.task(name="background.customer_voice_extraction")(background_customer_voice_extraction)
    if "background.product_scan" not in a.tasks:
        a.task(name="background.product_scan")(background_product_scan)
    if "background.brand_report" not in a.tasks:
        a.task(name="background.brand_report")(background_brand_report)
