-- supabase/migrations/20260928000001_brand_intelligence_product_active_name_unique.sql
-- Module: brand_intelligence. Feature F36-I10 (drill-6 #16, ruling H, Contract W).
--
-- Rule: within one brand, an active parent product name is unique (trimmed, case-insensitive);
-- within one parent, an active sell-way name is unique the same way. Archived rows never
-- block a new active one, and a sell-way may share a name with another parent (different
-- scope). `repository.create_product` is get-or-create on the same key; these two partial
-- unique indexes are the backstop for rename / restore (`repository.update_product`) and any
-- caller that bypasses the facade.
CREATE UNIQUE INDEX product_active_parent_name_uniq
    ON product (brand_id, lower(btrim(name)))
    WHERE parent_id IS NULL AND status = 'active';
CREATE UNIQUE INDEX product_active_sellway_name_uniq
    ON product (parent_id, lower(btrim(name)))
    WHERE parent_id IS NOT NULL AND status = 'active';
