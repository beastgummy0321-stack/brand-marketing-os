-- supabase/migrations/20261005000101_brand_intelligence_close_rate_percent.sql
-- Module: brand_intelligence. F50-I04 (feature F50 Contract I, decision 9): a rate is stored as
-- the percent the user typed -- 20 means 20% -- like the rule card's `step_rate`. `close_rate`
-- moves from a 0–1 fraction to 0–100 on both economics tables; stored values are multiplied by
-- 100 in the same statement (test data only, CLAUDE.md 資料狀態). The one multiplier is
-- `app.core.input_rules.rate_fraction`.

ALTER TABLE product_economics DROP CONSTRAINT IF EXISTS product_economics_close_rate_check;
ALTER TABLE product_economics
    ALTER COLUMN close_rate TYPE numeric(5,2) USING close_rate * 100;
ALTER TABLE product_economics ADD CONSTRAINT product_economics_close_rate_check
    CHECK (close_rate IS NULL OR (close_rate > 0 AND close_rate <= 100));
COMMENT ON COLUMN product_economics.close_rate IS
    '成交率（百分比 0–100，填 20 代表 20%），NULL＝一次轉換就是一次成交（商品）；服務／名單型填成交率。';

ALTER TABLE product_economics_version
    DROP CONSTRAINT IF EXISTS product_economics_version_close_rate_check;
ALTER TABLE product_economics_version
    ALTER COLUMN close_rate TYPE numeric(5,2) USING close_rate * 100;
ALTER TABLE product_economics_version ADD CONSTRAINT product_economics_version_close_rate_check
    CHECK (close_rate IS NULL OR (close_rate > 0 AND close_rate <= 100));
