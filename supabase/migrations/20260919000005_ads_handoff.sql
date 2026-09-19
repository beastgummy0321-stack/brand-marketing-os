-- Per-node readback of an approved manual handoff; native identities stay in external_entity.
CREATE TABLE ads_handoff_item (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 change_set_id text NOT NULL,
 action_id text NOT NULL REFERENCES ads_action(id) ON DELETE CASCADE,
 planned_kind text NOT NULL CHECK(planned_kind IN ('campaign','group','ad')),
 planned_id text NOT NULL,
 name text NOT NULL,
 parent_item_id text REFERENCES ads_handoff_item(id) ON DELETE CASCADE,
 placement_id text,
 placement_revision integer,
 expected_json jsonb NOT NULL,
 entity_id text,
 status text NOT NULL DEFAULT 'pending'
  CHECK(status IN ('pending','reported','confirmed','deviated','unknown','stale')),
 evidence_json jsonb NOT NULL DEFAULT '{}',
 attempt_id text,
 reported_at timestamptz,
 observed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,id),
 UNIQUE(org_id,brand_id,campaign_id,change_set_id,planned_kind,planned_id),
 FOREIGN KEY(org_id,brand_id,campaign_id,change_set_id)
  REFERENCES ads_change_set(org_id,brand_id,campaign_id,id) ON DELETE CASCADE,
 FOREIGN KEY(org_id,brand_id,campaign_id,entity_id)
  REFERENCES ads_external_entity(org_id,brand_id,campaign_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id,placement_id,placement_revision)
  REFERENCES ads_asset_placement(org_id,brand_id,campaign_id,id,revision)
);
CREATE UNIQUE INDEX ads_handoff_identity_idx ON ads_handoff_item(org_id,entity_id)
 WHERE entity_id IS NOT NULL;
ALTER TABLE ads_handoff_item ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_handoff_item TO authenticated;
CREATE POLICY ads_handoff_org_isolation ON ads_handoff_item FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true))
 WITH CHECK(org_id=current_setting('app.org_id',true));
