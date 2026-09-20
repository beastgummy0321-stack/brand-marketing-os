-- supabase/migrations/20260920000006_ads_campaign_target_columns.sql
-- Module: ads (F16-I04 repair round). Review of `20260920000005_ads_campaign_target.sql`
-- (applied -- never edited in place, corrected here by a new migration instead) found that
-- overloading `success_metric='cost_per_result'` / `success_basis` / `success_target` for the
-- target-cost concept silently corrupts code far outside this issue's touch: close-out's
-- `_metric_value` has no `cost_per_result` branch and falls through to a purchase *count*
-- compared with `>=` against a money target (a fabricated verdict); `learning.py` prints the raw
-- metric string to users and groups cohorts by it; `budget.py` cold-start and
-- `asset_suggestions.py` both key off `success_metric=='cpa'` / `success_target is not None`.
-- Architect ruling (2026-09-20): the target cost gets its own columns. Nothing in this feature
-- ever writes `success_metric` / `success_target` / `success_basis` again.
--
-- `target_cost` (numeric, nullable) / `target_basis` (text, nullable, CHECK IN ('break_even',
-- 'trailing_30', 'own')): `app/ads/targets.py::resolve()` reads `target_basis='own'` +
-- `target_cost` as the user override that always wins over anything computed. `break_even` and
-- `trailing_30` are always recomputed on read (product economics / this campaign's own
-- trailing-30-day actual, never a stored snapshot that could silently drift from a recomputed
-- one) -- this table only ever records which of those two paths a `PUT` last asked `resolve()`
-- to prefer, never a number for them. The CHECK below enforces exactly that split: `target_cost`
-- is stored only when `target_basis='own'`.
ALTER TABLE ads_campaign ADD COLUMN target_cost numeric;
ALTER TABLE ads_campaign ADD COLUMN target_basis text
    CONSTRAINT ads_campaign_target_basis_check CHECK (target_basis IN ('break_even', 'trailing_30', 'own'));
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_target_cost_only_for_own CHECK (
    (target_basis IS NULL AND target_cost IS NULL)
    OR (target_basis = 'own' AND target_cost IS NOT NULL)
    OR (target_basis IN ('break_even', 'trailing_30') AND target_cost IS NULL)
);

-- Undo `..._0005`'s overload of `success_metric` / `success_basis` for the same concept. No row
-- may already carry `success_metric='cost_per_result'` -- no write path that could have produced
-- one ever shipped past this repair round, so a survivor here means something wrote it out of
-- band; fail loudly rather than silently rewriting a row's meaning.
DO $$
DECLARE
    leftover_count integer;
BEGIN
    SELECT COUNT(*) INTO leftover_count FROM ads_campaign WHERE success_metric = 'cost_per_result';
    IF leftover_count > 0 THEN
        RAISE EXCEPTION 'ads_campaign has % row(s) with success_metric=cost_per_result; this '
            'migration will not silently rewrite them -- resolve manually first', leftover_count;
    END IF;
END $$;

ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_cost_per_result_basis;
ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_success_metric_check;
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_success_metric_check
    CHECK (success_metric IN ('cpa', 'roas', 'purchases'));

-- `result_kind` and `target_revision` (added by `..._0005`) are kept as-is: this migration only
-- touches the target-cost storage shape, not the result-kind vocabulary or the optimistic
-- concurrency counter.
