-- supabase/migrations/20260830000004_meta_entity_spend.sql
-- Module: meta (ticket S1, .scratch/adloop/issues/S1-three-level-performance.md)
-- Rule: migration files only CREATE tables prefixed/owned by this module. This file also
-- DROPs meta_campaign_spend, which this module already owns (created in
-- 20260829000004_meta_daily_spend.sql) -- dropping your own module's table is not a CREATE
-- and is not subject to the ownership registry (test_migration_ownership.py only inspects
-- CREATE TABLE statements).

-- meta_entity_spend replaces meta_campaign_spend: campaign, adset AND ad level rows now
-- share one table (SPEC 2.4, GRILL decision 1 / C4). `level` is NOT NULL with no default on
-- purpose -- a WHERE clause can be forgotten, a NOT NULL column cannot. Mixing three levels
-- into one aggregate would triple every money total, so the column exists precisely to make
-- that mistake structurally visible instead of a silent 3x.
--
-- Existing meta_campaign_spend rows are test data (CLAUDE.md 資料狀態) -- this is a replace,
-- not a backfill. org_id + ad_account_id, not brand_id: an account can be bound to more than
-- one brand (brand_meta_ad_account is m:n), so a spend row cannot honestly belong to a single
-- brand. roas is nullable and stays nullable forever -- NULL means 未追蹤 (untracked), never 0.
CREATE TABLE meta_entity_spend (
  id                  text PRIMARY KEY,       -- new_id("mes")
  org_id              text NOT NULL REFERENCES organisation(id),
  ad_account_id       text NOT NULL REFERENCES meta_ad_account(id) ON DELETE CASCADE,
  level               text NOT NULL,          -- campaign | adset | ad
  entity_id           text NOT NULL,          -- the id at THIS row's level
  entity_name         text NOT NULL,
  campaign_id         text NOT NULL,          -- present at every level
  adset_id            text,                   -- NULL at campaign level
  ad_id               text,                   -- NULL at campaign and adset level
  spend_date          date NOT NULL,
  spend               numeric(14,2) NOT NULL,
  impressions         bigint NOT NULL,
  clicks              bigint NOT NULL,
  roas                numeric(10,4),          -- NULL = 未追蹤, never 0
  actions             jsonb,                  -- Meta's raw actions array, unparsed (ADR 0036)
  action_values       jsonb,                  -- Meta's raw action_values array, unparsed
  attribution_window  text NOT NULL,          -- what action_attribution_windows was SENT,
                                               -- e.g. '7d_click,1d_view' -- never what the API
                                               -- defaulted to (SPEC 7.4(d))
  pulled_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX meta_entity_spend_org_id_idx ON meta_entity_spend(org_id);
CREATE UNIQUE INDEX meta_entity_spend_account_level_entity_date_idx
  ON meta_entity_spend(ad_account_id, level, entity_id, spend_date);

ALTER TABLE meta_entity_spend ENABLE ROW LEVEL SECURITY;

-- Same policy shape as meta_campaign_spend had: RLS on, zero policies. Backend connects as
-- postgres (bypasses RLS); RLS exists only to close anon/authenticated access through
-- PostgREST (test_real_db_schema_drift.py Gate D).

DROP TABLE meta_campaign_spend;
