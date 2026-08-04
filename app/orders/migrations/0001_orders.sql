-- app/orders/migrations/0001_orders.sql
-- 訂單明細與顧客新表（GitHub issue #33，決策 0025 補遺第 1、2 點）：
-- 掛品牌層，不進 app/ads/repository.py CYCLE_CASCADE_TABLES（訂單資料不因刪某一期廣告檔期而消失，
-- 比照 learning_ledger 脫鉤——只是這裡連欄位都不掛 campaign_cycle_id，因為訂單本來就不屬於某一期）。
-- 顧客識別鍵：billing email 正規化雜湊為主，缺才退回 billing phone 雜湊（app/orders/identity.py）。

CREATE TABLE IF NOT EXISTS customer (
    id TEXT PRIMARY KEY,               -- cus_*
    brand_id TEXT NOT NULL,
    identity_hash TEXT NOT NULL,       -- sha256(正規化 email 或電話)
    identity_type TEXT NOT NULL,       -- 'email' | 'phone'
    first_order_at TEXT,               -- 目前已知最早一筆訂單日期，用來判新舊客
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_brand_hash ON customer(brand_id, identity_hash);

CREATE TABLE IF NOT EXISTS order_record (
    id TEXT PRIMARY KEY,               -- ord_*
    brand_id TEXT NOT NULL,
    customer_id TEXT,                  -- 訂購人 email／電話都空時為 NULL（優雅缺席，不硬湊一個假顧客）
    order_number TEXT NOT NULL,        -- EasyStore Order Number，同品牌內去重鍵（重複匯入＝更新覆蓋）
    order_date TEXT,
    total_amount REAL,
    refunded_amount REAL,
    financial_status TEXT,
    fulfillment_status TEXT,
    order_status TEXT,
    voucher_code TEXT,
    currency TEXT,
    source TEXT NOT NULL,              -- 'easystore_xlsx'
    import_batch_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_order_brand_number ON order_record(brand_id, order_number);
CREATE INDEX IF NOT EXISTS idx_order_customer ON order_record(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_brand_date ON order_record(brand_id, order_date);

CREATE TABLE IF NOT EXISTS order_item (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    sku TEXT,
    item_price REAL,
    quantity REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_item_order ON order_item(order_id);
CREATE INDEX IF NOT EXISTS idx_order_item_sku ON order_item(brand_id, sku);

-- 逐 SKU 成本登記（選填）：沒登記就誠實顯示「不知道成本」，不假裝算得出毛利（鐵則 16）。
CREATE TABLE IF NOT EXISTS sku_cost (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_cost REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sku_cost_brand_sku ON sku_cost(brand_id, sku);
