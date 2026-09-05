# AI 呼叫成功、後續存檔失敗時，狀態端點還是報「完成」

Status: before-cloud — 2026-09-05 票 09 審查時量到，同時存在於 `app/intake` 與 `app/brand_web`。

成因：背景工作的形狀是「呼叫 AI → 把結果存起來」。狀態是從 `llm_task` 那一列讀的，而那一列在 **AI
呼叫成功的當下** 就變成 `succeeded`。如果**後面存檔那一段**丟例外（初掃存草稿、人物誌寫回資料表、
貼回修格式套用結果），handler 的外層 `except Exception` 會接住它、送出一則「失敗，可重試」的通知，
然後正常結束——於是下一次輪詢讀到的 `llm_task` 是 `succeeded`、佇列也不再 active，畫面報「完成」。

使用者看到的：一則說失敗的通知，配上一個說完成的畫面，而資料沒有存進去。

這不是票 09 新增的。審查逐條比對後確認 `app/brand_web/routes_products.py` 的 `_research_state()`
（票 08 的樣板，票 09 被指定照抄）**更寬鬆**——它在 `succeeded` 那條分支連 `is_active` 都沒問，
而且 `_apply_product_scan_result` 整段跑在 try/except 之外。票 09 的版本比它嚴，所以不擋票。

`file:line`：`app/intake/persona_generation.py:145-151`、`app/intake/routes_api.py:250-258`；
`app/brand_web/routes_products.py:197-228`。

做法（未裁決）：後續存檔那一段自己的失敗要能被狀態看見——最小做法是 handler 在後處理失敗時把
`llm_task` 那一列標成 `failed`（欄位已經有，不用動 schema），狀態端點照舊讀它。route B，兩個模組
一起改，半天級。門檻是「真的有人回報存檔失敗卻顯示完成」——但上雲之後多租戶、多實例，
存檔失敗的機率只會變高。
