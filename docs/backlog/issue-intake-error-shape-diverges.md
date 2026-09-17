# 建檔精靈的錯誤格式跟全站其他地方不一樣（三種形狀）

> 歷史問題紀錄：其中舊流程名稱與已刪文件不是目前執行指令。重用症狀／證據前只核對受影響路徑；規劃依 CLAUDE.md 與現行架構。保留未解問題，不以紀錄年代判定已解決。


Status: before-cloud — 2026-09-05 寫 `docs/contracts/intake.md` 時實測發現。今天不擋任何事。

成因：`app/intake/` 全模組 grep `ApiError` **零命中**。它自己有兩種錯誤格式，加上全站標準那一種，
同一個前端會遇到三種不同的錯誤內容：

| 出處 | 回傳長相 |
|---|---|
| `app/intake/routes_api.py:54-55`、`routes_t2_api.py:22-23` 的私有 `_error()` | `{"error": "<一句中文>"}`，**沒有 code 欄** |
| `routes_api.py:201,567`、`routes.py:31` 的 `NotFoundKind` | `{"detail": "<kind>"}` |
| 全站其他模組的 `web.ApiError` | `{"error": {code, message, details}}` |

影響：前端要為建檔精靈寫一套額外的錯誤解析，或者乾脆不解析、只顯示原字串。沒有 `code` 表示
畫面永遠分不出「這個錯誤該重試」和「這個錯誤該叫使用者改輸入」。今天沒有畫面需要分岔，所以
是欠帳不是漏洞——但上雲之後多一個租戶、多一種錯誤，這件事會先在客服那裡爆出來。

`file:line`：`app/intake/routes_api.py:54-55,201,567`、`app/intake/routes_t2_api.py:22-23`、
`app/intake/routes.py:31`；對照組 `app/shared/web.py` 的 `ApiError`。

做法（未裁決）：把 `_error()` 換成 `web.ApiError`，每個錯誤點補一個穩定的 `code`。是 route B
（不動 schema、不動金流、不動邊界），但要一次改完整個模組、且前端跟著改一處解析——半天級。
`app/intake/routes_api.py` 現在 750 行、上限 800，這張票很可能會撞到，撞到就停下回報。
