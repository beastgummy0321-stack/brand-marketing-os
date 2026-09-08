# 06 — free briefs and video scripts get their task files; 「彈性格式」 joins the format vocabulary; the module's pull-out proof; close-out

route=C: one data migration (a `brand_coordinate` row for every existing brand — schedule-owned
table, `schedule_` prefix) plus behaviour (two task files, two validators, one form field). Serves
the board row 素材工作檯 (spec.md in this folder). Ticket 05 landed the handoff and retired the old
path; this ticket fills the two dormant parts ticket 02 left (`video_script`, `free` raise
`FileNotFoundError` today) and closes the goal.

## What

### 1. `app/departments/workbench/video_script.md` (new)

Style of `copy.md`; JSON-only reply; the 工單 section carries the requested count. Methodology row
「素材工作檯影片腳本」 (`creative-matrix.md` §5 frameworks, `copywriting.md`, `humanizer-zh-tw.md`)
is already in `app/methodology/README.md:43`. Reply, literally:

```json
{
  "scripts": [
    {"title": "…", "framework": "…creative-matrix.md 第 5 節框架名稱原文…", "hook": "…前 3 秒…",
     "beats": [{"t": "0–3s", "visual": "…", "voice": "…", "text": "…字幕或圖上文字…"}],
     "cta": "…"}
  ],
  "hook_pool": ["…", "…"],
  "warnings": []
}
```

`scripts` has exactly the requested count (1–5); each script ≥3 beats; `hook_pool` ≥ count.
`app/workbench/validate.py::check_video_script` (exists, `:155`) is completed to those three checks
plus `framework` non-empty; no length band (`meta-format-specs.md:52-53`, ADR 0047).

### 2. `app/departments/workbench/free.md` (new)

Free generation: the 工單's `request.free_text` is the whole brief; brand context when
`use_brand_knowledge`. Reply, literally: `{"items": [{"label": "…", "value": "…"}], "warnings": []}`
— labelled blocks, any number ≥1, labels chosen by the model, values plain text without line
breaks inside a value (use several items instead). `validate.check_free(data)`: `items` non-empty
list of `{label: str, value: str}` — that is the whole gate (`jobs.py:83` currently returns `[]`).
`app/methodology/README.md` gains the row `| 素材工作檯自由生成 | `humanizer-zh-tw.md` |` and
`jobs.py:34-41`'s label map gains `"free": "素材工作檯自由生成"`.

### 3. Count for video scripts — API and form

- `app/workbench/routes.py` run route (ticket 03): `{"count": 1–5}` is **required** for
  `part=video_script` too; `count_out_of_range` 400 otherwise. `repository.run_part` passes it.
  Contract page "Routes" line updated in the same commit.
- `frontend/src/components/workbench/NewBriefPanel.tsx` (ticket 04): when 種類 = 影片腳本, one
  numeric `Input` 「要幾支腳本」 (1–5, required, empty) → `request.video_script_count`;
  `repository._parts_for` enqueues `video_script` only when it is set (mirrors
  `image_prompt_count`). `BriefDetail.tsx` 影片腳本 card renders `scripts[]` as labelled blocks
  (title · framework · hook · beats table · cta) each with `CopyIconButton`, and `hook_pool`
  below; 再產一輪 asks the count again (same field, same rule, empty).
- `frontend/src/lib/workbenchApi.ts`: `runPart(brandId, id, part, count?)` already carries
  `count`; the `NewBrief.request` type gains `video_script_count`.

### 4. 「彈性格式」 joins the `format` dimension

- `app/schedule/repository.py:_SEED_COORDINATES["format"]` gains the row
  `("flexible", "Meta 版位", "彈性格式", "1～10 張同座標圖；asset_feed_spec images ≤10，2026-09-09 查證")`
  after `single_image` (`:169`) — new brands get it from `ensure_coordinates_seeded`.
- Existing brands do not: `ensure_coordinates_seeded` (`:176-207`) probes **per dimension** and
  skips `format` once any row exists. So one data migration
  `supabase/migrations/<ts>_schedule_brand_coordinate_flexible_format.sql`, schedule-owned (ADR
  0049), shaped like `20260904000002_schedule_brand_coordinate_six_dimensions.sql:90-94`:
  `INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json) SELECT 'crd_' || replace(gen_random_uuid()::text,'-',''), brand.org_id, brand.id, 'format', 'flexible', '彈性格式', 'Meta 版位', jsonb_build_object('situation', '…same text…') FROM brand ON CONFLICT (brand_id, dimension, key) DO NOTHING;`
  No table created, no column changed; `test_migration_ownership` sees the `schedule_` prefix.
- `app/methodology/meta-format-specs.md` §1 heading stays 「單圖 single_image」 (the API value still
  exists — ADR 0068 numbers table); add one sentence under it: 「彈性格式＝同一座標 1～10 張，走
  `flexible` 座標值」. `CONTEXT.md` 廣告素材: one line under 素材檔 or 風格 defining 彈性格式 in
  plain words (the user's 2026-09-09 description: 1～10 張同主題圖減緩受眾疲勞).

### 5. Pull-out proof (container contract §6) — run, report, restore

In a throwaway state (`git stash` after committing nothing): delete `frontend/src/components/workbench/`,
its `App.tsx` route + import and the `BRAND_NAV` row → `cd frontend && npm run build` passes and
the e2e `smoke` still opens 經營概況. Backend: `app.schedule` imports `app.workbench` by design
(ADR 0068 §2 — the customer depends on the factory), so the backend half of the pull-out is
**not expected to pass** and is not run; write that sentence, with the ADR reference, into
`docs/contracts/workbench.md` under decisions in force. Restore with `git stash pop`; `git status`
must equal what it was before the proof.

### 6. Close-out bookkeeping (main chat does the board; you do the docs)

- `docs/contracts/workbench.md`: routes line for `video_script` count; error shapes unchanged;
  the pull-out sentence.
- `docs/contracts/schedule.md` "Decisions in force": one line — `format` dimension carries
  `flexible` since 2026-09-09 (ticket workbench/06), seeded by migration for existing brands.
- `app/methodology/README.md` 檔案索引 rows exist from ticket 01; only the new task row above.
- Ratchets: `TEST_LINES_CEILING` and `KNOWN_MODULE_SIZES["app/workbench"]` set to measured
  values with the reason `ticket workbench/06`; `app/schedule` row measured (one seed line).

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_workbench.py app/tests/test_workbench_api.py app/tests/test_methodology.py app/tests/test_schedule.py app/tests/test_migration_ownership.py app/tests/test_architecture_boundaries.py -q` green; two new cases in `test_workbench.py`: (a) FakeProvider `video_script` round-trip with `count=2` → output with two scripts, validation all ✅; a reply with one script → the fix call runs once and the stored validation shows ❌ on `scripts` count if still wrong; (b) `free` round-trip → `items` stored; a reply `{"items": []}` → ❌. Case (a) proven red once by disabling the count check.
3. `supabase db reset` applies the data migration; then `SELECT count(*) FROM brand_coordinate WHERE dimension='format' AND key='flexible'` equals `SELECT count(*) FROM brand` (paste both numbers) and a second `supabase db reset` yields the same (idempotent by `ON CONFLICT`).
4. `cd frontend && npm run build && npm run lint && npm test && npm run e2e` green.
5. Pull-out proof (§5) reported with the build's last line and `git status --short` before/after identical.
6. `git diff --name-only` ⊆ Shared files touched + the new files.
7. WALK on a restarted backend, fresh browser, `brd_bughunt`: (1) 素材工作檯 → 新工單 → 種類 影片腳本, 要幾支腳本 2, 需求說明 「30 秒開箱」 → 建立 → 處理中 → 完成 → two script blocks with title/framework/hook/beats/cta and copy icons; (2) 新工單 → 種類 自由生成, 需求說明 「寫三句 IG 限動貼文」 → 完成 → labelled blocks with copy icons; (3) 品牌智庫 → 創意座標 → 格式 lists 彈性格式; (4) 素材工作檯 新工單 kind 影片腳本 without a count → field error, no request.

## Shared files touched

Searched 2026-09-09 with `git grep -n -F` (docs/issues/workbench excluded); names that change meaning:

`_SEED_COORDINATES` (format gains a row): `app/schedule/repository.py:125, :196` · `app/schedule/jobs.py:125` (comment) · `app/tests/test_schedule.py:1931` (comment on `audience[0]` — the seeded-count assertion near `:2592` (68 rows ×2) **changes to 69** and its comment says why).
`check_video_script` (completed): `app/workbench/jobs.py:82` · `app/workbench/validate.py:155`.
`素材工作檯影片腳本` (unchanged row, now has a caller): `app/methodology/README.md:43` · `app/workbench/jobs.py:40` · ADR 0068 §9.
`ensure_coordinates_seeded` (unchanged; documented as the reason for the migration): `app/schedule/repository.py:23, :122, :176, :226, :337` · `app/tests/test_schedule.py:2592` · `app/workbench/repository.py:9, :233` · `supabase/migrations/20260904000002_…sql:11`.
`video_script` (part gains a task file and a count): `app/departments/workbench/fix.md:1` · `app/llm/providers.py:140, :163` · `app/workbench/jobs.py:35, :40, :81, :82, :144` · `app/workbench/repository.py:40, :47, :48` · `app/workbench/validate.py:155` · ADR 0050:112 · ADR 0068:27.
Plus ticket 03/04 files by name once they exist: `app/workbench/routes.py`, `frontend/src/lib/workbenchApi.ts`, `frontend/src/components/workbench/{NewBriefPanel,BriefDetail}.tsx` — re-run the scan for `image_prompt_count` at dispatch to place `video_script_count` beside it.

Files edited: `app/workbench/{jobs,validate,repository,routes}.py`, `app/schedule/repository.py`,
`app/methodology/README.md`, `app/methodology/meta-format-specs.md`, `app/tests/{test_workbench,test_schedule,test_architecture_boundaries}.py`,
`frontend/src/lib/workbenchApi.ts`, `frontend/src/components/workbench/{NewBriefPanel,BriefDetail}.tsx`,
`docs/contracts/{workbench,schedule}.md`, `CONTEXT.md`.
Files created: `app/departments/workbench/video_script.md`, `app/departments/workbench/free.md`,
`supabase/migrations/<ts>_schedule_brand_coordinate_flexible_format.sql`.

## Contradiction check

- Done-check 3 (`count(flexible) == count(brand)` after reset) vs `ensure_coordinates_seeded`'s
  per-dimension skip: a brand created *after* the migration and before its first coordinate read
  has zero `format` rows, then gets all of them from the Python seed — consistent only if the
  Python row and the SQL row share `key='flexible'` and the same label; a typo in either leaves
  done-check 3 green (counts match) and the vocabulary with two spellings — the reviewer diffs the
  two literals.
- Done-check 2(a) (count check red once) vs the fix call: the fix call may *add* a script to reach
  the count — then the stored validation is ✅ and the "still wrong" branch is never exercised; the
  test must feed a FakeProvider sequence whose fix reply is also short.
- Cheapest wrong implementation that leaves every check green: `check_free` accepting
  `{"items": [{"label": "", "value": ""}]}` (non-empty list of empty strings) — case (b) must
  include empty strings as ❌.
