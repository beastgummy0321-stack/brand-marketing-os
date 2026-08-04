-- learning_ledger 遷入品牌永久層（修憲落地 A3，決策 0037 第三節；架構條文見
-- docs/architecture-rules.md A1／A4）。
--
-- 為什麼在這裡建表：Brand Learning 依 docs/domain.md 是品牌永久概念，該表原本建在
-- app/ads/migrations/0001_tables.sql，且已落地不得再編輯（A6）。本模組
-- （brand_intelligence）在啟動時排在 app/ads 之前套用（app/core/db.py 的
-- MODULE_MIGRATIONS），所以全新安裝時由本檔先把表建好；既有資料庫（表已由
-- app/ads 的舊 migration 建好）則下面的 CREATE TABLE IF NOT EXISTS 是無害的
-- no-op，緊接著的 ALTER TABLE 原地補上新欄位——兩種情境都不遺失既有資料，
-- 不是重建空表。之後 app/ads/migrations/0001_tables.sql 自己的
-- CREATE TABLE IF NOT EXISTS learning_ledger 對「表已存在」一樣是 no-op，
-- 兩份定義不會打架。
--
-- 不再照抄舊表 source_cycle_id／source_reading_id 的
-- REFERENCES campaign_cycle(id) / performance_reading(id)：跨模組外鍵原則禁止
-- （A3），品牌永久層反向依賴分支專屬層的表更違反 A1 單向地界。改為純 ID 引用、
-- 不掛外鍵約束——呼叫端仍自行負責解除關聯（見 app/brand_intelligence/repository.py
-- 的 unlink_learning_ledger_reading／unlink_learning_ledger_cycle）。
CREATE TABLE IF NOT EXISTS learning_ledger (
    id TEXT PRIMARY KEY,                    -- lrn_*
    brand_id TEXT NOT NULL,
    product_id TEXT,
    platform TEXT,
    learning_text TEXT NOT NULL,
    applicability_scope TEXT NOT NULL,
    source_cycle_id TEXT,
    source_reading_id TEXT,
    source_hypothesis_id TEXT,              -- 跨模組引用 strategy_hypothesis，僅存 ID
    sample_size TEXT,
    confidence TEXT,
    needs_revalidation INTEGER NOT NULL DEFAULT 0,
    expired INTEGER NOT NULL DEFAULT 0,
    learned_at TEXT NOT NULL,
    created_by TEXT NOT NULL,               -- Supported→Learning 必須由人確認
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lrn_brand_id ON learning_ledger(brand_id);
CREATE INDEX IF NOT EXISTS idx_lrn_source_cycle ON learning_ledger(source_cycle_id);

-- 來源分支欄位（A4 跨分支知識可見性）：品牌永久層每一筆學習都要能回答
-- 「這是哪個分支學到的」。既有資料一律標為 'ads'——這是目前唯一存在過的分支，
-- 是事實不是猜測。DEFAULT 'ads' 只是為了讓這句 ALTER 對舊列與省略此欄位的舊呼叫端
-- 有安全的落點；不代表以後可以省略不填——
-- app/brand_intelligence/repository.py 的 create_learning_ledger_entry() 要求
-- 呼叫端明確傳入 source_track，各分支自己的 repository 薄封裝
-- （如 app/ads/repository.py）固定填自己的分支代號，新分支上線比照辦理。
ALTER TABLE learning_ledger ADD COLUMN source_track TEXT NOT NULL DEFAULT 'ads';
