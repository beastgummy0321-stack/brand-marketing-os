-- Local approval and evidence only. No platform mutation is authorized by these rows.
CREATE TABLE ads_change_set (
    id text PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    campaign_id text NOT NULL,
    operation_id text NOT NULL,
    request_hash text NOT NULL,
    content_hash text NOT NULL,
    title text NOT NULL,
    month text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','approved','rejected','deferred','superseded')),
    plan_json jsonb NOT NULL,
    approval_id text REFERENCES approval(id),
    decision_reason text,
    revisit_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    FOREIGN KEY (org_id,brand_id,campaign_id)
        REFERENCES ads_campaign(org_id,brand_id,id) ON DELETE CASCADE,
    UNIQUE (org_id,brand_id,operation_id),
    UNIQUE (org_id,brand_id,campaign_id,id)
);
CREATE INDEX ads_change_set_brand_idx ON ads_change_set(org_id,brand_id,campaign_id);
ALTER TABLE ads_change_set ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON ads_change_set TO authenticated;
CREATE POLICY ads_change_set_org_isolation ON ads_change_set FOR ALL TO authenticated
    USING (org_id=current_setting('app.org_id',true))
    WITH CHECK (org_id=current_setting('app.org_id',true));

ALTER TABLE ads_action ADD COLUMN change_set_id text;
ALTER TABLE ads_action ADD COLUMN verification_state text NOT NULL DEFAULT 'legacy'
    CHECK (verification_state IN ('legacy','pending','reported','confirmed','deviated','unknown','stale'));
ALTER TABLE ads_action ADD COLUMN evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ads_action ADD COLUMN reported_at timestamptz;
ALTER TABLE ads_action ADD COLUMN first_observed_at timestamptz;
ALTER TABLE ads_action ADD COLUMN verified_at timestamptz;
ALTER TABLE ads_action ADD CONSTRAINT ads_action_change_set_scope_fk
    FOREIGN KEY (org_id,brand_id,campaign_id,change_set_id)
    REFERENCES ads_change_set(org_id,brand_id,campaign_id,id) ON DELETE CASCADE;
CREATE INDEX ads_action_change_set_idx ON ads_action(change_set_id);
