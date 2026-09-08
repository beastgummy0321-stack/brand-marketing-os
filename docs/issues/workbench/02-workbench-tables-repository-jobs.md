# 02 — workbench module: tables, repository, generation jobs (dormant, no route, no screen)

route=C: schema (two new tables, a new migration-owning module) and a module boundary (new
package `app/workbench/`, ADR 0068). Serves the board row 素材工作檯 (spec.md in this folder).
Ticket 01 landed the methodology and task files this module reads; this ticket is the module's
body. Nothing calls it yet except tests — the first callers are ticket 03 (routes) and 05
(schedule). Dormant by design (workflow: structure first, flip later).

## What

### 1. Migration `supabase/migrations/<UTC ts>_workbench_baseline.sql`

Named `_baseline.sql` because `app/tests/test_migration_ownership.py::ownership()` learns which
module owns a table **only from `*_baseline.sql` files** (`:35-45`); `MODULES` (`:16`) gains
`"workbench"` in the same commit. Header comment in the style of
`20260908000002_schedule_imported_ad.sql` (module, ticket, ADR 0068 §1). Two tables, both with
`org_id` NOT NULL REFERENCES organisation(id), `brand_id` NOT NULL REFERENCES brand(id), indexes
on both, and the RLS + grant + policy block **copied verbatim** from that file's tail
(`test_rls_tenant_policy.py` requires one authenticated policy per org table).

```sql
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
```

### 2. Package `app/workbench/`

Read `app/schedule/__init__.py`, `app/schedule/repository.py` (cleanup registration at `:694`),
`app/schedule/jobs.py` (`register_tasks()` at `:730`, the prompt join order in
`schedule_creative()` `:575-636`) and `app/meta/__init__.py` first; copy their shape.

- `__init__.py` — exactly the five exports in `docs/contracts/workbench.md` "Exported shapes"
  (`register`, `register_tasks`, `submit_brief`, `briefs_for_source`, `adopted_output`), lazy
  imports like `app/schedule/__init__.py`. `register()` mounts a router that has **no routes yet**
  (ticket 03) — it exists so `app/main.py`'s loop can include it.
- `repository.py` — inserts/reads for the two tables; `cleanup.register("素材工作檯", …)` covering
  both tables (`app/core/cleanup.py:17`), brand dimension only, product dimension `None`-shaped
  the way a module without product rows does it (read the docstring at `cleanup.py:22`).
  `submit_brief` writes the brief with `status='queued'` and enqueues one
  `background.workbench_generate` per part in `brief["parts"]` (today: `["copy"]` for
  `ad_creative`/`copy`; `["image_prompt"]` only when `request_json.image_prompt_count` is set;
  `["video_script"]`, `["free"]` for those kinds), lock `f"workbench:{brief_id}:{part}"`.
- `jobs.py` — one procrastinate task `workbench_generate(org_id, brand_id, brief_id, part, *,
  count=None)`, registered by `register_tasks()` exactly like `schedule.jobs.register_tasks()`
  (name `background.workbench_generate`). Body, in order: mark brief `running` → build the prompt
  (`prompts.py`) → `gateway.run_task(conn, PROVIDER, brand_id=…, task_type=f"workbench_{part}",
  prompt_template_id=f"workbench_{part}", prompt_template_version="v1", …, options=
  TaskOptions(max_tokens=16000, timeout_s=480.0), context=TaskContext(context_scope={"brand_id",
  "brief_id", "part"}, …))` → `validate.parse_json_only(rendered_output)` (anything but one JSON
  object = failure, `last_error` = 「代理沒有回傳純 JSON，請重新產出一次。」) → `validate.check_<part>()`
  → items that fail their band are re-asked **once, together, in one follow-up `run_task` call**
  whose prompt is the task file's 「修正」 section plus the failing items and their constraints
  (`app/departments/workbench/fix.md`, new, JSON-only reply `{"replacements": [{"path": "bodies.long[1]", "value": "…"}]}`); the batch is never regenerated (ADR 0068 §6) → write
  `workbench_output` with `generation_round` = max+1 for that part, `body_json` carrying the
  reply, `validation` (one line per check, ✅/❌ text) and, for `image_prompt`, `rendered` (the N
  rendered 14-line prompts) → brief `done`. Any exception or a failed `llm_task` → brief `failed`
  + `last_error`; the exception is not swallowed.
- `image_styles.json` — the capture-style catalogue (contract page, module-local decision):
  `[{"key": "ugc", "label": "UGC 手機實拍", "capture_line": "UGC 手機實拍，現場光", "authenticity_hint": "手機視角、生活雜物與不完美構圖是特色，不是缺點"}]`
  — one entry today. `repository.submit_brief` rejects an unknown `style_key` with
  `ValueError("style_unknown")` (routes map it to 400 in ticket 03).
- `prompts.py` — pure functions: `brief_text(brief, product_name, style)`, `copy_prompt(...)`,
  `image_prompt_prompt(..., headlines, count, style)`, `render_image_prompt(fixed, variable)` (the
  **nine-line** format from `app/methodology/image-prompt-template.md` §2, `subject` prefixed
  「見參考商品照，」 by the shell — copy `render_prompt` from `scripts/workbench_probe.py:80`
  unchanged before deleting the script). The 工單 text carries the style's `label` and
  `authenticity_hint` on one 「風格：」 line. The copy prompt joins:
  `app/departments/workbench/copy.md` · `methodology.compile(conn, ["素材工作檯文案"], brand_id)` ·
  brief text · brand context (`context_compiler.compile(conn, brand_id, product_id)` when
  `use_brand_knowledge` and a product; else nothing) · coordinate vocabulary **last** (schedule
  contract "Position in the prompt decides"; the vocabulary text function is **copied** from
  `app/schedule/jobs._coordinate_vocabulary_text` into this package — schedule internals are
  private, container contract rule 5 allows the copy).
- `validate.py` — the validators ticket 01 wrote in `scripts/workbench_probe.py`, moved here
  unchanged in behaviour: `parse_json_only`, `check_copy` (5/3/2 counts, bands 100–150 /
  300–500 / 800–1000 by `len()` without line breaks, 5 headlines ≤27, 5 descriptions ≤30, seven
  coordinates each present among the brand's `brand_coordinate` labels for its dimension),
  `check_image_prompts` (count == N, each rendered prompt 200–250 字, the six `fixed` strings
  verbatim in every rendered prompt), `check_video_script` (script count == request, each
  non-empty — no length band: `meta-format-specs.md:52-53` leaves scripts unbudgeted, ADR 0047).
  Returns a list of `{"path", "ok", "message"}`.

`scripts/workbench_probe.py` is **deleted** in this ticket (its validators live here now, its
purpose — the user reading one node's output — is served); its `--selftest` fixtures become
`app/tests/test_workbench.py` cases.

### 3. Registration and gates

- `app/main.py`: `from app import workbench as workbench_module`, add it to the register loop
  tuple **before `dashboard_module`**, call `workbench_module.register_tasks()` beside
  `schedule_module.register_tasks()`, and add `"素材工作檯"` to `_REQUIRED_CLEANUP_MODULES`.
- `app/tests/test_architecture_boundaries.py:483` `LAYER_ORDER`: insert `"app.workbench"`
  immediately **before `"app.schedule"`** (schedule may import workbench; workbench may import
  core, background, llm, shared, identity, brand_intelligence — all already above it). Comment
  cites ADR 0068 §2. `MODULES_WITHOUT_CONTRACT` is not edited (the page exists).
- `app/tests/test_migration_ownership.py:16` `MODULES` gains `"workbench"`.
- `app/llm/providers.py`: `TASK_TYPE_LABELS` gains four rows (`workbench_copy` 「素材工作檯：文案」,
  `workbench_image_prompt` 「素材工作檯：圖片提示詞」, `workbench_video_script` 「素材工作檯：影片腳本」,
  `workbench_free` 「素材工作檯：自由生成」) and `TASK_DEFAULTS` gains the same four with
  `{"model": None, "thinking": "high"}` for copy and `"medium"` for the other three — needed now
  because `gateway.run_task` → `resolve_model(task_type)` and the settings table read these
  dicts; the dead `creative_*` rows are ticket 06's.
- ADR 0068 frontmatter `applies-to` gains `app/workbench/` and `app/departments/workbench/`
  (the index refuses paths that do not exist; both exist after this ticket).
- `docs/contracts/workbench.md`: replace the sentence "Until ticket 02 lands … not a description
  of code" with the landing date; nothing else.
- Prompt caching check (spec, plan review): read `app/llm/providers.py` `AnthropicProvider` and
  the pinned SDK's documentation (`anthropic==0.122.0`, `pyproject.toml:10`) for whether a
  `cache_control` block on the methodology section is supported; **report the finding** with the
  doc URL — do not implement it in this ticket.

### 4. `app/tests/test_workbench.py` (new)

Copy the fixture shape of `app/tests/test_schedule.py:626-640` (test `background.app()`, call
`register_tasks()` again, `FakeProvider` at `:175`). Cases, one each:

1. `submit_brief` for a manual `copy` brief → one `workbench_brief` row `queued`, one queued job;
   running the worker with a FakeProvider whose reply is the literal JSON of
   `app/departments/workbench/copy.md` → one `workbench_output` (`part='copy'`, round 1, all
   validation lines ✅), brief `done`.
2. FakeProvider reply wrapped in prose (「以下是文案：{…}」) → no output row, brief `failed`,
   `last_error` is the JSON-only message.
3. `image_prompt` part with `count=3`: reply whose second prompt alters a `fixed` string → the
   fix call runs once (FakeProvider sequence), and the stored `validation` shows the fixed-block
   line ❌ if still wrong; a 260-字 rendered prompt likewise. (The selftest fixtures from ticket 01.)
4. Rounds: a second `image_prompt` run writes `generation_round=2`; adopting round 1 sets
   `adopted_at` on that row only; `adopted_output()` returns it and, with nothing adopted, the
   latest round.
5. Isolation: `briefs_for_source` under org A never returns org B's brief with the same
   `source_ref` (two orgs, same `source_tree_task_id` string).

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_workbench.py -q` green; test 3 proven red once by disabling the fixed-block comparison in `validate.check_image_prompts` (paste the red line), then restored.
3. `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py app/tests/test_migration_ownership.py app/tests/test_rls_tenant_policy.py -q` green (schema ticket set + the two lists this ticket edits).
4. `uv run pytest app/tests/test_methodology.py app/tests/test_schedule.py -q` green (the methodology README rows and the untouched schedule paths).
5. `supabase db reset` applies the new migration cleanly (paste the last three lines of its output); then `git grep -n "REFERENCES workbench_"` shows only this migration.
6. `cd frontend && npm run e2e` green (starts the 8720 backend itself; the backend must boot with the new module registered — this is the check that `register()` with an empty router and the cleanup assertion both hold).
7. `git diff --name-only` ⊆ Shared files touched + the new files; `scripts/workbench_probe.py` appears as deleted.

## Shared files touched

PASTED AT STATION ① BEFORE DISPATCH — every name below is searched repo-wide with `git grep -n`
and the hits are pasted here. Names that change meaning in this ticket: `LAYER_ORDER`,
`MODULES` (migration ownership), `_REQUIRED_CLEANUP_MODULES`, `TASK_TYPE_LABELS`, `TASK_DEFAULTS`,
`workbench_probe`, the register loop tuple in `app/main.py`, `applies-to` of ADR 0068.

## Contradiction check

- Done-check 3 (`LAYER_ORDER` unknown-package assertion, `test_architecture_boundaries.py:531`)
  vs done-check 6 (backend boots with the module registered): both pass if `app.workbench` is
  placed *above* `app.schedule` — and also pass if placed *below* it, as long as no schedule
  import exists yet (ticket 05 adds it). The input that shows the wrong placement is ticket 05's
  first `from app import workbench` inside `app/schedule/jobs.py`: with workbench below schedule
  the layer test goes red then. This ticket fixes the position now (before schedule) so ticket 05
  cannot pass by moving it.
- Done-check 2 test 3 (a fix call runs once) vs ADR 0068 §6 ("re-asked alone, the batch is never
  regenerated"): a fix call that resends the whole original prompt and replaces every item
  satisfies "once" and violates "alone". The FakeProvider sequence in test 3 must assert the
  second call's prompt names only the failing paths.
- Cheapest wrong implementation that leaves every check green: `parse_json_only` implemented as
  "find the last `{…}` in the text" (prose tolerated — test 2 must feed prose *after* the JSON
  too, not only before); validation that counts `len()` on the model's `theme` string instead of
  the shell-rendered prompt; `adopted_output()` returning the latest round even when an older one
  is adopted (test 4 adopts round 1 after round 2 exists).
