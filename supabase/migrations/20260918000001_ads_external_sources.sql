-- Native read-only source records, separate from the internal delivery plan.
ALTER TABLE ads_campaign ADD COLUMN origin text NOT NULL DEFAULT 'internal'
    CHECK (origin IN ('internal', 'imported'));
ALTER TABLE ads_campaign ALTER COLUMN goal_text DROP NOT NULL;
ALTER TABLE ads_campaign ALTER COLUMN objective DROP NOT NULL;
ALTER TABLE ads_campaign ALTER COLUMN success_metric DROP NOT NULL;
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_internal_required
    CHECK (origin = 'imported' OR (goal_text IS NOT NULL AND objective IS NOT NULL
                                  AND success_metric IS NOT NULL));
ALTER TABLE ads_campaign ADD CONSTRAINT ads_campaign_tenant_key UNIQUE (org_id, brand_id, id);

CREATE TABLE ads_external_entity (
    id text PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    campaign_id text NOT NULL,
    platform text NOT NULL,
    source_account text NOT NULL,
    native_kind text NOT NULL,
    native_id text NOT NULL,
    parent_native_kind text,
    parent_native_id text,
    native_label text,
    name text,
    objective text,
    native_status text,
    start_date date,
    end_date date,
    budget_type text NOT NULL DEFAULT 'unknown' CHECK (budget_type IN ('daily','lifetime','unknown')),
    budget_amount numeric,
    currency text,
    budget_source text,
    availability jsonb NOT NULL DEFAULT '{}'::jsonb,
    creative jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_success_at timestamptz,
    last_attempt_at timestamptz,
    sync_status text NOT NULL DEFAULT 'unknown',
    sync_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, brand_id, platform, source_account, native_kind, native_id),
    UNIQUE (org_id, brand_id, campaign_id, platform, source_account, native_kind, native_id),
    UNIQUE (org_id, brand_id, campaign_id, id),
    FOREIGN KEY (org_id, brand_id, campaign_id) REFERENCES ads_campaign(org_id, brand_id, id) ON DELETE CASCADE,
    CHECK ((parent_native_kind IS NULL) = (parent_native_id IS NULL)),
    CHECK (parent_native_id IS NULL OR (parent_native_kind, parent_native_id) <> (native_kind, native_id)),
    FOREIGN KEY (org_id, brand_id, campaign_id, platform, source_account, parent_native_kind, parent_native_id)
        REFERENCES ads_external_entity(org_id, brand_id, campaign_id, platform, source_account, native_kind, native_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX ads_external_entity_campaign_idx ON ads_external_entity(org_id, brand_id, campaign_id);

CREATE TABLE ads_external_daily (
    id text PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    campaign_id text NOT NULL,
    entity_id text NOT NULL,
    day date NOT NULL,
    metric_scope text NOT NULL,
    attribution_key text NOT NULL,
    currency text,
    spend numeric,
    impressions bigint,
    clicks bigint,
    purchases numeric,
    revenue numeric,
    availability jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (org_id, brand_id, campaign_id, entity_id)
        REFERENCES ads_external_entity(org_id, brand_id, campaign_id, id) ON DELETE CASCADE,
    UNIQUE NULLS NOT DISTINCT (org_id, brand_id, entity_id, day, metric_scope, attribution_key, currency)
);
CREATE INDEX ads_external_daily_campaign_idx ON ads_external_daily(org_id, brand_id, campaign_id);

ALTER TABLE ads_external_entity ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_external_entity TO authenticated;
CREATE POLICY ads_external_entity_org_isolation ON ads_external_entity FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
ALTER TABLE ads_external_daily ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_external_daily TO authenticated;
CREATE POLICY ads_external_daily_org_isolation ON ads_external_daily FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

-- Deferred so a complete page can insert parents and children in either order.
CREATE FUNCTION ads_external_acyclic() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE ancestors AS (
            SELECT e.id, e.parent_native_kind, e.parent_native_id, ARRAY[e.id] AS path, false AS cycle
            FROM ads_external_entity e WHERE e.id = NEW.id
            UNION ALL
            SELECT p.id, p.parent_native_kind, p.parent_native_id,
                   a.path || p.id, p.id = ANY(a.path)
            FROM ancestors a JOIN ads_external_entity p
              ON p.org_id=NEW.org_id AND p.brand_id=NEW.brand_id AND p.campaign_id=NEW.campaign_id
             AND p.platform=NEW.platform AND p.source_account=NEW.source_account
             AND p.native_kind=a.parent_native_kind AND p.native_id=a.parent_native_id
            WHERE NOT a.cycle
        ) SELECT 1 FROM ancestors WHERE cycle
    ) THEN
        RAISE EXCEPTION 'external_parent_cycle' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER ads_external_parent_acyclic
    AFTER INSERT OR UPDATE ON ads_external_entity DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ads_external_acyclic();
