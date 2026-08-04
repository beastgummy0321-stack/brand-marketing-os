-- app/core/migrations/0001_core.sql
-- audit_log、llm_task —— 見 docs/design/03-data-model.md §3.1。
-- 跨模組欄位（如 llm_task.brand_id 指向 brand_intelligence.brand）一律不建 DB 外鍵（03 §1、§8.4）。

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    brand_id TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_brand_id ON audit_log(brand_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS llm_task (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    context_scope_json TEXT NOT NULL,
    input_context_ids_json TEXT NOT NULL,
    input_context_hash TEXT NOT NULL,
    knowledge_item_ids_json TEXT NOT NULL,
    brand_version INTEGER NOT NULL,
    product_version INTEGER,
    campaign_plan_version INTEGER,
    prompt_template_id TEXT NOT NULL,
    prompt_template_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    structured_output_json TEXT,
    rendered_output TEXT,
    validation_result_json TEXT,
    usage_json TEXT,
    cost REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_task_brand_id ON llm_task(brand_id);
