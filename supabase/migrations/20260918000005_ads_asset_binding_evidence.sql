CREATE TABLE ads_asset_binding (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 placement_id text NOT NULL,
 placement_revision integer NOT NULL,
 entity_id text,
 platform text,
 source_account text,
 native_kind text,
 native_id text,
 existence_status text NOT NULL DEFAULT 'self_reported',
 evidence_level text NOT NULL DEFAULT 'unknown',
 reported_at timestamptz,
 reported_by text,
 user_verified_at timestamptz,
 user_verified_by text,
 first_verified_at timestamptz,
 last_verified_at timestamptz,
 last_attempt_at timestamptz,
 verified_by text,
 creative_snapshot jsonb NOT NULL DEFAULT '{}',
 creative_hash text,
 media_equivalence jsonb NOT NULL DEFAULT '{}',
 continuous_intervals jsonb NOT NULL DEFAULT '[]',
 timezone_name text,
 valid_from timestamptz NOT NULL DEFAULT now(),
 valid_to timestamptz,
 stale_reason text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,id),
 CHECK(valid_to IS NULL OR valid_to>=valid_from),
 FOREIGN KEY(org_id,brand_id,campaign_id,placement_id,placement_revision)
  REFERENCES ads_asset_placement(org_id,brand_id,campaign_id,id,revision),
 FOREIGN KEY(org_id,brand_id,campaign_id,entity_id)
  REFERENCES ads_external_entity(org_id,brand_id,campaign_id,id)
);
ALTER TABLE ads_external_daily ADD CONSTRAINT ads_external_daily_scope_id UNIQUE(org_id,brand_id,campaign_id,id);
CREATE TABLE ads_asset_observation_claim (
 observation_id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 binding_id text NOT NULL,
 FOREIGN KEY(org_id,brand_id,campaign_id,observation_id) REFERENCES ads_external_daily(org_id,brand_id,campaign_id,id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(org_id,brand_id,campaign_id,binding_id)
  REFERENCES ads_asset_binding(org_id,brand_id,campaign_id,id)
);
CREATE FUNCTION ads_binding_no_overlap() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.existence_status='platform_confirmed' THEN
  IF NEW.platform IS NULL OR NEW.source_account IS NULL OR NEW.native_kind IS NULL OR NEW.native_id IS NULL THEN
   RAISE EXCEPTION 'binding_native_scope_required' USING ERRCODE='23514';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('ads-binding:'||NEW.org_id||':'||NEW.platform||':'||NEW.source_account||':'||NEW.native_kind||':'||NEW.native_id,0));
  IF EXISTS(SELECT 1 FROM ads_asset_binding b WHERE b.id<>NEW.id AND b.org_id=NEW.org_id
   AND b.platform=NEW.platform AND b.source_account=NEW.source_account AND b.native_kind=NEW.native_kind AND b.native_id=NEW.native_id
   AND b.existence_status='platform_confirmed'
   AND tstzrange(b.valid_from,b.valid_to,'[)') && tstzrange(NEW.valid_from,NEW.valid_to,'[)')) THEN
   RAISE EXCEPTION 'binding_interval_overlap' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ads_binding_no_overlap BEFORE INSERT OR UPDATE ON ads_asset_binding
 FOR EACH ROW EXECUTE FUNCTION ads_binding_no_overlap();
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['ads_asset_binding','ads_asset_observation_claim'] LOOP
  EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY tenant_scope ON %I USING (org_id=current_setting(''app.org_id'',true)) WITH CHECK (org_id=current_setting(''app.org_id'',true))',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON %I TO authenticated',t);
 END LOOP;
END $$;
