-- supabase/migrations/20260829000004_meta_daily_spend.sql
-- Module: meta (ticket 05, .scratch/schedule-module/issues/05-daily-spend-pull-and-display.md)
-- Rule: migration files only CREATE tables prefixed/owned by this module. This file also
-- ALTERs meta_ad_account, which this module already owns (created in
-- 20260829000002_meta_baseline.sql) -- altering your own module's existing table is not a
-- new CREATE and is not subject to the ownership registry.

-- "Last successful pull" per account, not per attempt: only a successful pull updates this
-- column (app/meta/repository.py mark_pull_succeeded()), so a failed pull leaves the previous
-- numbers on screen and this timestamp tells the user how stale they are.
ALTER TABLE meta_ad_account ADD COLUMN last_pull_at timestamptz;

-- Per account, per campaign, per day -- never a rolling total. The unique index is the whole
-- re-run-safety mechanism: upserting on (ad_account_id, campaign_id, spend_date) makes a
-- second pull for the same day overwrite, not duplicate.
--
-- org_id + ad_account_id, not brand_id: an account can be bound to more than one brand
-- (brand_meta_ad_account is m:n), so a spend row cannot honestly belong to a single brand.
-- roas is nullable and stays nullable forever -- NULL means 未追蹤 (untracked), never 0.
CREATE TABLE meta_campaign_spend (
  id            text PRIMARY KEY,       -- new_id("mcs")
  org_id        text NOT NULL REFERENCES organisation(id),
  ad_account_id text NOT NULL REFERENCES meta_ad_account(id) ON DELETE CASCADE,
  campaign_id   text NOT NULL,          -- Graph API campaign_id
  campaign_name text NOT NULL,
  spend_date    date NOT NULL,
  spend         numeric(14,2) NOT NULL,
  impressions   bigint NOT NULL,
  clicks        bigint NOT NULL,
  roas          numeric(10,4),          -- NULL = 未追蹤, never 0
  pulled_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX meta_campaign_spend_org_id_idx ON meta_campaign_spend(org_id);
CREATE UNIQUE INDEX meta_campaign_spend_account_campaign_date_idx
  ON meta_campaign_spend(ad_account_id, campaign_id, spend_date);

ALTER TABLE meta_campaign_spend ENABLE ROW LEVEL SECURITY;
