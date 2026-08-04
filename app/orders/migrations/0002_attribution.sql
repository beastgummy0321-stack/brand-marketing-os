-- app/orders/migrations/0002_attribution.sql
-- 訂單手動排除歸因（GitHub issue #35，決策 0025 補遺第 3 點）：
-- 訂單可勾「非廣告來源」，報表毛歸因（含存疑）／淨歸因並列，判讀一律用淨歸因。
-- 掛在既有 order_record 上（不是新表）：這是既有訂單列的一個屬性，不是新資料源。

ALTER TABLE order_record ADD COLUMN attribution_override TEXT;  -- NULL | 'excluded'
