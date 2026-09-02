-- supabase/migrations/20260903000007_meta_ad_account_allocation_weight.sql
-- Module: meta (ADR 0049 -- brand_meta_ad_account is this module's table, so the ALTER carries
-- this module's prefix even though ticket T3a is a schedule slice).
-- Dormant by decision (ADR 0055 §9): no writer, no reader in T3. It exists because one ad
-- account bound to two brands would otherwise have the same day's spend counted in full by
-- both. The application layer blocks the second brand today; the schema deliberately does not
-- (ADR 0050), so there is no unique constraint here either.
ALTER TABLE brand_meta_ad_account
    ADD COLUMN allocation_weight numeric(6,3) NOT NULL DEFAULT 1.0;
