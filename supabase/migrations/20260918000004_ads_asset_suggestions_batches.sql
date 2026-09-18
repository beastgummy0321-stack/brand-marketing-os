CREATE TABLE ads_asset_suggestion_batch (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 input_hash text NOT NULL,
 idempotency_key text NOT NULL,
 input_json jsonb NOT NULL,
 status text NOT NULL DEFAULT 'queued',
 results jsonb NOT NULL DEFAULT '[]',
 error text,
 llm_task_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,input_hash),
 UNIQUE(org_id,brand_id,campaign_id,idempotency_key),
 UNIQUE(org_id,brand_id,id),
 UNIQUE(org_id,brand_id,campaign_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id) REFERENCES ads_campaign(org_id,brand_id,id) ON DELETE CASCADE
);
CREATE TABLE ads_asset_suggestion_reservation (
 batch_id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 amount numeric NOT NULL CHECK(amount>=0),
 settlement text NOT NULL DEFAULT 'held',
 known_failed_cost numeric NOT NULL DEFAULT 0 CHECK(known_failed_cost>=0),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(org_id,brand_id,batch_id) REFERENCES ads_asset_suggestion_batch(org_id,brand_id,id) ON DELETE CASCADE
);
ALTER TABLE ads_asset_placement ADD COLUMN suggestion_batch_id text;
ALTER TABLE ads_asset_placement ADD COLUMN suggestion_input_hash text;
ALTER TABLE ads_asset_placement ADD CONSTRAINT ads_placement_suggestion_scope
 FOREIGN KEY(org_id,brand_id,campaign_id,suggestion_batch_id) REFERENCES ads_asset_suggestion_batch(org_id,brand_id,campaign_id,id);
DO $$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['ads_asset_suggestion_batch','ads_asset_suggestion_reservation'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON %I USING (org_id = current_setting(''app.org_id'',true)) WITH CHECK (org_id = current_setting(''app.org_id'',true))',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO authenticated',t);
 END LOOP;
END $$;
