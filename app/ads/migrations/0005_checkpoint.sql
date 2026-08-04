-- app/ads/migrations/0005_checkpoint.sql
-- 票 9（issue #19）：期中檢查點（第 3／7 天）健康檢查＋素材疲勞。
--
-- performance_snapshot 加 frequency 欄位：Meta 匯出檔案常見「頻率」欄（平均每人看過幾次），
-- 素材疲勞判定（app/core/rule_cards.py 的 ad_creative_fatigue 卡）要吃這個數字。頻率不是
-- 可加總的欄位——同一支廣告每天的頻率是「平均每人看過幾次」，不是次數——所以只存，
-- 不進 performance.totals() 的 SUM 邏輯，判讀時另外取這期目前的最大值（保守：看最嚴重的
-- 那一筆，不是拿平均把警訊稀釋掉）。
ALTER TABLE performance_snapshot ADD COLUMN frequency REAL;

-- 檢查點紀錄：提醒卡觸發後「匯入 CSV → 跑健康檢查」的結果落庫，供之後回顧。
-- result_json 明文不含任何「贏／輸」等級欄位（peeking 紀律，ab-testing.md 第 4、7 節）——
-- 這是健康檢查模式的硬規則，不是這裡少寫。
CREATE TABLE IF NOT EXISTS cycle_checkpoint (
    id TEXT PRIMARY KEY,                    -- chk_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    kind TEXT NOT NULL,                     -- day3/day7
    result_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active/archived（決策 0023 第 8 條：新資料實體必附封存＋刪除）
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_checkpoint_cycle ON cycle_checkpoint(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_cycle_checkpoint_brand ON cycle_checkpoint(brand_id);
