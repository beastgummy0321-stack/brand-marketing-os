-- Monitoring is opt-in per native ad; pausing it does not stop source collection.
ALTER TABLE ads_review_round ADD COLUMN recovery_checked_at timestamptz;
ALTER TABLE ads_handoff_item ADD COLUMN review_monitor_checked_at timestamptz;
CREATE TABLE ads_review_monitor (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 entity_id text NOT NULL,
 enabled boolean NOT NULL DEFAULT true,
 window_days integer NOT NULL DEFAULT 7 CHECK(window_days BETWEEN 1 AND 31),
 cadence_days integer NOT NULL DEFAULT 7 CHECK(cadence_days BETWEEN 1 AND 31),
 window_start date,
 window_end date,
 previous_id text,
 review_id text,
 state text NOT NULL DEFAULT 'scheduled' CHECK(state IN
  ('scheduled','waiting','queued','running','ready','needs_attention','paused')),
 next_check_at timestamptz,
 last_checked_at timestamptz,
 last_input_hash text,
 reason text,
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 observe_after timestamptz,
 source_handoff_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,entity_id),
 FOREIGN KEY(org_id,brand_id,campaign_id,entity_id)
  REFERENCES ads_external_entity(org_id,brand_id,campaign_id,id) ON DELETE CASCADE,
 FOREIGN KEY(org_id,brand_id,campaign_id,previous_id)
  REFERENCES ads_review_round(org_id,brand_id,campaign_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id,review_id)
  REFERENCES ads_review_round(org_id,brand_id,campaign_id,id),
 FOREIGN KEY(org_id,brand_id,campaign_id,source_handoff_id)
  REFERENCES ads_handoff_item(org_id,brand_id,campaign_id,id),
 CHECK((window_start IS NULL AND window_end IS NULL)
  OR (window_start IS NOT NULL AND window_end>=window_start))
);
CREATE INDEX ads_review_monitor_due_idx ON ads_review_monitor(next_check_at,id) WHERE enabled;
ALTER TABLE ads_review_monitor ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_review_monitor TO authenticated;
CREATE POLICY ads_review_monitor_org_isolation ON ads_review_monitor FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true))
 WITH CHECK(org_id=current_setting('app.org_id',true));
