-- Module: brand_intelligence. Ticket: F42-I01 (feature F42, decision "where each brand fact lives").
--
-- Brand onboarding stores what the owner knows about the brand once:
--   * brand.media_capability -- which media the brand can hand in: 'photo' (photo only) or
--     'photo_video'. NULL = never asked (no format filter). Writer:
--     app.brand_intelligence.repository.set_media_capability; readers: brand onboarding and
--     the plan's format filter.
--   * brand_fact 'policy' -- a store policy from the registry POLICY_TYPES (app/core/vocab.py).
--     fact_key = registry key or 'custom'; params_json = its params (custom: {label, offer_key});
--     value = the program-composed ad-ready sentence. Writer: save_brand_policies; readers:
--     brand onboarding, available_offer_keys / offer_sources (planner, copy guard).
--
-- Amends 20260929000002_brand_intelligence_brand_fact_key.sql (F38): fact_key was proof-only;
-- it is now allowed on proof and policy facts, and required on policy facts.
-- brand_fact_proof_key_valid (the six proof kinds) is kept as is.
ALTER TABLE brand ADD COLUMN media_capability text
    CHECK (media_capability IN ('photo', 'photo_video'));

ALTER TABLE brand_fact ADD COLUMN params_json jsonb;

ALTER TABLE brand_fact DROP CONSTRAINT brand_fact_key_only_for_proof;
ALTER TABLE brand_fact ADD CONSTRAINT brand_fact_key_only_for_proof_or_policy
    CHECK (fact_type IN ('proof', 'policy') OR fact_key IS NULL);
ALTER TABLE brand_fact ADD CONSTRAINT brand_fact_policy_key_required
    CHECK (fact_type <> 'policy' OR fact_key IS NOT NULL);
