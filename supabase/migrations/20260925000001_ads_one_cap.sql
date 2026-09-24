-- supabase/migrations/20260925000001_ads_one_cap.sql
-- Module: ads (F28-I01). One cost-per-result cap per campaign (docs/architecture/ads.md §6.32).
--
-- The canonical store is `ads_campaign.target_cost` with `target_basis='own'`. The older goal
-- columns `success_metric` / `success_target` / `success_basis` stay (never dropped, never
-- edited in an applied migration) but no code reads or writes them after this issue.
--
-- 1. Back-fill: a campaign whose only cap lived in the old store (a cost-per-purchase target
--    typed on the strategy tab, drill 5) gets it copied into the one store. A ROAS or a count
--    target is not a cost cap and is never converted.
-- 2. The trailing-30-day fallback is removed: a stored `trailing_30` label goes back to NULL
--    (`target_cost` is already NULL for it -- `ads_campaign_target_cost_only_for_own`).
-- 3. `target_basis` allows only `own` / `break_even` (NULL = nothing chosen).
-- 4. A system-built campaign no longer needs `success_metric`: the brief writes the cap instead.

UPDATE ads_campaign
   SET target_basis = 'own', target_cost = success_target
 WHERE target_basis IS NULL
   AND success_metric = 'cpa'
   AND success_target > 0;

UPDATE ads_campaign SET target_basis = NULL WHERE target_basis = 'trailing_30';

ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_target_cost_only_for_own;
ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_target_basis_check;
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_target_basis_check
    CHECK (target_basis IN ('break_even', 'own'));
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_target_cost_only_for_own CHECK (
    (target_basis IS NULL AND target_cost IS NULL)
    OR (target_basis = 'own' AND target_cost IS NOT NULL)
    OR (target_basis = 'break_even' AND target_cost IS NULL)
);

ALTER TABLE ads_campaign DROP CONSTRAINT ads_campaign_internal_required;
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_internal_required
    CHECK (origin = 'imported' OR (goal_text IS NOT NULL AND objective IS NOT NULL));
