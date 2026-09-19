-- supabase/migrations/20260920000001_ads_outcome_nullable.sql
-- Module: ads (F16-I01, ruling RC-D). `purchases`/`revenue` on `ads_outcome_daily` were frozen
-- `NOT NULL DEFAULT 0` (20260913000001_ads_tables.sql), so a Meta-sourced row with no tracked
-- purchase/revenue count had no way to say "unknown" — it physically stored 0, and every reader
-- (`app/ads/outcome.py::_bucket`, `repository._outcome_totals`, `experiments.py`) had to guess
-- which zeros were real and which were missing data by checking `source = 'meta'`, a platform
-- name baked into platform-neutral core. Dropping NOT NULL/DEFAULT lets untracked be `NULL` and
-- a real, counted zero stay `0` — the two stop being the same bit pattern.
--
-- Existing rows are NOT rewritten. Every Meta-sourced row written before this migration still
-- physically holds `purchases = 0`/`revenue` possibly `0`: legacy zero = unknown for
-- Meta-sourced rows written before this migration. A back-fill would have to guess which
-- historic zeros were real, which this ticket does not do.

ALTER TABLE ads_outcome_daily ALTER COLUMN purchases DROP NOT NULL;
ALTER TABLE ads_outcome_daily ALTER COLUMN purchases DROP DEFAULT;
ALTER TABLE ads_outcome_daily ALTER COLUMN revenue DROP NOT NULL;
ALTER TABLE ads_outcome_daily ALTER COLUMN revenue DROP DEFAULT;
