-- app/orders/migrations/0005_channel.sql
-- 通路對照卡新表（GitHub issue #40，決策 0025 第二節 B）：治兩種系統性誤判——
-- 外溢低估（廣告帶去蝦皮／藥局買，官網數字看不到）、互噬高估（把蝦皮客搬來官網，假新增）。
-- 全部選填，缺就誠實顯示灰燈；規則判定粗標籤＋人話說明，不算歸因比例（見 app/orders/channel.py）。

-- 蝦皮賣家中心報表逐列匯入，品牌層（跨檔期資料，不進 app/ads/repository.py
-- CYCLE_CASCADE_TABLES，比照 order_record／shopee 本身無檔期外鍵可掛——用日期範圍
-- 跟檔期比對，同 app/orders/repository.unsettled_order_ratio 的既有作法）。
-- 格式假設：Shopee 賣家中心「訂單」匯出常見欄名（未經真實檔驗證，見 app/orders/channel.py
-- 檔頭誠實標注）。order_sn 有值時以它去重覆寫，避免歷史回填月份重疊時重複計入營收。
CREATE TABLE IF NOT EXISTS shopee_report_row (
    id TEXT PRIMARY KEY,                -- shp_*
    brand_id TEXT NOT NULL,
    order_sn TEXT,
    order_date TEXT,                    -- YYYY-MM-DD
    revenue REAL,
    voucher_code TEXT,
    source TEXT NOT NULL,
    import_batch_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shopee_report_brand_date ON shopee_report_row(brand_id, order_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shopee_report_brand_sn
    ON shopee_report_row(brand_id, order_sn) WHERE order_sn IS NOT NULL;

-- 藥局出貨批次紀錄：人工填批次日期＋數量，判讀看補貨間隔縮短（抗批發雜訊）。
-- 品牌層、跨期持續累積的營運日誌，不掛檔期外鍵，比照 policy_change_log。
CREATE TABLE IF NOT EXISTS pharmacy_batch (
    id TEXT PRIMARY KEY,                -- phb_*
    brand_id TEXT NOT NULL,
    batch_date TEXT NOT NULL,
    quantity REAL,
    note TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pharmacy_batch_brand_date ON pharmacy_batch(brand_id, batch_date);

-- 蝦皮期別專屬碼（外溢下限鐵證）：碼字在蝦皮賣家中心手動設定，這裡只登記碼字與
-- 回收數（人工看蝦皮後台填），比照 app/ads/migrations/0009 的 cycle_voucher_code——
-- 這是該期的規劃產物，期被刪就該一起消失，進 app/ads/repository.py CYCLE_CASCADE_TABLES，
-- 不比照 learning_ledger 脫鉤。
CREATE TABLE IF NOT EXISTS cycle_shopee_code (
    id TEXT PRIMARY KEY,                -- shc_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    code TEXT,
    redemption_count INTEGER,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shopee_code_cycle ON cycle_shopee_code(campaign_cycle_id);
