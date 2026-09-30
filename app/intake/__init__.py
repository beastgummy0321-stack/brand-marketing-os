"""app/intake — 品牌建檔（七步，F42）。契約頁 docs/contracts/intake.md。

- AI 呼叫全部經 app/llm/gateway.run_task（app/intake/ai.py 的網站／照片預填、
  app/intake/custom.py 的「自訂」、app/intake/persona_generation.py 的人物誌），會寫 llm_task、
  會算成本，並受草稿花費上限擋（state.would_exceed；預設值在 app/intake/script.py）。
- 草稿每次讀寫都經 repository.py 落地 intake_draft 表，重啟可續接。
- F42-I14 拆掉舊階段（初掃印象、AI 問答、交接包／貼回、系統調研、真相卡、花費側欄）與它們的
  三個背景工作；舊欄位與 intake_item 留在 schema（測試資料，不在本票遷移）。

票 09：背景工作走 `app.background` 佇列；`register()` 比照 `app/brand_web/__init__.py`。
"""

_routes_mounted = False


def register(app) -> None:  # 掛路由（票 03-1）＋掛背景 task（票 09）
    global _routes_mounted
    if not _routes_mounted:
        from app.intake.routes import router as intake_router
        from app.intake.routes_api import router as intake_api_router

        app.include_router(intake_router)
        app.include_router(intake_api_router)
        _routes_mounted = True

    from app.background import app as background_app
    from app.intake.persona_generation import background_intake_persona
    from app.intake.routes_api import background_intake_scan

    a = background_app()  # 簽章相同的可以迴圈註冊（跟 brand_web 三支簽章互異、逐支手寫不同）
    for name, func in (("background.intake_scan", background_intake_scan),
                       ("background.intake_persona", background_intake_persona)):
        if name not in a.tasks:
            a.task(name=name)(func)
