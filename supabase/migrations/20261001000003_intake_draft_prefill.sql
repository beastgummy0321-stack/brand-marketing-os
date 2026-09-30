-- Module: intake. Ticket: F42-I01 (feature F42, decision "where each brand fact lives").
--
-- The brand-onboarding AI scan's structured prefill: what the website/photo scan found per
-- onboarding field, with its source note. A proposal shown on each step, never a confirmed
-- fact -- confirmed values are written to the brand (brand_fact / rule / brand columns) only
-- when the user presses 下一步. NULL = no scan yet.
ALTER TABLE intake_draft ADD COLUMN prefill_json jsonb;
