# 七維同步閘門的天花板：它是 regex，騙得過

Status: decide-later——值不值得升級留給下一輪判斷；今天不動。
關聯：`CoordinateDimensionSyncTest`（`app/tests/test_architecture_boundaries.py:606-650`）；T8a 審查 2026-09-04 實際騙成功。

成因：把兩份 TypeScript 當純文字讀，`.search()` 找第一個命中＋非貪婪 `\n];` 收尾。審查在真正的
`export const COORDINATE_DIMENSIONS` 前面插一個同名、七鍵正確的假宣告（合法 TS，不同作用域），
收尾 `];` 貼齊行首，再把真正那份拿掉 `format`——閘門全綠。
影響：擋得住正常編輯出的錯（改名、重排、少一個——三種都實測紅過），擋不住刻意構造。
這是開票時自己選的天花板（票面禁裝 TS parser、禁加依賴），不是實作瑕疵。
升級路：裝一支 TS parser，或改用 `tsc` 產出的型別資訊。
