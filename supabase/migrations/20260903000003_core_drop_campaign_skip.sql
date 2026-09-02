-- supabase/migrations/20260903000003_core_drop_campaign_skip.sql
-- Module: core. Ticket T2a (docs/issues/t2a-period-tables/ticket.md), ADR 0053 §6 / ADR 0054.
--
-- campaign_skip has zero Python callers (grep "campaign_skip" over app/) and its holiday_id
-- column references a table (holiday) that has never existed. ADR 0054 keeps the shared
-- commerce calendar as a department data file read into the prompt, never a table -- drop the
-- orphaned table outright rather than build the holiday table ADR 0050 once named.
DROP TABLE campaign_skip;
