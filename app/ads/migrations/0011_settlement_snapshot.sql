-- app/ads/migrations/0011_settlement_snapshot.sql
-- 結算版次＋判讀快照基建（GitHub issue #37，決策 0025 審查補遺 C：結算版本化＋判讀快照）。
--
-- 判讀流程改為「先凍結快照、再算判定」（app/ads/settlement.py）：每次判讀先寫一筆
-- settlement_version（這期第幾版、觸發原因、當下是否已結案），再寫一筆 reading_snapshot
-- 凍結判讀當下——各源資料最後到達時間、缺席清單、生效中的灌水係數版本（見 0010 的
-- ad_revenue_coefficient）、關鍵彙總數字；明細鍵值另存 reading_snapshot_input，
-- 兩層是為了讓「同一期兩個版次」能逐鍵比對出差異（issue #37 acceptance：同一期重跑
-- 判讀必產生新版次且快照逐位可比對）。
--
-- 兩張表都掛檔期外鍵：檔期被刪代表這期的判讀史失去意義，跟著連帶刪除
-- （進 app/ads/repository.py CYCLE_CASCADE_TABLES，不比照 learning_ledger 脫鉤）。

CREATE TABLE IF NOT EXISTS settlement_version (
    id TEXT PRIMARY KEY,                          -- setv_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    version INTEGER NOT NULL,                      -- 這個檔期的第幾版判讀，從 1 起
    trigger_reason TEXT NOT NULL,                  -- 'initial' | 'manual_rerun' | 'late_data' | 'correction'
    is_post_close INTEGER NOT NULL DEFAULT 0,      -- 觸發當下檔期是否已是 CLOSED（結案後仍在校正）
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_setv_cycle_version
    ON settlement_version(campaign_cycle_id, version);
CREATE INDEX IF NOT EXISTS idx_setv_brand_id ON settlement_version(brand_id);

CREATE TABLE IF NOT EXISTS reading_snapshot (
    id TEXT PRIMARY KEY,                           -- rsnap_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    settlement_version_id TEXT NOT NULL REFERENCES settlement_version(id),
    coefficient_version_id TEXT REFERENCES ad_revenue_coefficient(id),  -- 判讀當下生效中的灌水係數版本，尚未校準時 NULL
    data_arrival_json TEXT NOT NULL,               -- {"meta": "...", "orders": "...", "ga4": "..."}（各源最後到達時間）
    missing_sources_json TEXT NOT NULL,             -- ["ga4", ...]（缺席清單）
    summary_json TEXT NOT NULL,                    -- 判讀當下的關鍵彙總（檔期層與各產品層 totals）
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rsnap_cycle ON reading_snapshot(campaign_cycle_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rsnap_settlement_version
    ON reading_snapshot(settlement_version_id);

-- 明細鍵值層：把 summary_json 攤平成一列一個鍵，兩個版次的快照才能逐鍵比對出差異
-- （不用寫 JSON diff，直接用 settlement_version.version 對兩批 reading_snapshot_input join 比對）。
-- brand_id／campaign_cycle_id 在這裡是刻意的反正規化（比照 0001_tables.sql 的
-- derived_metric：它也是 performance_snapshot 的子表，但照樣直接帶 campaign_cycle_id）——
-- CYCLE_CASCADE_TABLES 的刪除函式一律用 `WHERE campaign_cycle_id = ?` 整批刪，
-- 子表若只掛父表 id 就得多一層 join 才能刪，直接帶欄位才能沿用同一套機制。
CREATE TABLE IF NOT EXISTS reading_snapshot_input (
    id TEXT PRIMARY KEY,                           -- rsin_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    reading_snapshot_id TEXT NOT NULL REFERENCES reading_snapshot(id),
    scope TEXT NOT NULL,                           -- 'cycle' 或 product_id 或 'sku_cost:<sku>'
    key TEXT NOT NULL,                             -- 輸入鍵，如 spend／impressions／kpis.roas
    value TEXT,                                    -- 一律存字串化的值，方便逐位比對
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rsin_snapshot ON reading_snapshot_input(reading_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_rsin_cycle ON reading_snapshot_input(campaign_cycle_id);
