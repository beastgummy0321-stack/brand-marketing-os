-- supabase/migrations/20260908000003_brand_intelligence_advertising_history.sql
-- Module: brand_intelligence (ADR 0049). Ticket: past-ads 01
-- (docs/issues/past-ads/01-schema-imported-ad-and-advertising-history.md). ADR 0067 rule 6.
--
-- "The fork is a brand fact." NULL = not yet answered, never defaulted to either value, so a
-- wizard step and the cockpit guide card (a later ticket) can tell "nobody has answered this
-- yet" apart from "answered none" -- the same nullable-switch shape as brand's other
-- methodology switches. Dormant here: this column has no reader and no writer in this ticket
-- (done-check 6); asking it and reacting to it belongs to a later ticket in this slice.
ALTER TABLE brand ADD COLUMN advertising_history TEXT
    CHECK (advertising_history IN ('has_history','none'));
