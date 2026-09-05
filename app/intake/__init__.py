"""app/intake — 建檔精靈（引導式建檔）。契約頁 docs/contracts/intake.md。

這段 docstring 到 2026-09-05 為止還在說本模組整體是 Mock、不呼叫任何 LLM、草稿存在
state.py 的 DRAFTS dict 裡重啟即消失。三句都已經不成立，寫契約頁時實測後改掉：

- 初掃、出題、貼回修格式、人物誌生成都真的呼叫 LLM，全部經 app/llm/gateway.run_task
  （app/intake/ai.py:45、app/intake/persona_generation.py:95），會寫 llm_task、會算成本。
- app/intake/script.py 不再是回放腳本，剩下的是提示詞零件與上限常數（MAX_QUESTIONS、
  output_contract_block、build_prompt）以及 card_test.py 的取樣資料；它自己的檔頭也還沒更新。
- 草稿每次讀寫都經 repository.py 落地 intake_draft 表，重啟可續接（state.py:1-7）。DRAFTS
  這個名字已經不存在。
"""


def register(app) -> None:
    """掛本模組所有路由（票 03-1，機械式搬移自 app/main.py）。"""
    from app.intake.routes import router as intake_router
    from app.intake.routes_api import router as intake_api_router

    app.include_router(intake_router)
    app.include_router(intake_api_router)
