-- Originals are canonical per brand; uploads and placement revisions preserve individual attempts.
CREATE TABLE ads_asset_upload_batch (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 created_by text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,id)
);
CREATE TABLE ads_user_asset (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 sha256 text NOT NULL,
 storage_key text NOT NULL,
 filename text NOT NULL,
 mime_type text NOT NULL,
 byte_size bigint NOT NULL CHECK(byte_size>0 AND byte_size<=52428800),
 width integer,
 height integer,
 duration numeric,
 thumbnail_key text,
 preview_key text,
 preview_mime text,
 preview_duration numeric,
 status text NOT NULL DEFAULT 'pending',
 error text,
 next_attempt_at timestamptz NOT NULL DEFAULT now(),
 preview_attempts integer NOT NULL DEFAULT 0,
    processing_started_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,sha256),
 UNIQUE(org_id,brand_id,id)
);
CREATE TABLE ads_asset_upload (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 batch_id text NOT NULL,
 ordinal integer NOT NULL CHECK(ordinal>=0 AND ordinal<10),
 filename text NOT NULL,
 expected_size bigint,
 supplied_mime text,
 copy_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'pending',
 error text,
 storage_key text,
 sha256 text,
 mime_type text,
 byte_size bigint,
 asset_id text,
 orphan_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
 updated_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(org_id,brand_id,batch_id) REFERENCES ads_asset_upload_batch(org_id,brand_id,id) ON DELETE CASCADE,
 FOREIGN KEY(org_id,brand_id,asset_id) REFERENCES ads_user_asset(org_id,brand_id,id),
 UNIQUE(batch_id,ordinal)
);
CREATE TABLE ads_asset_placement (
 id text NOT NULL,
 revision integer NOT NULL CHECK(revision>0),
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 asset_id text NOT NULL,
 is_current boolean NOT NULL DEFAULT true,
 required boolean NOT NULL DEFAULT true,
 copy_fields jsonb NOT NULL DEFAULT '{}'::jsonb,
 suggested_copy jsonb NOT NULL DEFAULT '{}'::jsonb,
 destination_entity_id text,
 purpose text,
 start_date date,
 end_date date,
 unknowns jsonb NOT NULL DEFAULT '["media_not_analyzed"]'::jsonb,
 status text NOT NULL DEFAULT 'pending',
 pending_reason text NOT NULL DEFAULT '尚未確認素材安排。',
 confirmed_by text,
 confirmed_at timestamptz,
 created_by text,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(id,revision),
 UNIQUE(org_id,brand_id,campaign_id,id,revision),
 FOREIGN KEY(org_id,brand_id,campaign_id) REFERENCES ads_campaign(org_id,brand_id,id) ON DELETE CASCADE,
 FOREIGN KEY(org_id,brand_id,asset_id) REFERENCES ads_user_asset(org_id,brand_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id,destination_entity_id)
   REFERENCES ads_external_entity(org_id,brand_id,campaign_id,id),
 CHECK(end_date IS NULL OR start_date IS NULL OR end_date>=start_date)
);
CREATE UNIQUE INDEX ads_asset_placement_current ON ads_asset_placement(org_id,brand_id,campaign_id,asset_id) WHERE is_current;

ALTER TABLE ads_asset_upload_batch ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_asset_upload_batch TO authenticated;
CREATE POLICY ads_asset_upload_batch_org_isolation ON ads_asset_upload_batch FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));

ALTER TABLE ads_user_asset ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_user_asset TO authenticated;
CREATE POLICY ads_user_asset_org_isolation ON ads_user_asset FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));

ALTER TABLE ads_asset_upload ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_asset_upload TO authenticated;
CREATE POLICY ads_asset_upload_org_isolation ON ads_asset_upload FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));

ALTER TABLE ads_asset_placement ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_asset_placement TO authenticated;
CREATE POLICY ads_asset_placement_org_isolation ON ads_asset_placement FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true)) WITH CHECK(org_id=current_setting('app.org_id',true));
