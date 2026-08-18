-- app/ads/migrations/0018_channel_tracking_check.sql
-- 追蹤健檢結果表（票 T0，契約 1.8）：品牌 x 通路一列，存上次檢測結果＋用不到旗標。
-- 只有 website 真的會查 GA4／Pixel（見 app/ads/tracking.py check_website_now）；其餘
-- 四路（fb_page／ig_account／shopee／pharmacy）的 ga4_found／pixel_found／checked_at
-- 固定是 NULL，狀態即時查 owned_channel／shopee_report_row／pharmacy_batch 得到，
-- 不需要快取。掛品牌層，不進 CYCLE_CASCADE_TABLES（比照 ga4_summary：健檢狀態不因
-- 某一期廣告檔期刪除而消失）。
--
-- ponytail: 沒有登記進 app/ads/repository.py 的 BRAND_CASCADE_TABLES（該檔案已頂到
-- docs/tech-debt.md 凍結行數上限，本票邊界定案明列不得再往裡面加）——刪品牌時這張表
-- 會留下孤兒列。之後有票動到 repository.py 時記得順手補登記。

CREATE TABLE IF NOT EXISTS channel_tracking_check (
    brand_id TEXT NOT NULL,
    channel_key TEXT NOT NULL CHECK (channel_key IN ('website', 'fb_page', 'ig_account', 'shopee', 'pharmacy')),
    hidden INTEGER NOT NULL DEFAULT 0,
    ga4_found INTEGER,      -- NULL／0／1，僅 channel_key='website' 使用
    pixel_found INTEGER,    -- 同上
    checked_at TEXT,        -- 僅 website 使用；其餘四路固定 NULL
    PRIMARY KEY (brand_id, channel_key)
);
