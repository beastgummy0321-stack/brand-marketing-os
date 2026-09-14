"""app/intake — 建檔精靈（引導式建檔）。契約頁 docs/contracts/intake.md。

這段 docstring 到 2026-09-05 為止還在說本模組整體是 Mock、不呼叫任何 LLM、草稿存在
state.py 的 DRAFTS dict 裡重啟即消失。三句都已經不成立，寫契約頁時實測後改掉：

- 初掃、出題、貼回修格式、人物誌生成都真的呼叫 LLM，全部經 app/llm/gateway.run_task
  （app/intake/ai.py:45、app/intake/persona_generation.py:95），會寫 llm_task、會算成本。
- app/intake/script.py 不再是回放腳本，剩下的是提示詞零件與上限常數（MAX_QUESTIONS、
  output_contract_block、build_prompt）以及 card_test.py 的取樣資料；它自己的檔頭也還沒更新。
- 草稿每次讀寫都經 repository.py 落地 intake_draft 表，重啟可續接（state.py:1-7）。DRAFTS
  這個名字已經不存在。

票 09：四種背景工作搬上 `app.background` 佇列；`register()` 比照 `app/brand_web/__init__.py`。
"""

_routes_mounted = False


def register(app) -> None:  # 掛路由（票 03-1）＋掛四個背景 task（票 09）
    global _routes_mounted
    if not _routes_mounted:
        from app.intake.routes import router as intake_router
        from app.intake.routes_api import router as intake_api_router

        app.include_router(intake_router)
        app.include_router(intake_api_router)
        _routes_mounted = True

    from app.background import app as background_app
    from app.intake.persona_generation import background_intake_persona
    from app.intake.research import background_intake_research
    from app.intake.routes_api import (
        background_intake_paste_fix,
        background_intake_question,
        background_intake_scan,
    )

    a = background_app()  # 簽章相同的可以迴圈註冊（跟 brand_web 三支簽章互異、逐支手寫不同）
    for name, func in (("background.intake_scan", background_intake_scan),
                       ("background.intake_question", background_intake_question),
                       ("background.intake_paste_fix", background_intake_paste_fix),
                       ("background.intake_persona", background_intake_persona),
                       ("background.intake_research", background_intake_research)):
        if name not in a.tasks:
            a.task(name=name)(func)
