-- supabase/migrations/20260826000002_brand_intelligence_baseline.sql
-- Module: brand_intelligence
-- Generated from app/brand_intelligence/migrations 0001..0008 on 2026-08-26 (ADR 0027 rebaseline).
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- learning_ledger note: also has a CREATE TABLE IF NOT EXISTS in app/ads/migrations/0001_tables.sql,
-- but app/brand_intelligence/migrations/0004 runs first at app startup, so the ads-module CREATE is
-- a documented no-op. This baseline therefore defines learning_ledger once, here, using the
-- brand_intelligence version's columns (no FK on source_cycle_id/source_reading_id — the ads
-- version's FKs on those never actually applied) plus source_track from the follow-up ALTER.
-- See .scratch/saas/tickets/02-2-type-decisions.md item 3.

CREATE TABLE brand (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    name TEXT NOT NULL,
    client_name TEXT,
    status TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    market_region TEXT,        -- 0005_brand_switches.sql
    conversion_goal TEXT,      -- 0005_brand_switches.sql
    industry TEXT              -- 0006_holiday_relevance_industry.sql
);
CREATE INDEX brand_org_id_idx ON brand(org_id);

CREATE TABLE product (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_org_id_idx ON product(org_id);
CREATE INDEX idx_product_brand_id ON product(brand_id);

CREATE TABLE source_reference (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    title TEXT NOT NULL,
    url TEXT,
    source_type TEXT NOT NULL,
    published_date date,
    captured_date date NOT NULL,
    locale TEXT,
    note TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX source_reference_org_id_idx ON source_reference(org_id);
CREATE INDEX idx_source_reference_brand_id ON source_reference(brand_id);

CREATE TABLE brand_fact (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    fact_type TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confidence TEXT,
    confirmed_by TEXT,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX brand_fact_org_id_idx ON brand_fact(org_id);
CREATE INDEX idx_brand_fact_brand_id ON brand_fact(brand_id);
CREATE INDEX idx_brand_fact_source_reference_id ON brand_fact(source_reference_id);

CREATE TABLE product_fact (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    product_id TEXT NOT NULL REFERENCES product(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    fact_type TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confidence TEXT,
    confirmed_by TEXT,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_fact_org_id_idx ON product_fact(org_id);
CREATE INDEX idx_product_fact_product_id ON product_fact(product_id);
CREATE INDEX idx_product_fact_brand_id ON product_fact(brand_id);
CREATE INDEX idx_product_fact_source_reference_id ON product_fact(source_reference_id);

CREATE TABLE product_economics (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    product_id TEXT NOT NULL REFERENCES product(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    selling_price numeric(14,2) NOT NULL,
    fixed_cost numeric(14,2),
    unit_variable_cost numeric(14,2),
    shipping_cost numeric(14,2),
    currency TEXT NOT NULL,
    cpa_roas_basis TEXT,
    effective_from date,   -- judgment call: see type-decisions.md item 4
    effective_to date,     -- judgment call: see type-decisions.md item 4
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confirmed_by TEXT,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_economics_org_id_idx ON product_economics(org_id);
CREATE INDEX idx_product_economics_product_id ON product_economics(product_id);
CREATE INDEX idx_product_economics_brand_id ON product_economics(brand_id);

CREATE TABLE brand_performance_baseline (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    metric TEXT NOT NULL,
    value double precision NOT NULL,
    unit TEXT,
    basis_note TEXT,
    source_cycle_id TEXT,
    sample_note TEXT,
    as_of_date date NOT NULL,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX brand_performance_baseline_org_id_idx ON brand_performance_baseline(org_id);
CREATE INDEX idx_bpb_brand_id ON brand_performance_baseline(brand_id);
CREATE INDEX idx_bpb_product_id ON brand_performance_baseline(product_id);

CREATE TABLE rule (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    rule_type TEXT NOT NULL,
    content TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz     -- 0007_rule_confirmed_at.sql
);
CREATE INDEX rule_org_id_idx ON rule(org_id);
CREATE INDEX idx_rule_brand_id ON rule(brand_id);
CREATE INDEX idx_rule_product_id ON rule(product_id);

CREATE TABLE claim (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    evidence_source_reference_id TEXT REFERENCES source_reference(id),
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX claim_org_id_idx ON claim(org_id);
CREATE INDEX idx_claim_brand_id ON claim(brand_id);
CREATE INDEX idx_claim_product_id ON claim(product_id);

CREATE TABLE official_asset (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    asset_kind TEXT NOT NULL,
    file_path TEXT NOT NULL,
    title TEXT,
    usage_note TEXT,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX official_asset_org_id_idx ON official_asset(org_id);
CREATE INDEX idx_official_asset_brand_id ON official_asset(brand_id);
CREATE INDEX idx_official_asset_product_id ON official_asset(product_id);

CREATE TABLE strategy_hypothesis (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    hypothesis_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    source_cycle_id TEXT,
    created_by TEXT NOT NULL,
    expired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX strategy_hypothesis_org_id_idx ON strategy_hypothesis(org_id);
CREATE INDEX idx_strategy_hypothesis_brand_id ON strategy_hypothesis(brand_id);
CREATE INDEX idx_strategy_hypothesis_product_id ON strategy_hypothesis(product_id);

CREATE TABLE owned_channel (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    channel_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    identifier TEXT,
    status TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX owned_channel_org_id_idx ON owned_channel(org_id);
CREATE INDEX idx_owned_channel_brand_id ON owned_channel(brand_id);

-- ============================================================
-- 0002_brand_report.sql
-- ============================================================
CREATE TABLE brand_report (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    generated_at timestamptz NOT NULL,
    generated_by TEXT NOT NULL,
    model TEXT NOT NULL,
    llm_task_id TEXT,
    brand_version INTEGER NOT NULL,
    source_fact_count INTEGER NOT NULL DEFAULT 0,
    sections_json jsonb NOT NULL
);
CREATE INDEX brand_report_org_id_idx ON brand_report(org_id);
CREATE INDEX idx_brand_report_brand_id ON brand_report(brand_id);

-- ============================================================
-- 0003_customer_voice.sql
-- ============================================================
CREATE TABLE customer_voice (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    raw_text TEXT NOT NULL,
    source_channel TEXT NOT NULL,
    source_detail TEXT,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL,
    extraction_json jsonb NOT NULL,
    llm_task_id TEXT,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX customer_voice_org_id_idx ON customer_voice(org_id);
CREATE INDEX idx_customer_voice_brand_id ON customer_voice(brand_id);

-- ============================================================
-- 0004_learning_ledger.sql (+ source_track ALTER); see file header note.
-- ============================================================
CREATE TABLE learning_ledger (
    id TEXT PRIMARY KEY,                    -- lrn_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,
    platform TEXT,
    learning_text TEXT NOT NULL,
    applicability_scope TEXT NOT NULL,
    source_cycle_id TEXT,
    source_reading_id TEXT,
    source_hypothesis_id TEXT,
    sample_size TEXT,
    confidence TEXT,
    needs_revalidation boolean NOT NULL DEFAULT false,  -- judgment call: type-decisions.md item 1
    expired boolean NOT NULL DEFAULT false,
    learned_at timestamptz NOT NULL,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    source_track TEXT NOT NULL DEFAULT 'ads'
);
CREATE INDEX learning_ledger_org_id_idx ON learning_ledger(org_id);
CREATE INDEX idx_lrn_brand_id ON learning_ledger(brand_id);
CREATE INDEX idx_lrn_source_cycle ON learning_ledger(source_cycle_id);

-- ============================================================
-- 0008_persona.sql
-- ============================================================
CREATE TABLE persona (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    title TEXT NOT NULL,
    when_needed TEXT NOT NULL,
    care_about TEXT NOT NULL,
    hesitation TEXT NOT NULL,
    where_to_find TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX persona_org_id_idx ON persona(org_id);
