-- supabase/migrations/20260903000006_schedule_channel_entity_map.sql
-- Module: schedule (ADR 0049). Ticket: T3a. Decision of record: ADR 0055.
--
-- ad_channel is created here rather than in T4 so that channel_entity_map's foreign key is
-- real from day one (constitution rule 3: opening a deferred feature is a switch, never a
-- migration). T4 adds the capability flags, spec, last_data_at and data_lag_days.
--
-- Per organisation, because constitution rule 2 admits no exception and the org_id gate
-- (test_org_isolation_all_tables.py:20) documents exactly two exempt tables, which may not be
-- widened. Precedent: app_setting, machine-wide settings, still org_id NOT NULL.
-- Rows are created lazily on first use (T3b), so this file seeds nothing.
CREATE TABLE ad_channel (
    id           TEXT PRIMARY KEY,                        -- adch_*
    org_id       text NOT NULL REFERENCES organisation(id),
    channel_key  TEXT NOT NULL,                           -- 'meta' | 'google' | 'tiktok'
    label        TEXT NOT NULL,
    enabled      boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, channel_key)
);
CREATE INDEX ad_channel_org_id_idx ON ad_channel(org_id);
-- id is already the primary key; this second unique exists only so other tables can carry a
-- COMPOSITE foreign key (channel_id, org_id) and have the database refuse a row whose channel
-- belongs to a different organisation. ADR 0050 uses the same device for official_asset
-- ("unique(id, brand_id) for composite FKs"). Added at T3a review, when the tables were still
-- empty: with a single-column FK, org A could reference org B's ad_channel row -- RLS still
-- hides B's data, so nothing leaks, but the reference dangles and the binding silently
-- disappears from any org-filtered join. Cheapest possible day to close it.
ALTER TABLE ad_channel ADD CONSTRAINT ad_channel_id_org_id_key UNIQUE (id, org_id);

-- The one place a tree node is tied to a live platform entity (ADR 0055 §1).
--
-- depth is GENERATED, not supplied: it is the segment count of node_key, so it cannot drift
-- from the key it describes. It is a NUMBER on the same 1-based scale as the tree's existing
-- budget_level. It must NEVER become a CHECK over ('campaign','adset','ad') -- those are
-- Meta's words for its own three levels, Google's budget level is 1 where Meta's is 2, and
-- T4's ad_channel.spec is specified to hold the level COUNT per channel (ADR 0055 §3).
-- No upper bound: a three-level cap belongs to tree.py's validation, not to the schema.
--
-- external_status holds the platform's own word, verbatim and untranslated (for Meta:
-- effective_status -- ACTIVE/PAUSED/DELETED/ARCHIVED/IN_PROCESS/WITH_ISSUES). local_state is
-- ours, and carries all three values from day one (ADR 0055 §4).
CREATE TABLE channel_entity_map (
    id                  TEXT PRIMARY KEY,                 -- cem_*
    org_id              text NOT NULL REFERENCES organisation(id),
    brand_id            TEXT NOT NULL REFERENCES brand(id),
    channel_id          TEXT NOT NULL,
    node_key            TEXT NOT NULL CHECK (node_key ~ '^[1-9][0-9]*(\.[1-9][0-9]*)*$'),
    depth               smallint GENERATED ALWAYS AS
                          (length(node_key) - length(replace(node_key, '.', '')) + 1) STORED,
    node_name_at_bind   TEXT NOT NULL,
    external_id         TEXT NOT NULL,
    external_status     TEXT,
    external_status_at  timestamptz,
    local_state         TEXT NOT NULL DEFAULT 'mapped'
                          CHECK (local_state IN ('mapped','orphaned','retired')),
    learning_reset_at   timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, brand_id, channel_id, node_key),
    -- Composite, not a single-column FK: the channel must belong to THIS row's organisation.
    FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id)
);
CREATE INDEX channel_entity_map_org_id_idx ON channel_entity_map(org_id);
CREATE INDEX channel_entity_map_brand_channel_depth_idx
    ON channel_entity_map(brand_id, channel_id, depth);

-- ad_set_period_membership -> period_node_membership (ADR 0055 §6). "Ad set" is Meta's name
-- for the level that carries the budget; on Google that level is the campaign, and ADR 0053's
-- rule was written about the budget-carrying node. Verified 2026-09-03: the table holds 0 rows
-- and has zero references anywhere outside the migration that created it, so this is a rename,
-- never a data migration.
ALTER TABLE ad_set_period_membership RENAME TO period_node_membership;
ALTER TABLE period_node_membership RENAME COLUMN ad_set_external_id TO node_key;
ALTER TABLE period_node_membership ADD COLUMN channel_id TEXT NOT NULL;
ALTER TABLE period_node_membership
    ADD CONSTRAINT period_node_membership_channel_id_org_id_fkey
    FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id);
ALTER INDEX ad_set_period_membership_org_id_idx RENAME TO period_node_membership_org_id_idx;
ALTER INDEX idx_aspm_brand_id  RENAME TO idx_pnm_brand_id;
ALTER INDEX idx_aspm_period_id RENAME TO idx_pnm_period_id;
-- A RENAME TO leaves every constraint carrying the old table's name, so a later reader greps
-- for a table that no longer exists and finds it. Rename them with the table.
ALTER TABLE period_node_membership
    RENAME CONSTRAINT ad_set_period_membership_pkey TO period_node_membership_pkey;
ALTER TABLE period_node_membership
    RENAME CONSTRAINT ad_set_period_membership_org_id_fkey
    TO period_node_membership_org_id_fkey;
ALTER TABLE period_node_membership
    RENAME CONSTRAINT ad_set_period_membership_campaign_period_id_fkey
    TO period_node_membership_campaign_period_id_fkey;
ALTER POLICY ad_set_period_membership_org_isolation ON period_node_membership
    RENAME TO period_node_membership_org_isolation;

-- RLS + grants + policy for the two NEW tables, written out per table. Copy the exact shape
-- from supabase/migrations/20260903000001_schedule_campaign_period.sql (its own tail explains
-- why the one-shot DO block in 20260902000002 does not reach a table created later).
ALTER TABLE ad_channel ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ad_channel TO authenticated;
DROP POLICY IF EXISTS ad_channel_org_isolation ON ad_channel;
CREATE POLICY ad_channel_org_isolation ON ad_channel
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

ALTER TABLE channel_entity_map ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON channel_entity_map TO authenticated;
DROP POLICY IF EXISTS channel_entity_map_org_isolation ON channel_entity_map;
CREATE POLICY channel_entity_map_org_isolation ON channel_entity_map
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
