-- app/orders/migrations/0004_policy_change_log.sql
-- 折扣／退款口徑變更紀錄（GitHub issue #39，決策 0025 第 4 點：「折扣規則／退款政策等口徑
-- 變更記變更日，跨口徑比較標注不同尺」）。
--
-- 品牌層資產，不掛檔期外鍵（跟 sku_cost_version 一樣是跨期累積事實，不是某一期的規劃產物），
-- 不進 app/ads/repository.py CYCLE_CASCADE_TABLES；品牌被刪除時走品牌層級的清除，不受單一
-- 檔期刪除影響。

CREATE TABLE IF NOT EXISTS policy_change_log (
    id TEXT PRIMARY KEY,                -- pcl_*
    brand_id TEXT NOT NULL,
    policy_type TEXT NOT NULL,          -- 'discount' | 'refund'
    changed_at TEXT NOT NULL,           -- 生效日
    description TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_policy_change_brand_date ON policy_change_log(brand_id, changed_at);
