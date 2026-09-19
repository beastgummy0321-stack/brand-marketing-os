-- Append-only material revisions; operation identity never substitutes for content approval.
CREATE TABLE ads_material_task (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 revision integer NOT NULL DEFAULT 1,
 created_by text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id) REFERENCES ads_campaign(org_id,brand_id,id)
);
CREATE TABLE ads_material_revision (
 task_id text NOT NULL,
 revision integer NOT NULL CHECK(revision>0),
 org_id text NOT NULL,
 brand_id text NOT NULL,
 campaign_id text NOT NULL,
 content_hash text NOT NULL,
 spec_json jsonb NOT NULL,
 pack_id text,
 dispatch_status text NOT NULL DEFAULT 'not_requested'
   CHECK(dispatch_status IN ('not_requested','prepared','queued','unknown')),
 approved_hash text,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(task_id,revision),
 FOREIGN KEY(org_id,brand_id,campaign_id,task_id)
   REFERENCES ads_material_task(org_id,brand_id,campaign_id,id) ON DELETE CASCADE
);
CREATE TABLE ads_material_operation (
 org_id text NOT NULL,
 brand_id text NOT NULL,
 operation_id text NOT NULL,
 campaign_id text NOT NULL,
 task_id text NOT NULL,
 request_hash text NOT NULL,
 result_revision integer NOT NULL,
 PRIMARY KEY(org_id,brand_id,operation_id),
 FOREIGN KEY(org_id,brand_id,campaign_id,task_id)
   REFERENCES ads_material_task(org_id,brand_id,campaign_id,id) ON DELETE CASCADE
);
ALTER TABLE ads_material_task ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_material_revision ENABLE ROW LEVEL SECURITY;
ALTER TABLE ads_material_operation ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_material_task,ads_material_revision,ads_material_operation
 TO authenticated;
CREATE POLICY ads_material_task_org ON ads_material_task FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
CREATE POLICY ads_material_revision_org ON ads_material_revision FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
CREATE POLICY ads_material_operation_org ON ads_material_operation FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
