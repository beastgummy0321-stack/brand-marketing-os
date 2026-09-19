-- A review is an observation and a human decision, never campaign closure.
CREATE TABLE ads_review_round (
 id text PRIMARY KEY,
 org_id text NOT NULL REFERENCES organisation(id),
 brand_id text NOT NULL REFERENCES brand(id),
 campaign_id text NOT NULL,
 entity_id text NOT NULL,
 previous_id text,
 window_start date NOT NULL,
 window_end date NOT NULL,
 evidence_json jsonb NOT NULL,
 evidence_hash text NOT NULL,
 result_json jsonb NOT NULL DEFAULT '{}',
 llm_task_id text REFERENCES llm_task(id),
 status text NOT NULL CHECK(status IN
  ('waiting','queued','running','ready','completed','deferred','unjudgeable','failed','unknown')),
 decision text CHECK(decision IN ('completed','deferred','unjudgeable')),
 reason text,
 revisit_at timestamptz,
 error text,
 reserved_amount numeric NOT NULL DEFAULT 0,
 reservation_state text NOT NULL DEFAULT 'held' CHECK(reservation_state IN ('held','settled')),
 failed_cost numeric NOT NULL DEFAULT 0,
 created_by text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,brand_id,campaign_id,id),
 UNIQUE(org_id,brand_id,campaign_id,evidence_hash),
 FOREIGN KEY(org_id,brand_id,campaign_id,entity_id)
  REFERENCES ads_external_entity(org_id,brand_id,campaign_id,id) ON DELETE CASCADE,
 FOREIGN KEY(org_id,brand_id,campaign_id,previous_id)
  REFERENCES ads_review_round(org_id,brand_id,campaign_id,id),
 CHECK(window_end>=window_start)
);
CREATE INDEX ads_review_round_pending_idx ON ads_review_round(status,updated_at);
ALTER TABLE ads_review_round ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_review_round TO authenticated;
CREATE POLICY ads_review_round_org_isolation ON ads_review_round FOR ALL TO authenticated
 USING(org_id=current_setting('app.org_id',true))
 WITH CHECK(org_id=current_setting('app.org_id',true));
