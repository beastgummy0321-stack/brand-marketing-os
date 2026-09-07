-- supabase/migrations/20260908000001_schedule_period_node_result.sql
-- Module: schedule (ADR 0049). Ticket: smart-loop 01. ADR 0066.
--
-- Settling a period scores every bound ad-set (depth 2, carries the approved share) and ad
-- (depth 3, carries the seven coordinate keys) node against the break-even line (ADR 0066
-- rule 2). Depth 1 (one campaign, no share, no coordinates) is never scored. A resettle
-- deletes and rewrites the whole set for that period (ADR 0066 rule 1) -- no ON DELETE
-- CASCADE is needed for that path; app/schedule/repository.py's replace_period_node_results()
-- does it in one transaction.
--
-- The composite FK mirrors 20260905000002_schedule_campaign_period_composite_fk.sql: a single-
-- column FK would let one organisation's row reference another organisation's campaign_period.
CREATE TABLE period_node_result (
    id TEXT PRIMARY KEY,                                   -- pnr_*, via db.new_id("pnr")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_period_id TEXT NOT NULL,
    source_tree_task_id TEXT NOT NULL,                     -- the tree whose bindings were scored
    channel_id TEXT NOT NULL REFERENCES ad_channel(id),
    node_key TEXT NOT NULL,
    depth SMALLINT NOT NULL CHECK (depth IN (2, 3)),                -- 2 = ad set (carries share), 3 = ad (carries coordinates); depth 1 is one campaign, nothing to score
    node_name TEXT NOT NULL,                               -- node_name_at_bind
    external_id TEXT NOT NULL,                             -- the Meta object the node was bound to
    approved_share numeric(6,4),                           -- NULL on a depth that carries no share
    approved_daily_amount numeric(14,2),                   -- NULL on a depth that carries no share
    actual_spend numeric(14,2) NOT NULL,
    revenue_tracked numeric(14,2),                         -- NULL when no day tracked a ROAS
    roas_conservative numeric(10,4),                       -- revenue_tracked / actual_spend
    roas_optimistic numeric(10,4),                         -- revenue_tracked / spend on tracked days
    roas_coverage numeric(5,4) NOT NULL,                   -- tracked rows / rows
    breakeven_roas numeric(10,4),                          -- diagnosis.breakeven_roas() at settle; NULL = none
    breakeven_source TEXT NOT NULL,                        -- the source string breakeven_roas() returns, verbatim
    verdict TEXT NOT NULL CHECK (verdict IN ('win','lose','unclear')),
    coordinates_json jsonb,                                -- depth 3 only: the seven *_key values
    settled_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id),
    UNIQUE (org_id, brand_id, campaign_period_id, channel_id, node_key)
);
CREATE INDEX period_node_result_org_id_idx ON period_node_result(org_id);
CREATE INDEX period_node_result_brand_period_idx ON period_node_result(brand_id, campaign_period_id);

-- RLS + grants + org-isolation policy, copied verbatim (per-table shape, ADR 0052) from
-- supabase/migrations/20260903000001_schedule_campaign_period.sql:82-88.
ALTER TABLE period_node_result ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON period_node_result TO authenticated;
DROP POLICY IF EXISTS period_node_result_org_isolation ON period_node_result;
CREATE POLICY period_node_result_org_isolation ON period_node_result
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
