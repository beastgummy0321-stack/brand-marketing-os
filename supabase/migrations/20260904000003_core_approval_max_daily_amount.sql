-- supabase/migrations/20260904000003_core_approval_max_daily_amount.sql
-- Module: core
-- Ticket: docs/issues/m2-approval-signs-a-ceiling/ticket.md
-- ADR 0059: an approval signs the tree's shape plus a daily ceiling, not a frozen total.
-- `approved_amount` answers "what was the signed daily total at press time" (unchanged,
-- 20260830000001_core_approval.sql). `max_daily_amount` answers a different question: "what
-- is the most today's spend may be under this approval" — the ceiling below which the total
-- is allowed to shrink (a system-driven cut, ADR 0059) without voiding the signature. The two
-- are set equal at press time (app/core/approval.py:approve()) and are not merged into one
-- column, because they diverge the day a ticket lets a user raise a ceiling without
-- re-approving the shape (ADR 0059's rejected-alternatives list).
--
-- Three statements, not one: ADD nullable, UPDATE existing rows to their own approved_amount
-- (the ceiling a past approval always implied, since no code before this ticket ever let the
-- two numbers differ), then tighten to NOT NULL — the backfill has to run between the add and
-- the constraint or this file cannot apply to a database that already has approval rows. It
-- applies to today's empty table (0 rows, measured 2026-09-04) the same way.
ALTER TABLE approval ADD COLUMN max_daily_amount numeric(14,2);
UPDATE approval SET max_daily_amount = approved_amount WHERE max_daily_amount IS NULL;
ALTER TABLE approval ALTER COLUMN max_daily_amount SET NOT NULL;
