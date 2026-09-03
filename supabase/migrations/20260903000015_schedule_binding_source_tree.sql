-- supabase/migrations/20260903000015_schedule_binding_source_tree.sql
-- Module: schedule (ADR 0049 -- the prefix is the module that OWNS the table, not the ticket
-- that wants it; both tables below are schedule's). Ticket: T5. Decision of record: ADR 0057.
--
-- No new table, so no RLS/GRANT/POLICY block: both tables already carry theirs from
-- 20260901000002 and 20260903000006.

-- ADR 0057 section 2. Which creative is this ad's? Answering it by picking the newest
-- schedule_tree row is the _latest_task_row shape, and creative_slot is unique on
-- (brand_id, source_tree_task_id, node_key) -- so re-expanding the tree gives node 1.2.3 a
-- SECOND slot with a second set of seven-dimension keys, and reading the newest one silently
-- re-attributes last month's money to this month's creative. Constitution rule 7: never answer
-- "what was true then" with a current-state column.
--
-- Written at bind time from the tree row the bind ran against. Nullable, for two reasons that
-- are both real: rows bound before this column existed, and levels 1-2, which have no creative
-- and never will. No foreign key, matching creative_slot.source_tree_task_id (20260901000002),
-- which holds the same value in the same shape.
--
-- A rebinding overwrites it with the rest of the row and keeps no history -- ADR 0055 section 4's
-- deliberate exception, whose named consumer test is unchanged: nothing reads "which entity was
-- this node bound to last month".
ALTER TABLE channel_entity_map ADD COLUMN source_tree_task_id TEXT;

-- ADR 0057 section 3. ADR 0055 section 7 left this column's fate to T5: denormalised
-- convenience, or gone. Gone.
--
-- Measured 2026-09-03 before writing this line: 6 creative_candidate rows, 0 of them with a
-- non-null value here, and a repo-wide unscoped sweep for the NAME returns 4 hits -- BOARD.md,
-- ADR 0050's table list, ADR 0055 section 7, and 20260901000002 which created it. Zero code
-- reads it and zero code writes it.
--
-- channel_entity_map is the single place a node is tied to a platform entity (ADR 0055 section
-- 1). Two columns answering "which ad is this", one of them with no writer, is how someone
-- eventually writes the convenience column without writing the map and produces a binding that
-- the settlement path cannot see.
ALTER TABLE creative_candidate DROP COLUMN published_ad_external_id;
