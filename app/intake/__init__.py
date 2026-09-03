"""app/intake — 建檔精靈（引導式建檔）。原設計文件 §19 已被 5eca0db 清除。

Mock —— 接真 API 輪改存 intake_draft 資料表。

本模組現階段整體是 Mock：精靈第一步（起始輸入）建立的品牌是真的、走
app.brand_intelligence.repository；其餘所有步驟（初掃、問答、交接包、貼回解析）
一律回放 app/intake/script.py 的預寫腳本，不呼叫任何 LLM、不產生任何真實花費。
草稿進度存在本模組的模組層 dict（app/intake/state.py 的 DRAFTS），行程重啟即消失。
"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）。"""
    from app.intake.routes import router as intake_router
    from app.intake.routes_api import router as intake_api_router

    app.include_router(intake_router)
    app.include_router(intake_api_router)
