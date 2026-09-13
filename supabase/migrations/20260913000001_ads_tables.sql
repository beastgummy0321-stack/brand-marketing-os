-- supabase/migrations/20260913000001_ads_tables.sql
-- Module: ads (F03-I01, ARCHITECTURE.md §0/§2/§3/§4/§6). Five tables for the Campaign object
-- and its delivery plan/action/outcome trail (投放中心 golden path: goal -> strategy -> delivery
-- plan -> pack -> artifacts -> publish + bind -> outcome -> verdict -> learning). Only ads_*
-- tables -- no other module's table is created or altered here.
--
-- Binding lives on the row (campaign, delivery_group, ad all three): external_id/external_name/
-- external_status/local_state/bound_at, because Meta's lookups are hierarchical (campaign bound
-- first, then group, then ad -- 逐節點 from the top). channel_entity_map belongs to schedule and
-- is not read or written by ads.
--
-- The 通路 level is a column (channel_key) on ads_delivery_group, not a table -- no platform is
-- hard-coded anywhere in this schema.

CREATE TABLE ads_campaign (
    id TEXT PRIMARY KEY,                       -- adc_*, via db.new_id("adc")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    name TEXT NOT NULL,
    goal_text TEXT NOT NULL,                   -- 為什麼做這個 Campaign（使用者的那句話）
    objective TEXT NOT NULL,                   -- 我們自己的詞彙，不綁平台原生目標名
    success_metric TEXT NOT NULL CHECK (success_metric IN ('cpa', 'roas', 'purchases')),
    success_target numeric NOT NULL,
    success_basis TEXT,                        -- 目標值的依據（一句話）
    start_date date,
    end_date date,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'live', 'ended', 'closed')),
    -- 預算：budget_planned 是採用的情境金額，寫入後永不重算；畫面上的合計是
    -- sum(ads_delivery_group.daily_budget) x 天數，在 repository.py 一處推導。
    budget_planned numeric,
    budget_scenario TEXT,
    budget_basis_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- 綁定四欄：campaign 節點最先綁（Meta 的查找是階層式的）。
    external_id TEXT,
    external_name TEXT,
    external_status TEXT,
    local_state TEXT NOT NULL DEFAULT 'unbound'
        CHECK (local_state IN ('unbound', 'bound', 'detached', 'retired')),
    bound_at timestamptz,
    context_json jsonb NOT NULL DEFAULT '{}'::jsonb,      -- 草案取材的 brand/product/learning ids
    constraints_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    verdict TEXT,
    verdict_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    closed_at timestamptz,
    created_by TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ads_campaign_org_id_idx ON ads_campaign(org_id);
CREATE INDEX idx_ads_campaign_brand_id ON ads_campaign(brand_id);

ALTER TABLE ads_campaign ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_campaign TO authenticated;
DROP POLICY IF EXISTS ads_campaign_org_isolation ON ads_campaign;
CREATE POLICY ads_campaign_org_isolation ON ads_campaign
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));


CREATE TABLE ads_delivery_group (
    id TEXT PRIMARY KEY,                       -- adg_*, via db.new_id("adg")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_id TEXT NOT NULL REFERENCES ads_campaign(id) ON DELETE CASCADE,
    channel_key TEXT NOT NULL,                 -- 'meta' / 'google_ads' / 'tiktok' / ... 沒有平台專屬欄位
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('new', 'retarget', 'explore')),
    daily_budget numeric NOT NULL,
    start_date date,
    end_date date,
    external_id TEXT,
    external_name TEXT,
    external_status TEXT,
    local_state TEXT NOT NULL DEFAULT 'unbound'
        CHECK (local_state IN ('unbound', 'bound', 'detached', 'retired')),
    bound_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ads_delivery_group_org_id_idx ON ads_delivery_group(org_id);
CREATE INDEX idx_ads_delivery_group_brand_id ON ads_delivery_group(brand_id);
CREATE INDEX idx_ads_delivery_group_campaign_id ON ads_delivery_group(campaign_id);

ALTER TABLE ads_delivery_group ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_delivery_group TO authenticated;
DROP POLICY IF EXISTS ads_delivery_group_org_isolation ON ads_delivery_group;
CREATE POLICY ads_delivery_group_org_isolation ON ads_delivery_group
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));


CREATE TABLE ads_ad (
    id TEXT PRIMARY KEY,                       -- ada_*, via db.new_id("ada")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_id TEXT NOT NULL REFERENCES ads_campaign(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES ads_delivery_group(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                        -- 追蹤名稱
    -- 七維座標（沿用 brand_coordinate 的詞彙，ADR 0050），沒有預算欄——預算只到投放組層。
    audience_key TEXT,
    pain_key TEXT,
    angle_key TEXT,
    hook_key TEXT,
    proof_key TEXT,
    offer_key TEXT,
    format_key TEXT,
    coordinates_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    product_id TEXT REFERENCES product(id),
    external_id TEXT,
    external_name TEXT,
    external_status TEXT,
    local_state TEXT NOT NULL DEFAULT 'unbound'
        CHECK (local_state IN ('unbound', 'bound', 'detached', 'retired')),
    bound_at timestamptz,
    asset_ready_source TEXT CHECK (asset_ready_source IN ('workbench', 'manual')),
    asset_ready_by TEXT,
    asset_ready_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ads_ad_org_id_idx ON ads_ad(org_id);
CREATE INDEX idx_ads_ad_brand_id ON ads_ad(brand_id);
CREATE INDEX idx_ads_ad_campaign_id ON ads_ad(campaign_id);
CREATE INDEX idx_ads_ad_group_id ON ads_ad(group_id);

ALTER TABLE ads_ad ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_ad TO authenticated;
DROP POLICY IF EXISTS ads_ad_org_isolation ON ads_ad;
CREATE POLICY ads_ad_org_isolation ON ads_ad
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));


CREATE TABLE ads_action (
    id TEXT PRIMARY KEY,                       -- adx_*, via db.new_id("adx")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_id TEXT NOT NULL REFERENCES ads_campaign(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('campaign', 'group', 'ad')),
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('publish', 'bind', 'budget', 'date', 'pause', 'creative')),
    before_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    after_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    approved_by TEXT,
    approved_at timestamptz,
    sync_state TEXT NOT NULL DEFAULT 'pending_manual'
        CHECK (sync_state IN ('pending_manual', 'confirmed_manual', 'auto_synced')),
    platform_ref TEXT,
    reverses_action_id TEXT REFERENCES ads_action(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ads_action_org_id_idx ON ads_action(org_id);
CREATE INDEX idx_ads_action_brand_id ON ads_action(brand_id);
CREATE INDEX idx_ads_action_campaign_id ON ads_action(campaign_id);

ALTER TABLE ads_action ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_action TO authenticated;
DROP POLICY IF EXISTS ads_action_org_isolation ON ads_action;
CREATE POLICY ads_action_org_isolation ON ads_action
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));


CREATE TABLE ads_outcome_daily (
    id TEXT PRIMARY KEY,                       -- ado_*, via db.new_id("ado")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_id TEXT NOT NULL REFERENCES ads_campaign(id) ON DELETE CASCADE,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('group', 'ad')),
    entity_id TEXT NOT NULL,
    day date NOT NULL,
    spend numeric NOT NULL DEFAULT 0,
    impressions integer NOT NULL DEFAULT 0,
    clicks integer NOT NULL DEFAULT 0,
    purchases integer NOT NULL DEFAULT 0,
    revenue numeric NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'TWD',
    source TEXT NOT NULL CHECK (source IN ('meta', 'simulated')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_kind, entity_id, day)
);
CREATE INDEX ads_outcome_daily_org_id_idx ON ads_outcome_daily(org_id);
CREATE INDEX idx_ads_outcome_daily_brand_id ON ads_outcome_daily(brand_id);
CREATE INDEX idx_ads_outcome_daily_campaign_id ON ads_outcome_daily(campaign_id);

ALTER TABLE ads_outcome_daily ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_outcome_daily TO authenticated;
DROP POLICY IF EXISTS ads_outcome_daily_org_isolation ON ads_outcome_daily;
CREATE POLICY ads_outcome_daily_org_isolation ON ads_outcome_daily
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
