-- supabase/migrations/20260909000001_workbench_baseline.sql
-- Module: workbench (ADR 0049). Ticket: workbench/02
-- (docs/issues/workbench/02-workbench-tables-repository-jobs.md). ADR 0068 §1.
--
-- The workbench is the asset module (ADR 0068): one brief in, one row per generation round
-- of a part out. `workbench_brief` is the 創意簡報 of CONTEXT.md; `workbench_output` is the
-- Nth round of one part (copy / image_prompt / video_script / free) of that brief.
-- `source_ref` stores a schedule node's identity (node_key + source_tree_task_id) without
-- interpreting it -- the workbench knows no tree (ADR 0068 rule 2, container contract "Must
-- not import or touch": app.schedule). `workbench_output`'s four provider columns are the
-- image-generation seat: nullable, unwritten today (ADR 0068 rule 1, decision "What we looked
-- at" -- the seat is reserved, not filled, in this goal).
--
-- Named `_baseline.sql` (not merely convention -- app/tests/test_migration_ownership.py's
-- ownership() only learns a module's owned tables from `*_baseline.sql` files).
--
-- Dormant here (ticket 02's done-check 6): this migration plus repository.py's cleanup
-- registration are the whole change. Nothing outside app/tests calls this package yet --
-- ticket 03 (routes) and ticket 05 (schedule handoff) are the first real callers.
CREATE TABLE workbench_brief (
    id TEXT PRIMARY KEY,                       -- wbb_*, via db.new_id("wbb")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    kind TEXT NOT NULL CHECK (kind IN ('ad_creative','copy','image_prompt','video_script','free')),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('schedule_node','manual')),
    source_ref jsonb NOT NULL DEFAULT '{}'::jsonb,   -- schedule_node: {"node_key","source_tree_task_id","node_name"}
    product_id TEXT REFERENCES product(id),
    audience_key TEXT, pain_key TEXT, angle_key TEXT, hook_key TEXT,
    proof_key TEXT, offer_key TEXT, format_key TEXT,
    coordinates_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    visual_tone TEXT CHECK (visual_tone IN ('暗調強對比','暖調生活')),
    visual_concept TEXT,
    style_key TEXT NOT NULL DEFAULT 'ugc',          -- a key of app/workbench/image_styles.json (ADR 0068 §7); no CHECK, the catalogue grows without a migration
    request_json jsonb NOT NULL DEFAULT '{}'::jsonb, -- {"use_brand_knowledge": bool, "free_text": str|null, "image_prompt_count": int|null}
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','done','failed','closed')),
    last_error TEXT,
    closed_at timestamptz,
    created_by TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workbench_brief_org_id_idx ON workbench_brief(org_id);
CREATE INDEX idx_workbench_brief_brand_id ON workbench_brief(brand_id);

CREATE TABLE workbench_output (
    id TEXT PRIMARY KEY,                       -- wbo_*, via db.new_id("wbo")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    brief_id TEXT NOT NULL REFERENCES workbench_brief(id) ON DELETE CASCADE,
    part TEXT NOT NULL CHECK (part IN ('copy','image_prompt','video_script','free')),
    generation_round integer NOT NULL DEFAULT 1,
    body_json jsonb NOT NULL,                  -- the validated reply + {"validation": [...], "rendered": [...]}
    coordinates_json jsonb,                    -- copy part: the seven labels the model answered
    adopted_at timestamptz,
    llm_task_id TEXT,
    storage_key TEXT, provider TEXT, provider_job_id TEXT, provider_status TEXT,  -- image-generation seat, ADR 0068 §1; unwritten
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brief_id, part, generation_round)
);
CREATE INDEX workbench_output_org_id_idx ON workbench_output(org_id);
CREATE INDEX idx_workbench_output_brand_id ON workbench_output(brand_id);

-- RLS + grants + org-isolation policy, copied verbatim (per-table shape, ADR 0052) from
-- 20260908000002_schedule_imported_ad.sql:41-49 -- every org_id table carries at least one
-- authenticated-scoped policy, no exemption list (app/tests/test_rls_tenant_policy.py::
-- test_every_org_table_has_an_authenticated_policy).
ALTER TABLE workbench_brief ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON workbench_brief TO authenticated;
DROP POLICY IF EXISTS workbench_brief_org_isolation ON workbench_brief;
CREATE POLICY workbench_brief_org_isolation ON workbench_brief
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

ALTER TABLE workbench_output ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON workbench_output TO authenticated;
DROP POLICY IF EXISTS workbench_output_org_isolation ON workbench_output;
CREATE POLICY workbench_output_org_isolation ON workbench_output
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
