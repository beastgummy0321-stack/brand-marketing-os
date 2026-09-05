# The intake scan's per-photo progress was given up when it moved onto the queue

Status: decided-and-deferred — 使用者 2026-09-05 裁決，記在這裡才不會被當成「不小心弄丟的功能」。

成因：建檔精靈初掃原本靠 `app/intake/routes_api.py:258-279` 的 `on_photo_progress` callback
反覆寫記憶體 dict（`:264-269`），畫面才報得出「正在看照片（第 3／12 張）」。搬上佇列之後狀態來源
是 `llm_task` 那一列，而 `llm_task` 沒有 stage 欄位——一次性的頭尾翻轉接不住逐張進度。

裁決：**不為了這個加 schema 欄位**。票 09 拿掉 callback，畫面只剩「處理中」。

影響：只有這一支有逐步進度，另外六種本來就是頭尾兩態。照片多的時候使用者會盯著一個不會動的
轉圈圈比較久——不是壞掉，是看不出進度。

要恢復的話（不是現在）：`llm_task` 加一個可空的 `stage` 欄位（一個 migration），handler 中途
UPDATE 它，狀態端點原樣吐出去。成本一小時級，門檻是「使用者真的抱怨看不到進度」。

`file:line`：`app/intake/routes_api.py:258-279`、`:264-269`；`supabase/migrations/20260826000001_core_baseline.sql:45-73`（`llm_task`）。
