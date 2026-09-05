-- supabase/migrations/20260905000004_orders_channel_revenue_period_fk.sql
-- Module: orders (ADR 0049). Ticket 07 (docs/issues/deploy/07-campaign-period-composite-fk.md).
--
-- Third of three files closing every foreign key into campaign_period (see
-- 20260905000002_schedule_campaign_period_composite_fk.sql, which must run first: it adds the
-- unique(id, org_id) that this composite FK requires). This file only touches the one table
-- orders owns among the eight: channel_revenue (docs/contracts/schedule.md "Must not import or
-- touch -- any other module's tables", ADR 0049).
--
-- Constraint name read out of the live database (pg_constraint), not guessed. No delete
-- behaviour added: the original constraint was the default NO ACTION.

-- #7 channel_revenue.campaign_period_id
ALTER TABLE channel_revenue DROP CONSTRAINT channel_revenue_campaign_period_id_fkey;
ALTER TABLE channel_revenue
    ADD CONSTRAINT channel_revenue_campaign_period_id_org_id_fkey
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id);
