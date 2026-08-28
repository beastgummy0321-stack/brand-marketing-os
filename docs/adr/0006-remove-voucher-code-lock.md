# 拿掉配碼校驗不符鎖住開跑的效果，改為只提醒

_Status: retired by ADR 0030 — the code it governed was deleted._

舊規則（決策 0025 補遺第 7 點）：期別配碼上線前校驗，規劃碼（系統算出來的）與後台實際
設定（EasyStore 無 API，人工輸入）逐欄比對，不符時鎖住**僅該期**的開跑動作
（`app/ads/codes.py` `is_activation_locked`，由 `app/ads/handoff.authorize_and_map`
呼叫）——校驗過關或重新校驗過關即解鎖，不需要另外的解鎖操作。

推翻理由：使用者 2026-08-06 grill 第 9、10 題定調。第 9 題定調新增的投放前 QA 自動覆核
一律不擋；第 10 題進一步指出連這個既有硬擋也該拿掉——理由是規則要一致，系統永遠只提醒，
不替人做決定，不留唯一的例外。

新規則：校驗流程本身保留（仍可逐欄比對、仍留紀錄於 `cycle_code_verification`），標示與
人話說明也保留（頁面上不符欄位照樣列出來）；只有「鎖住開跑動作」這個效果拿掉。
`app/ads/codes.py` 的 `is_activation_locked` 改名 `verification_warning`，回傳值語意從
「鎖住原因」改為「警示文字」；`app/ads/handoff.authorize_and_map` 不再讀這個回傳值來擋
`ValueError`，投放授權可以在校驗不符的情況下照常送出。

## Consequences

- 折扣碼設錯會直接上線：使用者若沒注意到警示就按下確認，錯誤的字碼、折數、使用上限或
  效期會被拿去投放，等訂單進來對不上碼才會發現，事後沒得救，只能到 EasyStore 後台重開。
- 稽核紀錄仍完整（`cycle_code_verification`、`write_audit` 都還在），校驗不符的當下狀態
  查得到，但系統不會因此擋人；「決定權在人」代表責任也完全在人。
- 這是全系統最後一個硬擋，拿掉之後全系統一致：所有校驗與檢查都只提醒、不擋流程。之後
  若要再加任何新的擋路邏輯，必須先推翻本 ADR，不得悄悄加例外。
