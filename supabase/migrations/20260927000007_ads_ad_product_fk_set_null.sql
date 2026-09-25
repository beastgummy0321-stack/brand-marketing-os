-- supabase/migrations/20260927000007_ads_ad_product_fk_set_null.sql
-- Module: ads. Ticket F31-I09 (item 13).
--
-- ads_ad.product_id (nullable, single column) had a plain REFERENCES product(id) (default
-- NO ACTION): brand delete order (品牌智庫 deletes product rows before 投放中心 deletes its ads)
-- raised a foreign-key violation for any brand whose ads carry a product, and deleting an
-- archived product that an ad points at failed the same way. Same fix as
-- 20260911000002_workbench_brief_product_fk_set_null.sql: ON DELETE SET NULL, so both delete
-- paths meet at the constraint.
ALTER TABLE ads_ad DROP CONSTRAINT ads_ad_product_id_fkey;
ALTER TABLE ads_ad ADD CONSTRAINT ads_ad_product_id_fkey
    FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE SET NULL;
