# 一句話建草稿：使用者明寫「CPA 在 300 以內」，成功目標仍解析成 null

Status: 2026-09-13 F03 驗收時用真後端＋真 LLM（codex_cli）打 `POST /api/ads/brands/{b}/campaigns` 量到。

Observed: goal_text「9 月推 Beast Gummy 高咖啡因軟糖給上班族，目標是購買，希望 CPA 在 300 以內，預算三萬。」
→ `success_metric = "cpa"`（對）、`success_target = null`（錯：句子裡有明確數字 300）。結案因此判「看不出」而不是對 300 比。
同一句的「預算三萬」也沒有進 `constraints`／情境（使用者要手動走「自訂預算」填 30000）。

Not a bug in the null rule（null 合法是 F03 定案）；是 `app/departments/ads/brief_parse.md` 沒有要求「句中出現的數字必須抓成
target／budget，抓不到才回 null」，也沒有 falsifier 用帶數字的句子測。F04 排進去：prompt 加一條「數字優先」規則＋一條帶數字的測試。
