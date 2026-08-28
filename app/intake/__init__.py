"""app/intake — 建檔精靈（引導式建檔）。見 DESIGN.md §19。

Mock —— 接真 API 輪改存 intake_draft 資料表。

本模組現階段整體是 Mock：精靈第一步（起始輸入）建立的品牌是真的、走
app.brand_intelligence.repository；其餘所有步驟（初掃、問答、交接包、貼回解析）
一律回放 app/intake/script.py 的預寫腳本，不呼叫任何 LLM、不產生任何真實花費。
草稿進度存在本模組的模組層 dict（app/intake/state.py 的 DRAFTS），行程重啟即消失。
"""
