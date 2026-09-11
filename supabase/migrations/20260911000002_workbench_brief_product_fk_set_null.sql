-- supabase/migrations/20260911000002_workbench_brief_product_fk_set_null.sql
-- Module: workbench. Ticket F01-T05-I01.
--
-- workbench_brief.product_id had a plain REFERENCES product(id) (default RESTRICT/NO ACTION):
-- deleting an archived product with a linked brief raised a foreign-key violation, and brand
-- delete order (品牌智庫 deletes product rows before 素材工作檯 deletes its briefs) hit the
-- same violation. Switch to ON DELETE SET NULL so both delete paths meet at the constraint
-- instead of at two separate app-level fixes.
ALTER TABLE workbench_brief DROP CONSTRAINT workbench_brief_product_id_fkey;
ALTER TABLE workbench_brief ADD CONSTRAINT workbench_brief_product_id_fkey
    FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE SET NULL;
