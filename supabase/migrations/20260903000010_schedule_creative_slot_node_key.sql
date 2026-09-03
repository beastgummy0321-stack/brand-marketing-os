-- supabase/migrations/20260903000010_schedule_creative_slot_node_key.sql
-- Module: schedule (ADR 0049). Ticket: T3d. Decision of record: ADR 0055 §1.
-- A slot is identified by the node's position, never by its name. No channel_id: the channel
-- is already pinned by source_tree_task_id, whose llm_task row froze context_scope_json
-- .platform (ADR 0055 section 1) -- a redundant channel_id here would drag ad_channel's lazy
-- row creation into the creative path, which runs before anything is bound.
ALTER TABLE creative_slot ADD COLUMN node_key TEXT
    CHECK (node_key ~ '^[1-9][0-9]*(\.[1-9][0-9]*)*$');
ALTER TABLE creative_slot DROP COLUMN ad_node_name;
ALTER TABLE creative_slot ALTER COLUMN node_key SET NOT NULL;
CREATE UNIQUE INDEX creative_slot_brand_tree_node_idx
    ON creative_slot(brand_id, source_tree_task_id, node_key);
