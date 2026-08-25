-- supabase/migrations/20260826000003_intake_baseline.sql
-- Module: intake
-- Generated from app/intake/migrations 0001..0002 on 2026-08-26 (ADR 0027 rebaseline).
-- Rule: migration files only CREATE tables prefixed/owned by this module.

CREATE TABLE intake_draft (
    id TEXT PRIMARY KEY,                    -- idr_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step INTEGER NOT NULL,
    current_question_no INTEGER NOT NULL,
    description TEXT NOT NULL,
    photos_json jsonb NOT NULL,
    research_urls_json jsonb NOT NULL,
    scan_sources_json jsonb,
    scan_impressions_json jsonb,
    scan_llm_task_id TEXT,
    qa_json jsonb,
    handoff_depth TEXT,
    handoff_prompt TEXT,
    handoff_generated_at timestamptz,
    paste_raw TEXT,
    paste_validation_json jsonb,
    repair_llm_task_id TEXT,
    cost_limit numeric(14,2) NOT NULL,
    llm_task_refs_json jsonb NOT NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    scan_products_json jsonb                -- 0002_scan_products.sql
);
CREATE INDEX intake_draft_org_id_idx ON intake_draft(org_id);
-- 一個品牌同時只有一份進行中草稿：DB 層擋，不靠 app 層自律。
CREATE UNIQUE INDEX idx_intake_draft_one_active ON intake_draft(brand_id) WHERE status = 'draft';

CREATE TABLE intake_item (
    id TEXT PRIMARY KEY,                    -- iit_*
    org_id text NOT NULL REFERENCES organisation(id),
    intake_draft_id TEXT NOT NULL REFERENCES intake_draft(id),
    brand_id TEXT NOT NULL,
    row_no INTEGER NOT NULL,
    raw_row TEXT NOT NULL,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    scope_raw TEXT NOT NULL,
    scope_product_id TEXT,
    evidence_source TEXT,
    client_evidence TEXT,
    outcome TEXT NOT NULL,
    target_table TEXT,
    target_id TEXT,
    processed_by TEXT,
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX intake_item_org_id_idx ON intake_item(org_id);
CREATE INDEX idx_intake_item_draft_row ON intake_item(intake_draft_id, row_no);
CREATE INDEX idx_intake_item_brand_outcome ON intake_item(brand_id, outcome);
