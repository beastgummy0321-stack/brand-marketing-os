# `_row_hash()` 對 int／float 不穩定

Status: before-cloud——2026-09-05 從 `docs/tech-debt.md` §七認領進上雲目標（使用者裁決：上雲前全清）。
路線：route C（金流）。

**`_row_hash()` 對 int／float 不穩定（T7 審查活體證出）**：`app/orders/channel.py` 把 `revenue`／`quantity`
直接餵 `json.dumps`，`hash(5000, 3)` ≠ `hash(5000.0, 3.0)`。今天唯一呼叫端 `app/orders/routes_api.py:161,164`
先過 `parse_number()`（`app/shared/web.py:291-298`，永遠回 `float | None`）所以壓成同一個雜湊。
防線是隱性的：第二個呼叫端（補登腳本、後台工具）一出現，去重靜靜失效，營收翻倍那顆 bug 回來。
根治兩行（`float()` 統一），但是金流路徑，走 route C。
