-- supabase/migrations/20260903000002_core_interrupt_period.sql
-- Module: core. Ticket T2a (docs/issues/t2a-period-tables/ticket.md), ADR 0053.
--
-- interrupt.campaign_cycle_id has pointed at nothing since campaign_cycle was dropped
-- (20260828000003_ads_drop_module_tables.sql). Rename it to campaign_period_id and point it at
-- the campaign_period table this ticket just created (20260903000001), so a period-scoped
-- warning's dedupe_key carries the period id (ADR 0053 consequences).
ALTER TABLE interrupt RENAME COLUMN campaign_cycle_id TO campaign_period_id;
ALTER TABLE interrupt ADD FOREIGN KEY (campaign_period_id) REFERENCES campaign_period(id);
DROP INDEX idx_interrupt_cycle;
CREATE INDEX idx_interrupt_period ON interrupt(campaign_period_id);

-- llm_task gets an owner for its spend once a campaign period exists (ADR 0053 consequences:
-- "llm_task.campaign_period_id gives LLM spend an owner"). Nullable, indexed; nothing writes it
-- yet -- that is T2b/T5.
ALTER TABLE llm_task ADD COLUMN campaign_period_id TEXT REFERENCES campaign_period(id);
CREATE INDEX idx_llm_task_campaign_period ON llm_task(campaign_period_id);
