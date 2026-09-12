-- supabase/migrations/20260912000001_workbench_pack.sql
-- Module: workbench (F02, ARCHITECTURE.md §5.1-§5.4, issue F02-I02).
--
-- 任務包 → 素材組 → 產物 → 版本 (ARCHITECTURE.md §5.1): display vocabulary only, no rename
-- of the code/DB names -- workbench_brief stays 素材組, workbench_output stays 版本, `part`
-- stays 產物類型. This migration adds the one new table (workbench_pack, 任務包) plus the
-- columns that let a brief belong to a pack and an output row be one selectable version
-- inside its generation round (ARCHITECTURE.md §5.2/§5.4).
--
-- grep -rn "REFERENCES workbench_brief" supabase/migrations/ before touching this file's
-- shape (CLAUDE.md) -- only 20260909000001_workbench_baseline.sql defines that table, no
-- other migration references it, so ADD COLUMN here is safe.
CREATE TABLE workbench_pack (
    id TEXT PRIMARY KEY,                       -- wbp_*, via db.new_id("wbp")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    name TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('schedule_node','free_job')),
    source_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
    summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,      -- 摘要：情境／角度／風格／目標受眾／重點訊息／參考連結
    context_json jsonb NOT NULL DEFAULT '{}'::jsonb,      -- brand/product/campaign ids
    constraints_json jsonb NOT NULL DEFAULT '{}'::jsonb,  -- e.g. copy_length, promotion_note (pack-level default)
    completion_json jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 完成條件 human ticks (F02-I03 writes them)
    approved_at timestamptz,
    closed_at timestamptz,
    created_by TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workbench_pack_org_id_idx ON workbench_pack(org_id);
CREATE INDEX idx_workbench_pack_brand_id ON workbench_pack(brand_id);

ALTER TABLE workbench_pack ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON workbench_pack TO authenticated;
DROP POLICY IF EXISTS workbench_pack_org_isolation ON workbench_pack;
CREATE POLICY workbench_pack_org_isolation ON workbench_pack
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

-- 一份 brief（素材組）永遠屬於一份 pack（任務包）——「a set only exists inside a pack」
-- (ARCHITECTURE.md §5.4). Nullable in SQL: no backfill of test data is worth a NOT NULL
-- dance (this ticket's Done text); `repository.py` never writes a brief without one.
ALTER TABLE workbench_brief ADD COLUMN pack_id TEXT REFERENCES workbench_pack(id) ON DELETE CASCADE;
ALTER TABLE workbench_brief ADD COLUMN name TEXT;
ALTER TABLE workbench_brief ADD COLUMN required_outputs_json jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX idx_workbench_brief_pack_id ON workbench_brief(pack_id);

-- 一個產物類型的一輪可能寫出不只一列（版本）——ARCHITECTURE.md §5.2: 一份 copy 回合寫 5 列，
-- 一份 image_prompt 回合寫 1 列（①＋② 那一對），一份 video_script 回合每支腳本一列.
-- `adopted_at` keeps its name and now means 選定 at version level.
ALTER TABLE workbench_output ADD COLUMN version_index integer NOT NULL DEFAULT 1;
ALTER TABLE workbench_output DROP CONSTRAINT workbench_output_brief_id_part_generation_round_key;
ALTER TABLE workbench_output
    ADD CONSTRAINT workbench_output_brief_id_part_generation_round_version_index_key
    UNIQUE (brief_id, part, generation_round, version_index);
