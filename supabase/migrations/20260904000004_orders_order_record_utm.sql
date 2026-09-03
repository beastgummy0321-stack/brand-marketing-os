-- supabase/migrations/20260904000004_orders_order_record_utm.sql
-- Module: orders (ADR 0049 -- orders owns order_record). Ticket T6a
-- (docs/issues/t6a-open-the-doors-before-the-data-arrives/ticket.md). ADR 0050's row, verbatim:
-- "utm_json jsonb, stored as imported. Without it real gross margin can never be attached to an
-- ad, and adding it later means re-importing every historical order."
--
-- Nullable, no default, no writer in this ticket -- constitution rule 3: the column exists from
-- day one even though the feature does not. `stored as imported`: whatever the import file
-- carries goes in untouched, no normalisation, no key renaming, no validation.

ALTER TABLE order_record ADD COLUMN utm_json jsonb;
