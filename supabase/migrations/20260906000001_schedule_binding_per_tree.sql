-- supabase/migrations/20260906000001_schedule_binding_per_tree.sql
-- Module: schedule (ADR 0049). Ticket 10 ("a binding belongs to the tree that made it").
-- Decision of record: ADR 0064, amending ADR 0055 section 1/4 and ADR 0057 section 2.
--
-- A binding is a fact about the tree that made it (ADR 0064 section 1): re-expanding a plan
-- makes a new schedule_tree row, and the old row's channel_entity_map bindings must survive
-- that -- today they do not, because the idempotency key is (org_id, brand_id, channel_id,
-- node_key) alone, so binding the same node_key in a NEW tree overwrites the row the OLD
-- tree made, and that tree's ad -> platform-entity link is gone from the database forever.
-- The fix is the same node_key plus source_tree_task_id.
--
-- NULLS NOT DISTINCT is required, not cosmetic: every row written before source_tree_task_id
-- existed holds NULL there, and the default NULLS DISTINCT would stop those rows colliding on
-- (org_id, brand_id, channel_id, node_key) -- the exact key they collide on today -- and let a
-- second bind against one of those pre-existing nodes duplicate instead of overwrite. Server
-- is PostgreSQL 17.6 (`show server_version`, checked 2026-09-06), so the syntax is available.
--
-- Constraint name read from pg_constraint on 2026-09-06:
-- channel_entity_map_org_id_brand_id_channel_id_node_key_key.
ALTER TABLE channel_entity_map
    DROP CONSTRAINT channel_entity_map_org_id_brand_id_channel_id_node_key_key;
ALTER TABLE channel_entity_map
    ADD CONSTRAINT channel_entity_map_org_id_brand_id_channel_id_node_key_source_tree_task_id_key
    UNIQUE NULLS NOT DISTINCT (org_id, brand_id, channel_id, node_key, source_tree_task_id);

-- Settlement joins on the tree too (ADR 0064 section 4): period_node_membership records which
-- tree's bind wrote it, a plain column, NOT part of period_node_membership_period_node_idx.
-- That index stays exactly as it is -- one membership row per (period, node) is the money
-- guarantee (ADR 0055 section 6; a second row counts one ad set's spend twice inside one
-- settlement), and this ticket does not touch it.
ALTER TABLE period_node_membership ADD COLUMN source_tree_task_id TEXT;

-- No new table, so no RLS/GRANT/POLICY block (same reasoning as
-- 20260903000015_schedule_binding_source_tree.sql). No data migration: data/ is test data
-- (project CLAUDE.md).
