-- supabase/migrations/20260826000001_core_baseline.sql
-- Module: core
-- Generated from app/core/migrations 0001..0013 on 2026-08-26 (ADR 0027 rebaseline).
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- Column-shape source of truth: app/core/migrations/*.sql, ALTERs applied in filename order.
-- Type mapping: ticket 02-2 §4 (TEXT *_at -> timestamptz, *_json -> jsonb, INTEGER 0/1 -> boolean,
-- REAL money-named -> numeric(14,2), REAL otherwise -> double precision).
-- rule_card_value.brand_id: 0010_rule_card_per_brand.sql added it and made it part of the PK
-- before this rebaseline (schema-inventory.md's "no brand_id" note is stale; migrations are
-- authoritative per ticket). See .scratch/saas/tickets/02-2-type-decisions.md item 1.

-- ============================================================
-- organisation (new root of the org -> user -> brand hierarchy, ADR 0027 decision 2)
-- ============================================================
CREATE TABLE organisation (
  id         text PRIMARY KEY,                 -- new_id("org")
  name       text NOT NULL,
  kind       text NOT NULL CHECK (kind IN ('personal','company')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- 0001_core.sql
-- ============================================================
CREATE TABLE audit_log (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    before_json jsonb,
    after_json jsonb,
    reason TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_org_id_idx ON audit_log(org_id);
CREATE INDEX idx_audit_log_brand_id ON audit_log(brand_id);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
-- idx_audit_log_brand_created added by 0008_audit_log_composite_index.sql
CREATE INDEX idx_audit_log_brand_created ON audit_log(brand_id, created_at);

CREATE TABLE llm_task (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    context_scope_json jsonb NOT NULL,
    input_context_ids_json jsonb NOT NULL,
    input_context_hash TEXT NOT NULL,
    knowledge_item_ids_json jsonb NOT NULL,
    brand_version INTEGER NOT NULL,
    product_version INTEGER,
    campaign_plan_version INTEGER,
    prompt_template_id TEXT NOT NULL,
    prompt_template_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    structured_output_json jsonb,
    rendered_output TEXT,
    validation_result_json jsonb,
    usage_json jsonb,
    cost numeric(14,2),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    error TEXT
);
CREATE INDEX llm_task_org_id_idx ON llm_task(org_id);
CREATE INDEX idx_llm_task_brand_id ON llm_task(brand_id);

-- ============================================================
-- 0002_app_setting.sql (final PK per ticket 02-2 §3: (org_id, key))
-- ============================================================
CREATE TABLE app_setting (
    org_id text NOT NULL REFERENCES organisation(id),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, key)
);

-- ============================================================
-- 0003_rule_card.sql superseded by 0010_rule_card_per_brand.sql (DROP+recreate,
-- discarding the seed rows — see migration comment). Final shape here, org-scoped
-- on top of the brand-scoped natural key (ticket 02-2 §3: "keep its existing
-- natural key plus org_id").
-- ============================================================
CREATE TABLE rule_card_value (
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    card_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value double precision NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, brand_id, card_key, field_key)
);
CREATE INDEX idx_rule_card_value_brand ON rule_card_value(brand_id);

-- ============================================================
-- 0006_interrupts.sql, unique index replaced by 0007_interrupt_dedupe_per_brand.sql
-- ============================================================
CREATE TABLE interrupt (
    id TEXT PRIMARY KEY,                    -- itr_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT,                          -- NULL＝跨品牌系統級
    campaign_cycle_id TEXT,                 -- 選填：來源掛在某檔期時填，供連帶刪除
    dedupe_key TEXT NOT NULL,
    category TEXT NOT NULL,
    kind TEXT,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    action_url TEXT,
    visible_from timestamptz,
    status TEXT NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
CREATE INDEX interrupt_org_id_idx ON interrupt(org_id);
CREATE UNIQUE INDEX idx_interrupt_brand_dedupe_key ON interrupt(brand_id, dedupe_key);
CREATE INDEX idx_interrupt_brand_status ON interrupt(brand_id, status);
CREATE INDEX idx_interrupt_cycle ON interrupt(campaign_cycle_id);

-- ============================================================
-- 0011_campaign_skip.sql
-- ============================================================
CREATE TABLE campaign_skip (
    id TEXT PRIMARY KEY,             -- csk_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    holiday_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    reason TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX campaign_skip_org_id_idx ON campaign_skip(org_id);
CREATE UNIQUE INDEX idx_campaign_skip_brand_holiday_year ON campaign_skip(brand_id, holiday_id, year);

-- ============================================================
-- 0012_calendar_dismiss.sql
-- ============================================================
CREATE TABLE brand_dismissed_calendar_category (
    id TEXT PRIMARY KEY,             -- bdc_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX brand_dismissed_calendar_category_org_id_idx ON brand_dismissed_calendar_category(org_id);
CREATE UNIQUE INDEX idx_brand_dismissed_calendar_category_brand_category
    ON brand_dismissed_calendar_category(brand_id, category);

-- ============================================================
-- 0013_orchestrator_decision.sql
-- ============================================================
CREATE TABLE decision (
    id TEXT PRIMARY KEY,                    -- dcs_*
    org_id text NOT NULL REFERENCES organisation(id),
    module TEXT NOT NULL,
    brand_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    action_json jsonb NOT NULL,
    risk_level TEXT NOT NULL,
    autonomy_mode double precision NOT NULL,
    dedupe_key TEXT NOT NULL,
    outcome TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    error_text TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decision_org_id_idx ON decision(org_id);
CREATE INDEX idx_decision_brand ON decision(brand_id);
CREATE INDEX idx_decision_dedupe ON decision(brand_id, dedupe_key);
