# The 500 handler returns an HTML page on `/api/*` routes

Status: open (found 2026-09-09 by the route C review of workbench ticket 05, not fixed there).

成因：`app/main.py:498-500` 的 catch-all exception handler 一律回 `_error_page()` HTML；同檔 `:486-495`
的 404 handler 有判 `request.url.path.startswith("/api/")` 才回 JSON，500 沒有。

影響：任何 API 路由的未預期例外，前端拿到的是 HTML，`res.json()` 再炸一次，畫面顯示不出真正的錯誤
訊息（例如 ticket 05 審查重現的 `CheckViolation`）。

`file:line`：`app/main.py:498-500`（500 handler）、`:486-495`（404 handler 的正確寫法）。

做法：500 handler 比照 404 handler，`/api/*` 回 `{"error": {"code": "internal", "message": …}}` JSON 500。
route B，一個測試：對一條會拋例外的假路由打 `/api/...` 斷言 content-type 是 JSON。
