-- supabase/migrations/20260920000005_ads_campaign_target.sql
-- Module: ads (F16-I04). Every campaign, system-built or imported, needs a resolvable target
-- cost per result. `success_metric` was limited to cpa/roas/purchases
-- (20260913000001_ads_tables.sql:22, applied -- never edited in place, corrected here by
-- ALTERing the check constraint instead) and an imported campaign had no target concept at all.
--
-- `result_kind` (text, nullable): this campaign's own declared/known "result" label -- the same
-- platform-neutral vocabulary `ads_external_daily.result_kind` already uses (F16-I03:
-- "purchase"/"engagement"/"link_click"/"lead"/...). Never a Meta objective string; the
-- objective -> result mapping stays in the Meta adapter (app/ads/adapters/meta_read.py), not
-- here. NULL means this campaign's own result definition is not yet known -- `app/ads/
-- targets.py::resolve()` treats that as missing data, never as a synonym for "purchase".
--
-- `success_metric` widened with `cost_per_result`: the new, platform-neutral target-cost
-- concept `targets.resolve()` computes/records for. Existing `cpa`/`roas`/`purchases` rows are
-- untouched -- this migration does not back-fill or re-interpret any existing row's meaning.
--
-- `success_basis` keeps its old free-text-sentence meaning for `cpa`/`roas`/`purchases` rows
-- ("目標值的依據（一句話）"). Only when `success_metric='cost_per_result'` is it constrained to
-- the machine label naming which of `targets.resolve()`'s three paths produced
-- `success_target`: `break_even` (product economics), `trailing_30` (this account's own
-- trailing-30-day actual, provisional), or `own` (a user-entered override that always wins).
--
-- `target_revision`: optimistic-concurrency counter for `PUT /api/ads/brands/{b}/campaigns/{c}
-- /target`, the same pattern `ads_month_budget.revision` already uses -- scoped to this one
-- sub-resource so unrelated campaign writes (strategy, plan, bind, ...) never collide with it.

ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_success_metric_check;
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_success_metric_check
    CHECK (success_metric IN ('cpa', 'roas', 'purchases', 'cost_per_result'));

ALTER TABLE ads_campaign ADD COLUMN result_kind text;

ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_cost_per_result_basis
    CHECK (success_metric <> 'cost_per_result' OR success_basis IN ('break_even', 'trailing_30', 'own'));

ALTER TABLE ads_campaign ADD COLUMN target_revision integer NOT NULL DEFAULT 0;
