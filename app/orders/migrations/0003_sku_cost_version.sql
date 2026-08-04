-- app/orders/migrations/0003_sku_cost_version.sql
-- SKU 成本帶生效區間版本表（GitHub issue #37）：0001 的 sku_cost 是「登記即覆蓋」的現行值，
-- 成本回改會悄悄改寫過去算過的毛利。這裡加一張版本表，每次 set_sku_cost() 呼叫、且成本真的
-- 變動時新增一版（帶 valid_from/valid_to），舊版 valid_to 封頂但值本身永遠不被覆寫——判讀快照
-- （app/ads/settlement.py）引用版本 id 就能保證「當時用的成本」事後不會被成本回改動過手腳
-- （決策 0025 審查補遺 C）。
--
-- 品牌層資產，不掛檔期外鍵，比照 app/ads/migrations/0010 的 ad_revenue_coefficient 模式
-- （跨期累積學習，不是某一期的規劃產物）。

CREATE TABLE IF NOT EXISTS sku_cost_version (
    id TEXT PRIMARY KEY,                -- skv_*
    brand_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    version INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,                      -- NULL＝目前生效版
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_skv_brand_sku_version ON sku_cost_version(brand_id, sku, version);
CREATE INDEX IF NOT EXISTS idx_skv_brand_sku_valid ON sku_cost_version(brand_id, sku, valid_to);
