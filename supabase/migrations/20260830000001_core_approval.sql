-- supabase/migrations/20260830000001_core_approval.sql
-- Module: core
-- Ticket: .scratch/approval-slice/issues/01-approval-is-the-money-brake.md
-- ADR 0040: 核准 (approval) is the 花錢煞車 (money brake) named in ADR 0018 §1 — the fourth
-- of exactly four user gates. This table records it now; no executor is wired to it yet
-- (app/meta/graph.py is read-only today), but the shape must already be platform-neutral
-- because the user ruled 2026-08-30 that the system will eventually publish on every
-- platform itself. Shape copied deliberately from the deleted `activation_authorization`
-- table (supabase/migrations/20260826000004_ads_baseline.sql, dropped with app/ads/):
-- scope_type + scope_ref + authorized_by/at + note. Added on top of that: an amount (an
-- executor cannot know what it may spend without one), a content_hash (so a re-expanded
-- tree cannot silently inherit an old signature), and revocation (a brake that cannot be
-- released is worse than none).
--
-- No platform column, ever. Which platform this spend goes to is already frozen in the
-- tree's own context_scope_json.platform (app/schedule); adding a platform here would be
-- adding data, not columns (ADR 0035).
CREATE TABLE approval (
    id TEXT PRIMARY KEY,                       -- apv_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,                  -- 'schedule_tree' is the only value today
    -- For scope_type = 'schedule_tree': brand_id itself (app/schedule/routes.py is the one
    -- caller). A specific schedule_tree llm_task id would NOT work here — re-expanding a
    -- tree creates a brand new llm_task row every time, so a scope_ref pinned to that row's
    -- id could never again be found by a later lookup, and the whole point of content_hash
    -- (catching a re-expanded tree that silently drifted from what was signed) would never
    -- fire: the lookup would just always come back empty instead of stale. brand_id is the
    -- stable "one live tree per brand" subject that content_hash then checks for staleness
    -- against. A second real scope_type (something other than the brand's tree) is the
    -- point at which scope_ref stops being interchangeable with brand_id — not before.
    scope_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,                -- fingerprint of what was approved
    approved_amount numeric(14,2) NOT NULL,    -- the daily total the human signed
    approved_by TEXT NOT NULL,
    approved_at timestamptz NOT NULL,
    revoked_by TEXT,
    revoked_at timestamptz,
    note TEXT,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX approval_org_id_idx ON approval(org_id);
CREATE INDEX idx_approval_brand_id ON approval(brand_id);

-- ADR 0027 decision 9 / ticket 02-5 convention: every public table gets RLS enabled, no
-- policies (backend connects as postgres, bypasses RLS; this only closes anon/authenticated
-- access via PostgREST). Gate: app/tests/test_real_db_schema_drift.py RowLevelSecurityGateTest.
ALTER TABLE approval ENABLE ROW LEVEL SECURITY;
