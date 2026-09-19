-- supabase/migrations/20260920000002_ads_outcome_legacy_meta_unknown.sql
-- Module: ads (F16-I01, ruling RC-D, repair). Normalises rows written before this feature
-- existed. Pre-F16 `ingest_meta` wrote `purchases=0`/`revenue=0` unconditionally for every
-- Meta-sourced row — those literals never recorded an observation; they are not a real,
-- counted zero. Before 20260920000001 (`purchases`/`revenue` NOT NULL DEFAULT 0), readers
-- excluded them with `source != 'meta'` / `revenue != 0` sentinels, so they always read as
-- unknown. Now that readers key on `IS NOT NULL` instead, those old `0` literals would start
-- being summed as real counted zeros — the exact "unknown becomes zero" this feature removes.
-- This statement reproduces the pre-change reading semantics exactly: nothing that worked
-- before this feature changes. It must sort before any migration or ingest that writes real
-- Meta purchases (F16-I05) — a genuine tracked-zero written after this point must stay `0`.

UPDATE ads_outcome_daily SET purchases = NULL WHERE source = 'meta';
UPDATE ads_outcome_daily SET revenue = NULL WHERE source = 'meta' AND revenue = 0;
