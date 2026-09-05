# 產品調研的狀態端點把「還在排隊」報成「做完了」

Status: before-cloud — 票 08 round 2 審查實測時撞到（2026-09-05）。那位審查員因此誤判了兩次自己的探針結果，追了一段時間才發現不是程式壞了。

成因：`app/brand_web/routes_products.py` 的 `_research_state()` 在查不到 `llm_task` 列時預設回
「done」。票 08 把這三支搬上佇列之後，「查不到列」多了一種新意思——**工作已經排進佇列，但 worker
還沒輪到它**（`llm_task` 的列要等 worker 撿走、而且真的要打 AI 之前才寫）。舊的 dict 版本沒有這個
狀態：按下去的當下就有一筆記錄了。

影響：使用者按了「重新調研」，如果 worker 正忙著別的工作，畫面會在幾秒內顯示「已完成」，然後
資料沒有變。他會以為調研跑過了、只是沒抓到東西。不會算錯錢，也不會多花錢（第二次按下去有
`background.is_active()` 擋著，票 08 round 2 已修），純粹是**畫面說謊**。

顧問報告（`routes_report_api.py` 的 `_job_shape()`）要一併查，形狀相同。

`file:line`：`app/brand_web/routes_products.py` `_research_state()`；`app/brand_web/routes_report_api.py` `_job_shape()`。

做法（未裁決，一小時級）：狀態端點在「查不到 `llm_task` 列」時，先問 `background.is_active(lock)`
——還活著就回「排隊中／處理中」，不然才回「done」。那支函式票 08 已經做好了，這裡只是多問一次。
路線 B（不動 schema、不動金流、不動邊界）。
