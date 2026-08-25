-- supabase/migrations/20260826000004_ads_baseline.sql
-- Module: ads
-- Generated from app/ads/migrations 0001..0020 on 2026-08-26 (ADR 0027 rebaseline).
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- Notes on the 6 DROP/RENAME statements applied to this model:
--   - 0007_retire_cycle_reminder.sql: DROP TABLE cycle_reminder — not created here.
--   - 0020_publishing_package_no_variant_fk.sql: rebuilds publishing_package (stash table,
--     DROP TABLE publishing_package, CREATE publishing_package_new, RENAME to publishing_package,
--     DROP the stash table) to drop the FK on hook_id/script_id/copy_variant_id. Final shape only
--     is represented below (plain text columns, no REFERENCES creative_variant).
-- learning_ledger is NOT created here — see brand_intelligence baseline file header.

CREATE TABLE ad_account (
    id TEXT PRIMARY KEY,                    -- adc_*
    org_id text NOT NULL REFERENCES organisation(id),
    platform TEXT NOT NULL,
    external_account_id TEXT NOT NULL,
    name TEXT,
    currency TEXT,
    status TEXT NOT NULL,
    last_synced_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ad_account_org_id_idx ON ad_account(org_id);
CREATE UNIQUE INDEX idx_ad_account_external ON ad_account(platform, external_account_id);

CREATE TABLE campaign_cycle (
    id TEXT PRIMARY KEY,                    -- ccy_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    ad_account_id TEXT REFERENCES ad_account(id),
    product_scope_json jsonb NOT NULL,
    objective TEXT NOT NULL,
    funnel_stage TEXT,
    budget numeric(14,2),
    currency TEXT NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    target_market TEXT,
    channels_json jsonb NOT NULL,
    placements_json jsonb,
    offer_id TEXT,                          -- no DB FK in source (SQLite build-order note); kept as-is
    landing_page TEXT,
    status TEXT NOT NULL,
    close_reason TEXT,
    blocked boolean,                        -- judgment call: type-decisions.md item 2
    needs_information boolean,              -- judgment call: type-decisions.md item 2
    archived boolean NOT NULL DEFAULT false,
    plan_version INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT 'normal',
    pain_slider_value double precision,
    derived_plan_json jsonb,
    diff_snapshot_json jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    background TEXT,                        -- 0002_cycle_background.sql
    occasion TEXT                           -- 0017_occasion.sql
);
CREATE INDEX campaign_cycle_org_id_idx ON campaign_cycle(org_id);
CREATE INDEX idx_campaign_cycle_brand_id ON campaign_cycle(brand_id);
CREATE INDEX idx_campaign_cycle_status ON campaign_cycle(brand_id, status);

CREATE TABLE campaign_cycle_product (
    id TEXT PRIMARY KEY,                    -- ccp_*
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    allocated_budget numeric(14,2),
    allocation_ratio double precision,
    allocation_basis TEXT NOT NULL,
    economics_missing boolean NOT NULL DEFAULT false,  -- judgment call: type-decisions.md item 2
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_cycle_product_org_id_idx ON campaign_cycle_product(org_id);
CREATE UNIQUE INDEX idx_ccp_cycle_product ON campaign_cycle_product(campaign_cycle_id, product_id);
CREATE INDEX idx_ccp_brand_id ON campaign_cycle_product(brand_id);

CREATE TABLE marketing_goal (
    id TEXT PRIMARY KEY,                    -- gol_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,
    objective_summary TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX marketing_goal_org_id_idx ON marketing_goal(org_id);
CREATE INDEX idx_marketing_goal_brand_id ON marketing_goal(brand_id);

CREATE TABLE success_criterion (
    id TEXT PRIMARY KEY,                    -- scr_*
    org_id text NOT NULL REFERENCES organisation(id),
    goal_id TEXT NOT NULL REFERENCES marketing_goal(id),
    brand_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    target_value double precision NOT NULL,
    unit TEXT,
    evaluation_period TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX success_criterion_org_id_idx ON success_criterion(org_id);
CREATE INDEX idx_success_criterion_goal_id ON success_criterion(goal_id);
CREATE INDEX idx_success_criterion_brand_id ON success_criterion(brand_id);

CREATE TABLE campaign_cycle_goal (
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    goal_id TEXT NOT NULL REFERENCES marketing_goal(id),
    brand_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (campaign_cycle_id, goal_id)
);
CREATE INDEX campaign_cycle_goal_org_id_idx ON campaign_cycle_goal(org_id);
CREATE INDEX idx_ccg_brand_id ON campaign_cycle_goal(brand_id);

CREATE TABLE campaign_cycle_hypothesis (
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    strategy_hypothesis_id TEXT NOT NULL,   -- 跨模組引用 strategy_hypothesis
    brand_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (campaign_cycle_id, strategy_hypothesis_id)
);
CREATE INDEX campaign_cycle_hypothesis_org_id_idx ON campaign_cycle_hypothesis(org_id);
CREATE INDEX idx_cch_brand_id ON campaign_cycle_hypothesis(brand_id);

CREATE TABLE offer (
    id TEXT PRIMARY KEY,                    -- ofr_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    product_scope_json jsonb NOT NULL,
    name TEXT NOT NULL,
    offer_type TEXT NOT NULL,
    terms TEXT NOT NULL,
    price_value numeric(14,2),
    currency TEXT,
    valid_from date NOT NULL,   -- judgment call: type-decisions.md item 4
    valid_to date NOT NULL,     -- judgment call: type-decisions.md item 4
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX offer_org_id_idx ON offer(org_id);
CREATE INDEX idx_offer_brand_id ON offer(brand_id);

CREATE TABLE experiment_cell (
    id TEXT PRIMARY KEY,                    -- exc_*
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,
    audience TEXT,
    awareness_stage TEXT,
    pain_point TEXT,
    benefit TEXT,
    creative_angle TEXT,
    format TEXT,
    cta TEXT,
    audience_hypothesis_id TEXT,
    message_hypothesis_id TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX experiment_cell_org_id_idx ON experiment_cell(org_id);
CREATE INDEX idx_experiment_cell_cycle_id ON experiment_cell(campaign_cycle_id);
CREATE INDEX idx_experiment_cell_brand_id ON experiment_cell(brand_id);

CREATE TABLE campaign_plan (
    id TEXT PRIMARY KEY,                    -- cpl_*
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    plan_json jsonb NOT NULL,
    status TEXT NOT NULL,
    approved_by TEXT,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_plan_org_id_idx ON campaign_plan(org_id);
CREATE UNIQUE INDEX idx_campaign_plan_version ON campaign_plan(campaign_cycle_id, plan_version);
CREATE INDEX idx_campaign_plan_brand_id ON campaign_plan(brand_id);

CREATE TABLE creative_brief (
    id TEXT PRIMARY KEY,                    -- cbf_*
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    brand_id TEXT NOT NULL,
    brief_type TEXT NOT NULL,
    purpose TEXT NOT NULL,
    constraints TEXT,
    expected_output TEXT,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creative_brief_org_id_idx ON creative_brief(org_id);
CREATE INDEX idx_creative_brief_cycle_id ON creative_brief(campaign_cycle_id);
CREATE INDEX idx_creative_brief_brand_id ON creative_brief(brand_id);

CREATE TABLE creative_variant (
    id TEXT PRIMARY KEY,                    -- cvr_*
    org_id text NOT NULL REFERENCES organisation(id),
    variant_type TEXT NOT NULL,
    creative_brief_id TEXT NOT NULL REFERENCES creative_brief(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,
    product_scope_json jsonb,
    audience_hypothesis_id TEXT,
    cta TEXT,
    claim_id TEXT,
    product_facts_used_json jsonb,
    attributes_json jsonb NOT NULL,
    fingerprint_json jsonb,
    rationale TEXT,
    recommendation_rank INTEGER,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creative_variant_org_id_idx ON creative_variant(org_id);
CREATE INDEX idx_creative_variant_cycle_id ON creative_variant(campaign_cycle_id);
CREATE INDEX idx_creative_variant_brand_id ON creative_variant(brand_id);
CREATE INDEX idx_creative_variant_brief_id ON creative_variant(creative_brief_id);

CREATE TABLE final_asset (
    id TEXT PRIMARY KEY,                    -- fas_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    source_variant_id TEXT NOT NULL REFERENCES creative_variant(id),
    asset_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    manual_edits_note TEXT,
    status TEXT NOT NULL,
    blocked boolean,                        -- judgment call: type-decisions.md item 2
    needs_information boolean,              -- judgment call: type-decisions.md item 2
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX final_asset_org_id_idx ON final_asset(org_id);
CREATE INDEX idx_final_asset_brand_id ON final_asset(brand_id);
CREATE INDEX idx_final_asset_cycle_id ON final_asset(campaign_cycle_id);
CREATE INDEX idx_final_asset_variant_id ON final_asset(source_variant_id);

CREATE TABLE adoption_decision (
    id TEXT PRIMARY KEY,                    -- adp_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT,
    reason_text TEXT,
    fingerprint_json jsonb,
    decided_by TEXT NOT NULL,
    decided_at timestamptz NOT NULL
);
CREATE INDEX adoption_decision_org_id_idx ON adoption_decision(org_id);
CREATE INDEX idx_adoption_decision_brand_id ON adoption_decision(brand_id);
CREATE INDEX idx_adoption_decision_target ON adoption_decision(target_type, target_id);
CREATE INDEX idx_adoption_decision_cycle_id ON adoption_decision(campaign_cycle_id);

CREATE TABLE creative_rule_card (
    id TEXT PRIMARY KEY,                    -- rcd_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,
    fingerprint_axis TEXT NOT NULL,
    fingerprint_value TEXT NOT NULL,
    proposed_rule_text TEXT NOT NULL,
    evidence_json jsonb NOT NULL,
    reject_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    promoted_rule_id TEXT,
    surfaced_cycle_id TEXT REFERENCES campaign_cycle(id),
    decided_by TEXT,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creative_rule_card_org_id_idx ON creative_rule_card(org_id);
CREATE INDEX idx_rule_card_brand_id ON creative_rule_card(brand_id);
CREATE INDEX idx_rule_card_status ON creative_rule_card(brand_id, status);

-- Final shape (post 0020_publishing_package_no_variant_fk.sql): hook_id/script_id/copy_variant_id
-- lost their REFERENCES creative_variant(id) FK; kept as plain text.
CREATE TABLE publishing_package (
    id TEXT PRIMARY KEY,                    -- pkg_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    product_id TEXT,
    final_asset_id TEXT REFERENCES final_asset(id),
    hook_id TEXT,
    script_id TEXT,
    copy_variant_id TEXT,
    campaign_name TEXT NOT NULL,
    adset_name TEXT NOT NULL,
    ad_name TEXT NOT NULL,
    destination_url TEXT NOT NULL,
    utm_json jsonb NOT NULL,
    placement TEXT,
    objective TEXT,
    daily_budget numeric(14,2),
    note TEXT,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX publishing_package_org_id_idx ON publishing_package(org_id);
CREATE INDEX idx_publishing_package_brand_id ON publishing_package(brand_id);
CREATE INDEX idx_publishing_package_cycle_id ON publishing_package(campaign_cycle_id);

CREATE TABLE activation_authorization (
    id TEXT PRIMARY KEY,                    -- ath_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    authorized_at timestamptz NOT NULL,
    note TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX activation_authorization_org_id_idx ON activation_authorization(org_id);
CREATE INDEX idx_activation_auth_brand_id ON activation_authorization(brand_id);

CREATE TABLE external_ad_mapping (
    id TEXT PRIMARY KEY,                    -- xam_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    publishing_package_id TEXT REFERENCES publishing_package(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    ad_account_id TEXT REFERENCES ad_account(id),
    platform TEXT NOT NULL,
    meta_account_id TEXT,
    meta_campaign_id TEXT,
    meta_adset_id TEXT,
    meta_ad_id TEXT,
    meta_creative_id TEXT,
    internal_asset_id TEXT REFERENCES final_asset(id),
    claim_status TEXT NOT NULL DEFAULT 'confirmed',
    confirmed_by TEXT,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX external_ad_mapping_org_id_idx ON external_ad_mapping(org_id);
CREATE INDEX idx_xam_brand_id ON external_ad_mapping(brand_id);
CREATE INDEX idx_xam_cycle_id ON external_ad_mapping(campaign_cycle_id);
CREATE INDEX idx_xam_meta_campaign ON external_ad_mapping(meta_campaign_id);

CREATE TABLE campaign_activation (
    id TEXT PRIMARY KEY,                    -- act_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    authorization_id TEXT NOT NULL REFERENCES activation_authorization(id),
    activated_by TEXT NOT NULL,
    activated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_activation_org_id_idx ON campaign_activation(org_id);
CREATE INDEX idx_campaign_activation_brand_id ON campaign_activation(brand_id);
CREATE INDEX idx_campaign_activation_cycle_id ON campaign_activation(campaign_cycle_id);

CREATE TABLE discovered_campaign (
    id TEXT PRIMARY KEY,                    -- dsc_*
    org_id text NOT NULL REFERENCES organisation(id),
    ad_account_id TEXT NOT NULL REFERENCES ad_account(id),
    platform TEXT NOT NULL,
    meta_campaign_id TEXT NOT NULL,
    campaign_name TEXT,
    objective TEXT,
    effective_status TEXT,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    suggested_brand_id TEXT,
    suggested_reason TEXT,
    claim_status TEXT NOT NULL,
    claimed_brand_id TEXT,
    claimed_by TEXT,
    claimed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX discovered_campaign_org_id_idx ON discovered_campaign(org_id);
CREATE UNIQUE INDEX idx_discovered_campaign_external ON discovered_campaign(ad_account_id, meta_campaign_id);
CREATE INDEX idx_discovered_campaign_status ON discovered_campaign(claim_status);

CREATE TABLE performance_snapshot (
    id TEXT PRIMARY KEY,                    -- psn_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    product_id TEXT,
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    platform TEXT NOT NULL,
    account_id TEXT,
    meta_campaign_id TEXT,
    meta_adset_id TEXT,
    meta_ad_id TEXT,
    date_range_start date NOT NULL,   -- judgment call: type-decisions.md item 4
    date_range_end date NOT NULL,     -- judgment call: type-decisions.md item 4
    as_of_date date NOT NULL,
    snapshot_taken_at timestamptz NOT NULL,
    currency TEXT NOT NULL,
    impressions bigint,
    clicks bigint,
    spend numeric(14,2),
    conversions double precision,
    revenue numeric(14,2),
    raw_json jsonb,
    reconciled boolean NOT NULL DEFAULT false,  -- judgment call: type-decisions.md item 2
    source TEXT NOT NULL,
    import_batch_id TEXT,
    quarantined boolean NOT NULL DEFAULT false, -- judgment call: type-decisions.md item 2
    quarantine_reason TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    frequency double precision,             -- 0005_checkpoint.sql
    reach bigint,                           -- 0013_reach.sql (bigint per impressions/reach/clicks rule)
    revenue_source TEXT                     -- 0010_inflation_coefficient.sql
);
CREATE INDEX performance_snapshot_org_id_idx ON performance_snapshot(org_id);
CREATE INDEX idx_psn_brand_id ON performance_snapshot(brand_id);
CREATE INDEX idx_psn_cycle_id ON performance_snapshot(campaign_cycle_id);
CREATE INDEX idx_psn_as_of ON performance_snapshot(brand_id, as_of_date);

CREATE TABLE derived_metric (
    id TEXT PRIMARY KEY,                    -- dmt_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    performance_snapshot_id TEXT NOT NULL REFERENCES performance_snapshot(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    product_id TEXT,
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    metric TEXT NOT NULL,
    value double precision NOT NULL,
    unit TEXT,
    calc_basis TEXT,
    computed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX derived_metric_org_id_idx ON derived_metric(org_id);
CREATE INDEX idx_dmt_brand_id ON derived_metric(brand_id);
CREATE INDEX idx_dmt_snapshot_id ON derived_metric(performance_snapshot_id);

CREATE TABLE performance_reading (
    id TEXT PRIMARY KEY,                    -- prd_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    product_id TEXT,
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    status TEXT NOT NULL,
    rule_result_json jsonb NOT NULL,
    confidence_level TEXT,
    llm_explanation TEXT,
    llm_task_id TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX performance_reading_org_id_idx ON performance_reading(org_id);
CREATE INDEX idx_prd_brand_id ON performance_reading(brand_id);
CREATE INDEX idx_prd_cycle_id ON performance_reading(campaign_cycle_id);

CREATE TABLE recommendation (
    id TEXT PRIMARY KEY,                    -- rec_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    product_id TEXT,
    performance_reading_id TEXT REFERENCES performance_reading(id),
    recommendation_type TEXT NOT NULL,
    content_json jsonb NOT NULL,
    status TEXT NOT NULL,
    blocked boolean,                        -- judgment call: type-decisions.md item 2
    needs_information boolean,              -- judgment call: type-decisions.md item 2
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recommendation_org_id_idx ON recommendation(org_id);
CREATE INDEX idx_rec_brand_id ON recommendation(brand_id);
CREATE INDEX idx_rec_cycle_id ON recommendation(campaign_cycle_id);

CREATE TABLE finding (
    id TEXT PRIMARY KEY,                    -- fnd_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    finding_type TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json jsonb,
    confidence_penalty double precision NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    resolved boolean NOT NULL DEFAULT false,    -- judgment call: type-decisions.md item 2
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX finding_org_id_idx ON finding(org_id);
CREATE INDEX idx_finding_brand_id ON finding(brand_id);
CREATE INDEX idx_finding_cycle_id ON finding(campaign_cycle_id);
CREATE INDEX idx_finding_target ON finding(target_type, target_id);

-- ============================================================
-- 0003_plan_options.sql
-- ============================================================
CREATE TABLE campaign_plan_option (
    id TEXT PRIMARY KEY,                    -- cpo_*
    org_id text NOT NULL REFERENCES organisation(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    option_index INTEGER NOT NULL,
    is_recommended boolean NOT NULL DEFAULT false,
    option_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_plan_option_org_id_idx ON campaign_plan_option(org_id);
CREATE INDEX idx_campaign_plan_option_cycle ON campaign_plan_option(campaign_cycle_id);
CREATE INDEX idx_campaign_plan_option_brand ON campaign_plan_option(brand_id);

-- ============================================================
-- 0004_rule_dissent.sql
-- ============================================================
CREATE TABLE rule_dissent (
    id TEXT PRIMARY KEY,                    -- dsn_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    target_type TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    reason TEXT NOT NULL,
    llm_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rule_dissent_org_id_idx ON rule_dissent(org_id);
CREATE INDEX idx_rule_dissent_cycle ON rule_dissent(campaign_cycle_id);
CREATE INDEX idx_rule_dissent_brand ON rule_dissent(brand_id);

-- ============================================================
-- 0005_checkpoint.sql (performance_snapshot.frequency folded in above)
-- ============================================================
CREATE TABLE cycle_checkpoint (
    id TEXT PRIMARY KEY,                    -- chk_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    kind TEXT NOT NULL,
    result_json jsonb NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cycle_checkpoint_org_id_idx ON cycle_checkpoint(org_id);
CREATE INDEX idx_cycle_checkpoint_cycle ON cycle_checkpoint(campaign_cycle_id);
CREATE INDEX idx_cycle_checkpoint_brand ON cycle_checkpoint(brand_id);

-- ============================================================
-- 0006_checklist.sql
-- ============================================================
CREATE TABLE brand_checklist_item (
    id TEXT PRIMARY KEY,                    -- bcl_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    item_key TEXT NOT NULL,
    checked boolean NOT NULL DEFAULT false,     -- judgment call: type-decisions.md item 2
    checked_by TEXT,
    checked_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX brand_checklist_item_org_id_idx ON brand_checklist_item(org_id);
CREATE UNIQUE INDEX idx_brand_checklist_item ON brand_checklist_item(brand_id, item_key);

CREATE TABLE cycle_checklist_item (
    id TEXT PRIMARY KEY,                    -- ccl_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    item_key TEXT NOT NULL,
    checked boolean NOT NULL DEFAULT false,     -- judgment call: type-decisions.md item 2
    checked_by TEXT,
    checked_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cycle_checklist_item_org_id_idx ON cycle_checklist_item(org_id);
CREATE UNIQUE INDEX idx_cycle_checklist_item ON cycle_checklist_item(campaign_cycle_id, item_key);
CREATE INDEX idx_cycle_checklist_brand ON cycle_checklist_item(brand_id);

-- ============================================================
-- 0008_ga4.sql
-- ============================================================
CREATE TABLE ga4_summary (
    id TEXT PRIMARY KEY,               -- ga4_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    date_range_start date NOT NULL,    -- judgment call: type-decisions.md item 4
    date_range_end date NOT NULL,      -- judgment call: type-decisions.md item 4
    source TEXT NOT NULL,
    medium TEXT NOT NULL,
    sessions INTEGER NOT NULL,
    conversions double precision NOT NULL,
    revenue numeric(14,2) NOT NULL,
    synced_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ga4_summary_org_id_idx ON ga4_summary(org_id);
CREATE INDEX idx_ga4_summary_brand ON ga4_summary(brand_id, date_range_end DESC);

CREATE TABLE ga4_sync_status (
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT PRIMARY KEY NOT NULL,
    date_range_start date NOT NULL,
    date_range_end date NOT NULL,
    row_count INTEGER NOT NULL,
    purchase_event_seen boolean,       -- NULL＝這次沒驗證到；0／1＝驗證結果
    synced_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ga4_sync_status_org_id_idx ON ga4_sync_status(org_id);

-- ============================================================
-- 0009_voucher_codes.sql
-- ============================================================
CREATE TABLE cycle_voucher_code (
    id TEXT PRIMARY KEY,                    -- vch_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    source_type TEXT NOT NULL,
    code TEXT NOT NULL,
    discount_type TEXT NOT NULL,
    discount_value double precision NOT NULL,
    usage_limit INTEGER NOT NULL,
    valid_from date NOT NULL,   -- judgment call: type-decisions.md item 4
    valid_to date NOT NULL,     -- judgment call: type-decisions.md item 4
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cycle_voucher_code_org_id_idx ON cycle_voucher_code(org_id);
CREATE UNIQUE INDEX idx_voucher_code_cycle_source ON cycle_voucher_code(campaign_cycle_id, source_type);
CREATE UNIQUE INDEX idx_voucher_code_brand_code ON cycle_voucher_code(brand_id, code);

CREATE TABLE cycle_code_verification (
    id TEXT PRIMARY KEY,                    -- vcv_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    passed boolean NOT NULL,                -- comment says 0/1
    mismatches_json jsonb,
    checked_by TEXT NOT NULL,
    checked_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cycle_code_verification_org_id_idx ON cycle_code_verification(org_id);
CREATE INDEX idx_code_verification_cycle ON cycle_code_verification(campaign_cycle_id, checked_at DESC);

-- ============================================================
-- 0010_inflation_coefficient.sql (performance_snapshot.revenue_source folded in above)
-- ============================================================
CREATE TABLE ad_revenue_coefficient (
    id TEXT PRIMARY KEY,                    -- arc_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    coefficient double precision NOT NULL,
    meta_revenue numeric(14,2) NOT NULL,
    order_revenue numeric(14,2) NOT NULL,
    sample_size INTEGER NOT NULL,
    reliable boolean NOT NULL DEFAULT false,    -- judgment call: type-decisions.md item 2
    source_cycle_id TEXT REFERENCES campaign_cycle(id),
    valid_from date NOT NULL,   -- judgment call: type-decisions.md item 4
    valid_to date,              -- judgment call: type-decisions.md item 4
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ad_revenue_coefficient_org_id_idx ON ad_revenue_coefficient(org_id);
CREATE INDEX idx_arc_brand_id ON ad_revenue_coefficient(brand_id);
CREATE INDEX idx_arc_brand_valid ON ad_revenue_coefficient(brand_id, valid_to);

CREATE TABLE ad_revenue_coefficient_error_log (
    id TEXT PRIMARY KEY,                    -- rce_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    coefficient_id TEXT NOT NULL REFERENCES ad_revenue_coefficient(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    predicted_order_revenue numeric(14,2),
    actual_order_revenue numeric(14,2) NOT NULL,
    error_pct double precision,
    recorded_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ad_revenue_coefficient_error_log_org_id_idx ON ad_revenue_coefficient_error_log(org_id);
CREATE INDEX idx_arce_brand_id ON ad_revenue_coefficient_error_log(brand_id, recorded_at DESC);

-- ============================================================
-- 0011_settlement_snapshot.sql (diff_summary from 0012 folded in below)
-- ============================================================
CREATE TABLE settlement_version (
    id TEXT PRIMARY KEY,                          -- setv_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    version INTEGER NOT NULL,
    trigger_reason TEXT NOT NULL,
    is_post_close boolean NOT NULL DEFAULT false,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    diff_summary TEXT                             -- 0012_settlement_diff.sql
);
CREATE INDEX settlement_version_org_id_idx ON settlement_version(org_id);
CREATE UNIQUE INDEX idx_setv_cycle_version ON settlement_version(campaign_cycle_id, version);
CREATE INDEX idx_setv_brand_id ON settlement_version(brand_id);

CREATE TABLE reading_snapshot (
    id TEXT PRIMARY KEY,                           -- rsnap_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    settlement_version_id TEXT NOT NULL REFERENCES settlement_version(id),
    coefficient_version_id TEXT REFERENCES ad_revenue_coefficient(id),
    data_arrival_json jsonb NOT NULL,
    missing_sources_json jsonb NOT NULL,
    summary_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reading_snapshot_org_id_idx ON reading_snapshot(org_id);
CREATE INDEX idx_rsnap_cycle ON reading_snapshot(campaign_cycle_id);
CREATE UNIQUE INDEX idx_rsnap_settlement_version ON reading_snapshot(settlement_version_id);

CREATE TABLE reading_snapshot_input (
    id TEXT PRIMARY KEY,                           -- rsin_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    reading_snapshot_id TEXT NOT NULL REFERENCES reading_snapshot(id),
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reading_snapshot_input_org_id_idx ON reading_snapshot_input(org_id);
CREATE INDEX idx_rsin_snapshot ON reading_snapshot_input(reading_snapshot_id);
CREATE INDEX idx_rsin_cycle ON reading_snapshot_input(campaign_cycle_id);

-- ============================================================
-- 0015_creative_theme.sql (0016 performance_* columns folded in below)
-- ============================================================
CREATE TABLE creative_theme (
    id TEXT PRIMARY KEY,                          -- cth_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT NOT NULL REFERENCES experiment_cell(id),
    format_key TEXT NOT NULL,
    name TEXT NOT NULL,
    folder_code TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creative_theme_org_id_idx ON creative_theme(org_id);
CREATE INDEX idx_creative_theme_brand_id ON creative_theme(brand_id);
CREATE INDEX idx_creative_theme_cycle_id ON creative_theme(campaign_cycle_id);
CREATE INDEX idx_creative_theme_cell_id ON creative_theme(experiment_cell_id);

CREATE TABLE creative_theme_component (
    id TEXT PRIMARY KEY,                          -- cthc_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    creative_theme_id TEXT NOT NULL REFERENCES creative_theme(id),
    component_type TEXT NOT NULL,
    sequence INTEGER,
    content TEXT NOT NULL,
    fingerprint_json jsonb,
    over_budget boolean NOT NULL DEFAULT false,     -- judgment call: type-decisions.md item 2
    similarity_flag boolean NOT NULL DEFAULT false, -- judgment call: type-decisions.md item 2
    created_at timestamptz NOT NULL DEFAULT now(),
    meta_asset_id TEXT,                             -- 0016_theme_component_performance.sql
    performance_impressions bigint,                 -- judgment call: type-decisions.md item 5
    performance_clicks bigint,                      -- judgment call: type-decisions.md item 5
    performance_conversions INTEGER,
    performance_synced_at timestamptz
);
CREATE INDEX creative_theme_component_org_id_idx ON creative_theme_component(org_id);
CREATE INDEX idx_creative_theme_component_theme_id ON creative_theme_component(creative_theme_id);
CREATE INDEX idx_creative_theme_component_brand_id ON creative_theme_component(brand_id);
CREATE INDEX idx_creative_theme_component_cycle_id ON creative_theme_component(campaign_cycle_id);

-- ============================================================
-- 0018_channel_tracking_check.sql
-- ============================================================
CREATE TABLE channel_tracking_check (
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    channel_key TEXT NOT NULL CHECK (channel_key IN ('website', 'fb_page', 'ig_account', 'shopee', 'pharmacy')),
    hidden boolean NOT NULL DEFAULT false,      -- judgment call: type-decisions.md item 2
    ga4_found boolean,      -- NULL／0／1
    pixel_found boolean,    -- NULL／0／1
    checked_at timestamptz,
    PRIMARY KEY (brand_id, channel_key)
);
CREATE INDEX channel_tracking_check_org_id_idx ON channel_tracking_check(org_id);

-- ============================================================
-- 0019_channel_plan_task_card.sql
-- ============================================================
CREATE TABLE channel_plan (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    channel TEXT NOT NULL,
    job TEXT NOT NULL,
    pct INTEGER NOT NULL,
    expected TEXT NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    depth TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brand_id, cycle_id, channel)
);
CREATE INDEX channel_plan_org_id_idx ON channel_plan(org_id);
CREATE INDEX idx_channel_plan_brand_cycle ON channel_plan(brand_id, cycle_id);

CREATE TABLE task_card (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    draft_hint TEXT,
    done boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    done_at timestamptz
);
CREATE INDEX task_card_org_id_idx ON task_card(org_id);
CREATE INDEX idx_task_card_brand_cycle ON task_card(brand_id, cycle_id);
