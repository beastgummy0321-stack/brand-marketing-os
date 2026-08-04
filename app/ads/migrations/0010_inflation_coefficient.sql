-- app/ads/migrations/0010_inflation_coefficient.sql
-- Meta 灌水係數＋revenue 反推標記＋對帳頁（GitHub issue #36，決策 0025 七題定案第 1 點、
-- 審查補遺第 3 點）。

-- revenue 來源標記：'reported'（Meta 匯出檔／API 直接給的營收欄）、
-- 'roas_derived'（app/ads/performance.py _derive_revenue_from_roas 用 ROAS 反推）、
-- 'unknown'（既有列回填——revenue 已入庫但當初沒存原始 raw_json，
-- 事後無法分辨是原始欄位還是反推值，誠實標「不知道」而不是亂猜，見鐵則 16）。
-- revenue 本身是 NULL 的列，revenue_source 也維持 NULL（沒有值就沒有來源可言）。
ALTER TABLE performance_snapshot ADD COLUMN revenue_source TEXT;
UPDATE performance_snapshot SET revenue_source = 'unknown'
    WHERE revenue IS NOT NULL AND revenue_source IS NULL;

-- 灌水係數：brand 層累積校準（不是檔期的規劃產物，是跨期學習——比照 learning_ledger 用
-- source_cycle_id 弱關聯＋刪期解除關聯，不進 CYCLE_CASCADE_TABLES）。
-- 每次校準寫一筆新版本，帶 valid_from/valid_to 生效區間；判讀只能引用當時生效版
-- （0025 補遺第 3 點：杜絕歷史被背後抽換）。
CREATE TABLE IF NOT EXISTS ad_revenue_coefficient (
    id TEXT PRIMARY KEY,                    -- arc_*
    brand_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    coefficient REAL NOT NULL,              -- 訂單實收 ÷ Meta 自報營收，本次校準算出的值
    meta_revenue REAL NOT NULL,             -- 校準當下用的 Meta 自報營收（含反推列）
    order_revenue REAL NOT NULL,            -- 校準當下用的訂單淨歸因實收
    sample_size INTEGER NOT NULL,           -- 累積校準次數（含這一次）
    reliable INTEGER NOT NULL DEFAULT 0,    -- 樣本量門檻是否已達（見 app/ads/inflation.py）
    source_cycle_id TEXT REFERENCES campaign_cycle(id),  -- 弱關聯，期被刪只斷開不連坐
    valid_from TEXT NOT NULL,
    valid_to TEXT,                          -- NULL＝目前生效版
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arc_brand_id ON ad_revenue_coefficient(brand_id);
CREATE INDEX IF NOT EXISTS idx_arc_brand_valid ON ad_revenue_coefficient(brand_id, valid_to);

-- 事後誤差紀錄：每次引用某一版係數去預估下一期訂單營收後、實際訂單資料到齊時記一筆
-- 誤差（決策 0025：「係數統計誠實…每次引用後記事後誤差」）。也是自適應降頻判斷穩不穩定的依據。
CREATE TABLE IF NOT EXISTS ad_revenue_coefficient_error_log (
    id TEXT PRIMARY KEY,                    -- rce_*
    brand_id TEXT NOT NULL,
    coefficient_id TEXT NOT NULL REFERENCES ad_revenue_coefficient(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),  -- 弱關聯，理由同上
    predicted_order_revenue REAL,           -- 用引用當下生效版係數 × 這期 Meta 自報營收算出
    actual_order_revenue REAL NOT NULL,
    error_pct REAL,                         -- (實際-預測)/預測；預測為 0 時無法算，留 NULL
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arce_brand_id ON ad_revenue_coefficient_error_log(brand_id, recorded_at DESC);
