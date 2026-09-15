-- supabase/migrations/20260915000002_workbench_visual_identity.sql
-- Module: workbench (F07, ARCHITECTURE.md §5.9, issue F07-I05).
--
-- The system derives each brand's visual identity and a ranked starting guess of fitting
-- looks from brand facts alone (Decision 20). One row per (brand, knowledge_version): the
-- derivation is cached, never re-derived until the brand's facts change. `fit_looks` is the
-- ranked catalogue-key list (`brand_spec` first when a confirmed `visual_base` fact exists);
-- `excluded_looks` only ever holds fact-evidenced exclusions, each carrying the verbatim
-- fact text that justified it.
--
-- grep -rn "REFERENCES workbench_brief" supabase/migrations/ pattern followed for this new
-- table too (CLAUDE.md) -- no other migration references workbench_visual_identity, so this
-- CREATE TABLE is the only place its shape lives.
CREATE TABLE workbench_visual_identity (
    id TEXT PRIMARY KEY,                    -- wvi_*, via db.new_id("wvi")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    knowledge_version integer NOT NULL,
    identity_text TEXT NOT NULL,
    fit_looks jsonb NOT NULL,               -- ranked keys, brand_spec first when present
    excluded_looks jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{look, fact}]
    brand_spec_text TEXT,
    llm_task_id TEXT,                        -- same definition as workbench_output.llm_task_id
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brand_id, knowledge_version)
);
CREATE INDEX workbench_visual_identity_org_id_idx ON workbench_visual_identity(org_id);
CREATE INDEX idx_workbench_visual_identity_brand_id ON workbench_visual_identity(brand_id);

-- RLS + grants + org-isolation policy, same per-table shape as every other workbench table
-- (20260909000001_workbench_baseline.sql:64-82).
ALTER TABLE workbench_visual_identity ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON workbench_visual_identity TO authenticated;
DROP POLICY IF EXISTS workbench_visual_identity_org_isolation ON workbench_visual_identity;
CREATE POLICY workbench_visual_identity_org_isolation ON workbench_visual_identity
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
