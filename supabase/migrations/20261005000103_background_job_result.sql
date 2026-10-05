-- supabase/migrations/20261005000103_background_job_result.sql
-- Module: background. Ticket: F50-I07 (feature F50 Contract J, audit W14).
--
-- The stored outcome of a background job, one row per (org, queueing lock): the newest outcome
-- wins (upserted by `app.background.register`'s wrapper when the handler returns or raises).
-- procrastinate's own status only says succeeded/failed; this row adds what the work found:
-- `failed` / `empty` / `done` plus a machine `code` and the sentence a screen shows (`text`).
-- Reader: `app.background.outcome(lock)` (scoped by the job's own `org_id` argument).
--
-- No `brand_id`: a job carries only `org_id` in its args (ADR 0038); periodic dispatchers and
-- account-level work (e.g. meta_daily_pull) have no single brand. Listed in
-- `test_brand_isolation_all_tables.BRAND_AGNOSTIC_EXCEPTIONS`.

CREATE TABLE background_job_result (
    org_id text NOT NULL REFERENCES organisation(id),
    lock text NOT NULL,
    task_name text NOT NULL,
    job_id bigint,
    state text NOT NULL CHECK (state IN ('failed', 'empty', 'done')),
    code text,
    text text,
    finished_at timestamptz NOT NULL,
    PRIMARY KEY (org_id, lock)
);

ALTER TABLE background_job_result ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON background_job_result TO authenticated;
DROP POLICY IF EXISTS background_job_result_org_isolation ON background_job_result;
CREATE POLICY background_job_result_org_isolation ON background_job_result
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
