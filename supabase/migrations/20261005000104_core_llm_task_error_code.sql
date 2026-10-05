-- supabase/migrations/20261005000104_core_llm_task_error_code.sql
-- Module: core. Ticket: F50-I07 (feature F50 Contract J, audit W14).
--
-- `llm_task.error` stays the human sentence; `error_code` names its kind so no reader has to
-- guess from free text. Written only by `app/llm/gateway.py` (beside `error`) and by
-- `gateway.record_refusal()` for a program refusal of a model reply. NULL on rows written
-- before this migration and on succeeded rows.

ALTER TABLE llm_task ADD COLUMN error_code text;
ALTER TABLE llm_task ADD CONSTRAINT llm_task_error_code_check CHECK (
    error_code IS NULL OR error_code IN (
        'timeout', 'refused', 'provider', 'truncated', 'spend_cap', 'no_credentials',
        'program_refused'
    )
);
