-- supabase/migrations/20260904000005_core_decision_columns.sql
-- Module: core (ADR 0049 -- core owns decision). Ticket T6a
-- (docs/issues/t6a-open-the-doors-before-the-data-arrives/ticket.md). ADR 0050's row, verbatim:
-- "add entity_type / entity_id · campaign_period_id · acted_at / acted_by · revert_of ·
-- expires_at. Do not open a new table -- verified 2026-09-04: the table exists with
-- action_json / risk_level / dedupe_key / outcome, and the codebase has zero references to it."
--
-- All nullable, no writer in this ticket -- constitution rule 3: the column exists from day one
-- even though the feature does not. A suggestion that has not been acted on has no acted_at, and
-- one that is not a reversal has no revert_of. revert_of is a self-reference, which is what
-- "undo" means here and what constitution rule 9's "must be able to undo it" needs a place to
-- record.

ALTER TABLE decision
    ADD COLUMN entity_type        text,
    ADD COLUMN entity_id          text,
    ADD COLUMN campaign_period_id text REFERENCES campaign_period(id),
    ADD COLUMN acted_at           timestamptz,
    ADD COLUMN acted_by           text,
    ADD COLUMN revert_of          text REFERENCES decision(id),
    ADD COLUMN expires_at         timestamptz;
