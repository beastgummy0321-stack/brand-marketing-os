-- app/ads/migrations/0006_checklist.sql
-- 票 10（issue #20）：投放前檢查清單，分兩類。
--
-- 一次性（品牌層，例如 Pixel 安裝與事件確認）：跨檔期共用同一列，通過即存，
-- 不用每期重新勾——是否要重新浮出由 app/ads/checklist.py 依成效資料現算異常訊號決定，
-- 不落一個「flagged」欄位（現算才不會跟成效資料的最新狀態脫鉤）。
CREATE TABLE IF NOT EXISTS brand_checklist_item (
    id TEXT PRIMARY KEY,                    -- bcl_*
    brand_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    checked_by TEXT,
    checked_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brand_checklist_item ON brand_checklist_item(brand_id, item_key);

-- 每期必看：每一期各自一列，不繼承上一期的勾選狀態（決策 0023 第 17 點：這類項目要逐期看）。
CREATE TABLE IF NOT EXISTS cycle_checklist_item (
    id TEXT PRIMARY KEY,                    -- ccl_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    item_key TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    checked_by TEXT,
    checked_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cycle_checklist_item
    ON cycle_checklist_item(campaign_cycle_id, item_key);
CREATE INDEX IF NOT EXISTS idx_cycle_checklist_brand ON cycle_checklist_item(brand_id);
