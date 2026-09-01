-- supabase/migrations/20260901000001_meta_spend_history_restrict.sql
-- Module: meta (docs/issues/T-fk-spend-history/ticket.md)
-- Rule: migration files only CREATE tables prefixed/owned by this module. This file instead
-- drops and recreates a constraint on meta_entity_spend, which this module already owns
-- (created in 20260830000004_meta_entity_spend.sql) -- same precedent as that file: touching
-- your own module's table is not a cross-module write and is not subject to the ownership
-- registry (test_migration_ownership.py only inspects CREATE TABLE statements).

-- meta_entity_spend is the only place ad spend exists -- no export, no snapshot, no second
-- copy. Its FK to meta_ad_account was ON DELETE CASCADE, so deleting an ad account silently
-- deletes every spend row it ever produced. Nothing in this repo currently deletes
-- meta_ad_account (the one DELETE route only removes a brand_meta_ad_account mapping row),
-- so this is a loaded gun with no trigger today -- but a future DELETE, a bulk cleanup
-- script, or one line of manual SQL is all it takes, and the loss would be silent and total.
-- The record of what was true then must not be reachable by an operation about what is true
-- now (constitution rule 7). Money history is protected; deleting an account with spend on
-- record is refused instead.
--
-- brand_meta_ad_account_ad_account_id_fkey stays CASCADE -- that is a mapping, not history.
-- meta_daily_spend's constraint is out of scope: 20260830000004_meta_entity_spend.sql already
-- DROP TABLE'd it.
ALTER TABLE meta_entity_spend DROP CONSTRAINT meta_entity_spend_ad_account_id_fkey;
ALTER TABLE meta_entity_spend
  ADD CONSTRAINT meta_entity_spend_ad_account_id_fkey
  FOREIGN KEY (ad_account_id) REFERENCES meta_ad_account(id) ON DELETE RESTRICT;
