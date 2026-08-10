-- app/core/migrations/0012_calendar_dismiss.sql
-- 節日類別永久覆寫（票 02-permanent-dismiss-category，ADR 0014 第二、三節）：使用者把
-- 某個節日類別永久標記「跟我無關」，之後系統業種比對判成相關也不再提醒；可隨時重新開啟。
-- 關閉＝寫入一筆，重新開啟＝刪除該筆；沒有列＝預設「提醒中」（G14.10 空狀態）。
--
-- category 是節日跨年份穩定識別碼（app/dashboard/campaign_calendar.py holiday_id()
-- 同款推導，見 app/core/calendar_dismiss.py 檔頭說明），不是逐年事件 id——同一節日逐年
-- id 不同（cny_2026／cny_2027），業種判斷錯是持續性的錯，要用跨年穩定碼才能一次永久關掉。
--
-- 跟 campaign_skip（票 03-cycle-skip-record，ADR 0015）是不同表：那邊是「這次不投，
-- 明年還提醒」；這裡是「系統業種判斷錯了，明年也不用提醒」，語意不同、刻意不合併
-- （ADR 0014 第二節）。
--
-- 放在 app/core 而不是 app/dashboard：app/dashboard 是唯讀彙總層（app/tests/
-- test_architecture_boundaries.py DashboardReadOnlyTest 機器檢查擋下任何寫入 SQL），
-- 比照既有 campaign_skip（app/core/migrations/0011_campaign_skip.sql）同一個理由。
-- brand_id 跨模組欄位不建 DB 外鍵（比照 interrupt／campaign_skip）。
CREATE TABLE IF NOT EXISTS brand_dismissed_calendar_category (
    id TEXT PRIMARY KEY,             -- bdc_*
    brand_id TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_dismissed_calendar_category_brand_category
    ON brand_dismissed_calendar_category(brand_id, category);
