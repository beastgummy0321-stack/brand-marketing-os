-- app/ads/migrations/0008_ga4.sql
-- GA4 彙總新表（GitHub issue #34，決策 0025 第 4 點／審查補遺第 1 點）：
-- UTM 歸因（來源／媒介）放這裡，不塞進 performance_snapshot——那張表的欄位形狀
-- 塞不下來源／媒介這種 GA4 專屬維度（見 app/ads/performance.py 檔頭說明）。
-- 掛品牌層，不進 app/ads/repository.py CYCLE_CASCADE_TABLES（比照
-- app/orders/migrations/0001_orders.sql 的訂單表：GA4 網站流量不因刪某一期廣告
-- 檔期而消失，脫鉤處理）。

CREATE TABLE IF NOT EXISTS ga4_summary (
    id TEXT PRIMARY KEY,               -- ga4_*
    brand_id TEXT NOT NULL,
    date_range_start TEXT NOT NULL,
    date_range_end TEXT NOT NULL,
    source TEXT NOT NULL,
    medium TEXT NOT NULL,
    sessions INTEGER NOT NULL,
    conversions REAL NOT NULL,
    revenue REAL NOT NULL,
    synced_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga4_summary_brand ON ga4_summary(brand_id, date_range_end DESC);

-- 每個品牌最新一次同步的狀態：purchase 事件是否有收到、抓的期間、抓到幾列來源／媒介。
-- 獨立一張表是因為就算來源／媒介彙總是 0 列（真的沒流量），這筆「purchase 有沒有收到」
-- 的誠實驗證狀態也要留得住，不能因為沒資料列可掛就一起消失（鐵則 16 狀態誠實）。
CREATE TABLE IF NOT EXISTS ga4_sync_status (
    brand_id TEXT PRIMARY KEY NOT NULL,
    date_range_start TEXT NOT NULL,
    date_range_end TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    purchase_event_seen INTEGER,       -- NULL＝這次沒驗證到；0／1＝驗證結果
    synced_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
