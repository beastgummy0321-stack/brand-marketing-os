-- supabase/migrations/20260903000001_schedule_campaign_period.sql
-- Module: schedule (ADR 0049 -- migration files take the prefix of the module that owns the
-- table). Ticket T2a (docs/issues/t2a-period-tables/ticket.md). Decisions: ADR 0053 (the
-- period's life), ADR 0050 (the ad-loop data model of record).
--
-- Structure only -- this ticket writes nothing. No route, no repository call inserts into any
-- of these three tables yet; that is T2b.

CREATE TABLE campaign_period (
    id TEXT PRIMARY KEY,                -- cpd_*, via db.new_id("cpd")
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    name TEXT NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning'
        CHECK (status IN ('planning','running','awaiting_data','settled')),
    version INTEGER NOT NULL DEFAULT 1,   -- optimistic lock, T2b uses it
    daily_budget numeric(14,2),           -- the value copied from the rule card at creation
    currency TEXT NOT NULL,
    settled_spend numeric(14,2),          -- all three NULL until settled
    settled_revenue numeric(14,2),
    settled_at timestamptz,
    force_settled_at timestamptz,         -- set when settled before the advice date
    force_settled_reason TEXT,
    recurrence_rule TEXT,                 -- NULL in v1; the door, not the feature
    source_period_id TEXT REFERENCES campaign_period(id),   -- NULL in v1
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);
CREATE INDEX campaign_period_org_id_idx ON campaign_period(org_id);
CREATE INDEX idx_campaign_period_brand_id ON campaign_period(brand_id);

-- Shaped like sku_cost_version (supabase/migrations/20260826000005_orders_baseline.sql:77-91):
-- same version INTEGER counter, same valid_from/valid_to interval names, same three indexes
-- (org_id_idx, unique natural-key+version, natural-key+valid_to) -- here the natural key is
-- campaign_period_id alone rather than brand_id+sku.
CREATE TABLE campaign_period_budget_version (
    id TEXT PRIMARY KEY,                -- cbv_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_period_id TEXT NOT NULL REFERENCES campaign_period(id),
    version INTEGER NOT NULL,
    daily_amount numeric(14,2) NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('initial','manual','auto_decrease','revert')),
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','system')),
    created_by TEXT NOT NULL,
    reverted_from_id TEXT REFERENCES campaign_period_budget_version(id),
    valid_from date NOT NULL,
    valid_to date,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_period_budget_version_org_id_idx ON campaign_period_budget_version(org_id);
CREATE UNIQUE INDEX idx_cpbv_period_version ON campaign_period_budget_version(campaign_period_id, version);
CREATE INDEX idx_cpbv_period_valid ON campaign_period_budget_version(campaign_period_id, valid_to);

-- No unique(ad_set_external_id), ever (ADR 0050): more than one membership can cover the same
-- ad set on overlapping days, resolved at read time by ADR 0053 decision 4 (shorter period
-- wins, equal length splits by allocation_weight). T3 replaces ad_set_external_id with a node
-- key; nothing writes this table until then.
CREATE TABLE ad_set_period_membership (
    id TEXT PRIMARY KEY,                -- aspm_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_period_id TEXT NOT NULL REFERENCES campaign_period(id),
    ad_set_external_id TEXT NOT NULL,   -- the platform's id; T3 replaces it with a node key
    from_date date NOT NULL,
    to_date date,
    allocation_weight numeric(6,3) NOT NULL DEFAULT 1.0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ad_set_period_membership_org_id_idx ON ad_set_period_membership(org_id);
CREATE INDEX idx_aspm_brand_id ON ad_set_period_membership(brand_id);
CREATE INDEX idx_aspm_period_id ON ad_set_period_membership(campaign_period_id);

-- RLS + grants + org-isolation policy for all three tables, copied verbatim (per-table, not the
-- dynamic DO-block form) from the loop body in
-- supabase/migrations/20260902000002_core_rls_all_tenant_policies.sql:35-44. That migration is
-- a one-shot DO block over tables that existed the day it ran; it does not reach a table
-- created later, so each new table needs this written out by hand.
ALTER TABLE campaign_period ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON campaign_period TO authenticated;
DROP POLICY IF EXISTS campaign_period_org_isolation ON campaign_period;
CREATE POLICY campaign_period_org_isolation ON campaign_period
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

ALTER TABLE campaign_period_budget_version ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON campaign_period_budget_version TO authenticated;
DROP POLICY IF EXISTS campaign_period_budget_version_org_isolation ON campaign_period_budget_version;
CREATE POLICY campaign_period_budget_version_org_isolation ON campaign_period_budget_version
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

ALTER TABLE ad_set_period_membership ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ad_set_period_membership TO authenticated;
DROP POLICY IF EXISTS ad_set_period_membership_org_isolation ON ad_set_period_membership;
CREATE POLICY ad_set_period_membership_org_isolation ON ad_set_period_membership
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
