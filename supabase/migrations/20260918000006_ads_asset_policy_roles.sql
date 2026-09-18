-- The original policies constrained tenant rows but implicitly targeted PUBLIC.
-- Keep their predicates and grants; narrow policy applicability to authenticated.
ALTER POLICY tenant_scope ON ads_asset_suggestion_batch TO authenticated;
ALTER POLICY tenant_scope ON ads_asset_suggestion_reservation TO authenticated;
ALTER POLICY tenant_scope ON ads_asset_binding TO authenticated;
ALTER POLICY tenant_scope ON ads_asset_observation_claim TO authenticated;
