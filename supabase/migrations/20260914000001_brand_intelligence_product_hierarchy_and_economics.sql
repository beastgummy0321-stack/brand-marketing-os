-- supabase/migrations/20260914000001_brand_intelligence_product_hierarchy_and_economics.sql
-- Module: brand_intelligence. Feature F05-I01 (ARCHITECTURE.md §8 items 1-3, settled, do not
-- redesign): one product, many ways to sell it. `parent_id` is self-referencing, exactly one
-- level deep (a child can never have a child -- enforced in create_product(), a CHECK can't see
-- other rows). Knowledge (facts, claims, photos, positioning) hangs off the parent; money
-- (product_economics) hangs off each child sale.
--
-- Same ticket also carries the one-conversion-value shape for services/leads: `close_rate`
-- (NULL = a product, one sale is one conversion, existing behaviour unchanged) and
-- `assumptions_json` (which fields the user left as a benchmark default instead of typing
-- their own number -- clears itself the moment the user edits that field).

ALTER TABLE product ADD COLUMN parent_id TEXT REFERENCES product(id) ON DELETE CASCADE
    CHECK (parent_id IS NULL OR parent_id <> id);
CREATE INDEX idx_product_parent_id ON product(parent_id);
COMMENT ON COLUMN product.parent_id IS
    '賣法掛在母產品底下，只有一層（第二層在 repository.create_product() 擋，CHECK 看不到別的列）。';

ALTER TABLE product_economics ADD COLUMN close_rate numeric(6,4)
    CHECK (close_rate IS NULL OR (close_rate > 0 AND close_rate <= 1));
ALTER TABLE product_economics ADD COLUMN assumptions_json jsonb;
COMMENT ON COLUMN product_economics.close_rate IS
    '成交率，NULL＝一次轉換就是一次成交（商品）；服務／名單型填成交率。';
COMMENT ON COLUMN product_economics.assumptions_json IS
    '["cost","shipping","close_rate"]：使用者按「不知道」填入的基準值欄位，改了就從陣列移除。';

ALTER TABLE product_economics_version ADD COLUMN close_rate numeric(6,4)
    CHECK (close_rate IS NULL OR (close_rate > 0 AND close_rate <= 1));
ALTER TABLE product_economics_version ADD COLUMN assumptions_json jsonb;
