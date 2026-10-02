-- Module: brand_intelligence. Ticket: F45-I01 (feature F45, docs/architecture/intake.md
-- 「F45 (ruled 2026-10-02): base and composed sell-ways」).
--
-- A sell-way is *base* (one knowledge product, no quantity: a `product` row with parent_id = that
-- product and no component rows) or *composed* (base sell-way × qty):
--   * product_component.product_id is renamed base_sell_way_id -- it now points at an active base
--     sell-way of the same brand, never at a knowledge product, so no reader keeps the old meaning
--     silently. Constraint / index names follow. Writer: save_sell_way; readers:
--     knowledge_product_ids, get_product_economics (derived numbers), list_sell_ways,
--     composed_using, available_offer_keys / offer_sources, delete_product_data.
--   * product.free_shipping -- 「這個賣法免運」. Writer: save_sell_way; readers: list_sell_ways,
--     available_offer_keys / offer_sources (the sell-way's own free_shipping sentence).
--   * product_economics / product_economics_version .selling_price DROP NOT NULL -- a composed
--     sell-way's empty price = Σ qty × each base's confirmed price, derived on read by
--     get_product_economics. save_sell_way only writes NULL for a composed row whose bases all have
--     a confirmed price in its currency, so the effective price readers (schedule diagnosis, ads
--     repository) never see NULL through the product writers.
--
-- Legacy rows (F43 meaning: product × qty): a sell-way with exactly one qty-1 component row is a
-- base -- that row is dropped (its parent_id already names the product). Every other sell-way with
-- component rows is archived and its rows deleted (its quantity had no unit). No backfill: test
-- data is rebuilt (CLAUDE.md 資料狀態). After this the table holds no row of the old meaning.
--
-- `grep -rn "REFERENCES product" supabase/migrations/` before this migration (nothing is
-- re-pointed: base_sell_way_id keeps its FK to product(id) ON DELETE CASCADE):
--   20260826000002_brand_intelligence_baseline.sql: product_fact, product_economics,
--     brand_performance_baseline, rule, claim, official_asset, strategy_hypothesis (dropped)
--   20260903000004_brand_intelligence_product_economics_version.sql: product_economics_version
--   20260909000001_workbench_baseline.sql / 20260911000002: workbench_brief (ON DELETE SET NULL)
--   20260913000001_ads_tables.sql / 20260927000007: ads_ad (ON DELETE SET NULL)
--   20260914000001_brand_intelligence_product_hierarchy_and_economics.sql: product.parent_id
--   20261002000001_brand_intelligence_sell_way.sql: product_component (sell_way_id, product_id),
--     product_customer_group
--   20261002000002_intake_product_prefill.sql: intake_product_prefill

-- Legacy rule first, while product_id still has its F43 meaning.
DELETE FROM product_component c
 WHERE c.qty = 1
   AND (SELECT count(*) FROM product_component o WHERE o.sell_way_id = c.sell_way_id) = 1;

UPDATE product
   SET status = 'archived', updated_at = now()
 WHERE id IN (SELECT sell_way_id FROM product_component)
   AND status <> 'archived';

DELETE FROM product_component;

ALTER TABLE product_component RENAME COLUMN product_id TO base_sell_way_id;
ALTER TABLE product_component
    RENAME CONSTRAINT product_component_product_id_fkey TO product_component_base_sell_way_id_fkey;
ALTER TABLE product_component
    RENAME CONSTRAINT product_component_sell_way_id_product_id_key
    TO product_component_sell_way_id_base_sell_way_id_key;
ALTER INDEX product_component_product_id_idx RENAME TO product_component_base_sell_way_id_idx;

ALTER TABLE product ADD COLUMN free_shipping boolean NOT NULL DEFAULT false;

ALTER TABLE product_economics ALTER COLUMN selling_price DROP NOT NULL;
ALTER TABLE product_economics_version ALTER COLUMN selling_price DROP NOT NULL;
