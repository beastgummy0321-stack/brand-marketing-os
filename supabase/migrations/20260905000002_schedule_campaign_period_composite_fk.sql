-- supabase/migrations/20260905000002_schedule_campaign_period_composite_fk.sql
-- Module: schedule (ADR 0049). Ticket 07 (docs/issues/deploy/07-campaign-period-composite-fk.md).
--
-- campaign_period had no defence against a cross-organisation reference: every FK into it was
-- single-column, so only application code stopped one organisation's row from pointing at
-- another organisation's period. Copies the ad_channel shape
-- (20260903000006_schedule_channel_entity_map.sql:29): add unique(id, org_id) on the parent,
-- then every FK becomes (fk_col, org_id) REFERENCES campaign_period(id, org_id), so the
-- database itself refuses a mismatched row.
--
-- Constraint names to drop were read out of the live database, not guessed:
--   SELECT conname, conrelid::regclass FROM pg_constraint WHERE confrelid = 'campaign_period'::regclass;
-- This file only touches tables schedule owns: campaign_period, campaign_period_budget_version,
-- period_node_membership, feedback. The other four referencing tables (interrupt, llm_task,
-- decision -- core; channel_revenue -- orders) are out of scope here (ADR 0049,
-- docs/contracts/schedule.md "Must not import or touch -- any other module's tables") and are
-- covered by 20260905000003 and 20260905000004.
--
-- No delete behaviour added: none of the eight original constraints declared ON DELETE CASCADE
-- or SET NULL, so none of the eight rebuilt ones does either.

ALTER TABLE campaign_period ADD CONSTRAINT campaign_period_id_org_id_key UNIQUE (id, org_id);

-- #1 campaign_period.source_period_id (self-reference)
ALTER TABLE campaign_period DROP CONSTRAINT campaign_period_source_period_id_fkey;
ALTER TABLE campaign_period
    ADD CONSTRAINT campaign_period_source_period_id_org_id_fkey
    FOREIGN KEY (source_period_id, org_id) REFERENCES campaign_period(id, org_id);

-- #2 campaign_period_budget_version.campaign_period_id (NOT NULL)
ALTER TABLE campaign_period_budget_version DROP CONSTRAINT campaign_period_budget_version_campaign_period_id_fkey;
ALTER TABLE campaign_period_budget_version
    ADD CONSTRAINT campaign_period_budget_version_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);

-- #3 period_node_membership.campaign_period_id (NOT NULL)
ALTER TABLE period_node_membership DROP CONSTRAINT period_node_membership_campaign_period_id_fkey;
ALTER TABLE period_node_membership
    ADD CONSTRAINT period_node_membership_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);

-- #6 feedback.campaign_period_id
ALTER TABLE feedback DROP CONSTRAINT feedback_campaign_period_id_fkey;
ALTER TABLE feedback
    ADD CONSTRAINT feedback_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);
