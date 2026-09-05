-- supabase/migrations/20260905000003_core_interrupt_llm_task_decision_period_fk.sql
-- Module: core (ADR 0049). Ticket 07 (docs/issues/deploy/07-campaign-period-composite-fk.md).
--
-- Second of three files closing every foreign key into campaign_period (see
-- 20260905000002_schedule_campaign_period_composite_fk.sql, which must run first: it adds the
-- unique(id, org_id) that these composite FKs require). This file only touches tables core
-- owns: interrupt, llm_task, decision (docs/contracts/schedule.md "Must not import or touch --
-- any other module's tables", ADR 0049).
--
-- Constraint names read out of the live database (pg_constraint), not guessed. No delete
-- behaviour added: all three original constraints were the default NO ACTION.

-- #4 interrupt.campaign_period_id
ALTER TABLE interrupt DROP CONSTRAINT interrupt_campaign_period_id_fkey;
ALTER TABLE interrupt
    ADD CONSTRAINT interrupt_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);

-- #5 llm_task.campaign_period_id
ALTER TABLE llm_task DROP CONSTRAINT llm_task_campaign_period_id_fkey;
ALTER TABLE llm_task
    ADD CONSTRAINT llm_task_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);

-- #8 decision.campaign_period_id
ALTER TABLE decision DROP CONSTRAINT decision_campaign_period_id_fkey;
ALTER TABLE decision
    ADD CONSTRAINT decision_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);
