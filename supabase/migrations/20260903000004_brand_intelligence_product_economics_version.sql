-- supabase/migrations/20260903000004_brand_intelligence_product_economics_version.sql
-- Module: brand_intelligence (ADR 0049 -- migration files take the prefix of the module that
-- owns the table). Ticket T2c (docs/issues/t2c-product-cost-versions/ticket.md). Decisions:
-- ADR 0053 sections 5 and 7, ADR 0049, ADR 0027.
--
-- A product cost change applies from today, never backwards (ADR 0053 section 5): this table
-- is append-only with a half-open interval [effective_from, effective_to). The partial unique
-- index below is the whole overlap guard -- with back-dating rejected, the only reachable
-- overlap is two open versions for one product, so no `CREATE EXTENSION btree_gist` and no
-- EXCLUDE constraint (that migration comes back only if back-dating is ever opened).

CREATE TABLE product_economics_version (
    id TEXT PRIMARY KEY,                       -- pev_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT NOT NULL REFERENCES product(id),
    version INTEGER NOT NULL,
    selling_price numeric(14,2) NOT NULL,
    fixed_cost numeric(14,2),
    unit_variable_cost numeric(14,2),
    shipping_cost numeric(14,2),
    currency TEXT NOT NULL,
    effective_from date NOT NULL,
    effective_to date,                          -- NULL = the open version; half-open [from, to)
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_pev_open_per_product
    ON product_economics_version(product_id) WHERE effective_to IS NULL;

-- RLS + grants + org-isolation policy, copied verbatim (per-table, not the dynamic DO-block
-- form) from the loop body in supabase/migrations/20260902000002_core_rls_all_tenant_policies.sql:35-44.
-- That migration is a one-shot DO block over tables that existed the day it ran; it does not
-- reach a table created later, so this table needs it written out by hand (worked example:
-- 20260903000001_schedule_campaign_period.sql).
ALTER TABLE product_economics_version ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON product_economics_version TO authenticated;
DROP POLICY IF EXISTS product_economics_version_org_isolation ON product_economics_version;
CREATE POLICY product_economics_version_org_isolation ON product_economics_version
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

-- ADR 0053 section 7: cpa_roas_basis is free text, read by no code and no prompt.
ALTER TABLE product_economics DROP COLUMN cpa_roas_basis;
