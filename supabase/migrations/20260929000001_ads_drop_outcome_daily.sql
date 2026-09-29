-- supabase/migrations/20260929000001_ads_drop_outcome_daily.sql
-- Module: ads (F37-I06, ruling 1 of the #13-B dig). Campaign performance has one source:
-- the platform sync table `ads_external_daily` plus the coverage recorded in
-- `context_json.external_sync.observations`. F37-I01..I03 moved every reader and writer
-- (outcome, closeout, review, simulated adapter, simulation recovery) off `ads_outcome_daily`
-- and deleted `POST .../ingest`, so the table has no code path left. Dropping it keeps a future
-- change from quietly writing a second copy of performance again. No foreign key references
-- this table; its index and org-isolation policy go with it.

DROP TABLE IF EXISTS ads_outcome_daily;
