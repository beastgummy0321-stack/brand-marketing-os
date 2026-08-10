-- app/core/migrations/0011_campaign_skip.sql
-- 這期跳過紀錄（票 03-cycle-skip-record，ADR 0015）：使用者標記「這次不投某個節日檔期」，
-- 純脈絡用途——明年同一節日提醒觸發時附帶顯示去年的理由，不寫入、不影響
-- app/ads/nextcycle.py 下期建議引擎的任何計算。跟 ADR 0014 的永久覆寫（不同表）語意不同：
-- 這裡是「今年不投不代表明年不投」。
--
-- 放在 app/core 而不是 app/dashboard：app/dashboard 是唯讀彙總層（票
-- 02-overview-cards 定案，app/tests/test_architecture_boundaries.py
-- DashboardReadOnlyTest 機器檢查擋下任何寫入 SQL），比照既有 rule_card／pacing_card
-- 等窄範圍功能狀態掛在 app/core 的做法（見 0003/0004/0005/0009 各檔）。
--
-- holiday_id 是節日跨年份的穩定識別碼，不是 campaign_calendar_data.json 逐年事件的 id
-- （同一節日逐年 id 不同，例如 cny_2026／cny_2027）——見
-- app/dashboard/campaign_calendar.py holiday_id()，去掉事件 id 尾碼的西元年份即為此欄位值。
--
-- brand_id 跨模組欄位不建 DB 外鍵（比照 interrupt，見
-- app/core/migrations/0006_interrupts.sql 說明）。
CREATE TABLE IF NOT EXISTS campaign_skip (
    id TEXT PRIMARY KEY,             -- csk_*
    brand_id TEXT NOT NULL,
    holiday_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    reason TEXT,                     -- 選填
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_skip_brand_holiday_year
    ON campaign_skip(brand_id, holiday_id, year);
