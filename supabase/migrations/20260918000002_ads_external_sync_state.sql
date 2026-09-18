-- Resumable account reads exist before any campaign has been imported.
CREATE TABLE ads_external_sync_job (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 platform text NOT NULL,
 source_account text NOT NULL,
 status text NOT NULL DEFAULT 'pending',
 tasks jsonb NOT NULL DEFAULT '{}'::jsonb,
 revision integer NOT NULL DEFAULT 0,
 last_attempt_at timestamptz,
 last_success_at timestamptz,
 error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,platform,source_account)
);
CREATE TABLE ads_external_listing (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 platform text NOT NULL,
 source_account text NOT NULL,
 native_kind text NOT NULL,
 native_id text NOT NULL,
 snapshot jsonb NOT NULL,
 observed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,platform,source_account,native_kind,native_id)
);
ALTER TABLE ads_external_sync_job ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_external_sync_job TO authenticated;
CREATE POLICY ads_external_sync_job_org_isolation ON ads_external_sync_job FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
ALTER TABLE ads_external_listing ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_external_listing TO authenticated;
CREATE POLICY ads_external_listing_org_isolation ON ads_external_listing FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));

ALTER TABLE ads_external_entity ADD COLUMN budget_raw jsonb NOT NULL DEFAULT '{}'::jsonb;
