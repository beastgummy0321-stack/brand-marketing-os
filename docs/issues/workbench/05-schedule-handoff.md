# 05 — schedule → workbench handoff: a successful tree submits briefs, copy is taken on the schedule page, `schedule_creative` retires

route=C: module boundary (schedule now depends on workbench, ADR 0068 §2) and the one global
behaviour flip of this goal (tree success → copy generated without a button). No schema change:
ADR 0068 §3 amended 2026-09-09 — `creative_slot` gains no column; the slot is found by
`(node_key, source_tree_task_id)`, which the brief's `source_ref` carries. Serves the board row
素材工作檯 (spec.md in this folder). Tickets 02–04 landed the module, its API and its screen; this
ticket makes the schedule its first customer and deletes the path it replaces.

## What

### 1. Tree success submits one brief per deepest node (`app/schedule/jobs.py`)

`schedule_tree()` (`jobs.py:510-572`) ends at `gateway.run_task(...)` and discards the row. It now
keeps the row; when `row["status"] == "succeeded"`, it reads the tree back
(`binding_mod.tree_with_bindings(conn, row, org_id, brand_id)` → `state._leaf_ad_nodes(tree["nodes"])`
— the same two calls `routes._run_creative` used) and, for each leaf in document order, calls the
workbench entry point:

```python
from app import workbench  # module entry point only (docs/contracts/workbench.md)
workbench.submit_brief(conn, org_id, brand_id, {
    "kind": "ad_creative", "source_kind": "schedule_node",
    "source_ref": {"node_key": leaf["node_key"], "source_tree_task_id": row["id"], "node_name": leaf["name"]},
    "product_id": product_ids[0] if product_ids else None,
    "coordinates": None, "visual_tone": None, "visual_concept": None, "style_key": "ugc",
    "request": {"use_brand_knowledge": True, "product_ids": product_ids},
}, created_by="system")
```

Each `submit_brief` runs in its own try/except: a failure for one node is logged
(`logging.getLogger(__name__).exception`) and the loop continues — the tree row is already
committed by `run_task` and is never rolled back by a brief. `product_ids` is what the job already
resolves from the plan row (`jobs.py:590-595` in the retiring function; keep that read).

### 2. The workbench copy call carries the visual direction (ADR 0068 §5 amendment)

- `app/departments/workbench/copy.md`: two more top-level keys in the reply, literally
  `"visual_tone": "暗調強對比" | "暖調生活" | null` and `"visual_concept": "…一到兩句話的畫面概念…"`,
  with the same wording `ad_creative.md` used for them (copy the two bullets, then delete that
  file in §4). Still a flat object.
- `app/workbench/validate.py::check_copy`: `visual_tone` must be one of the two values or null;
  `visual_concept` a non-empty string — one validation line each.
- `app/workbench/jobs.py::_run` (copy part): after a valid reply, write `visual_tone` /
  `visual_concept` onto the brief (new `repository.update_brief_visual(conn, org_id, brand_id,
  brief_id, tone, concept)`) and keep them in `body_json`.
- `app/workbench/prompts.py`: brand context is compiled for **every** id in
  `request.product_ids` (falling back to `[product_id]`) when `use_brand_knowledge`, joined by a
  blank line — the shape `schedule.jobs._compile_brand_context` had (`jobs.py:60-80`; copy it, do
  not import).

### 3. Schedule reads the workbench and seeds its own memory (`app/schedule/state.py`)

`_brand_response()` (`state.py:172-217`): the `creative` block (`:189-204`) is replaced by
`"briefs": _briefs_for_tree(conn, org_id, brand_id, tree_row)`:

```python
briefs = workbench.briefs_for_source(conn, org_id, brand_id, "schedule_node",
                                     {"source_tree_task_id": tree_row["id"]}) if tree_row else []
```

per brief → one entry, literally:

```json
{"node_key": "1.1.1", "node_name": "…", "brief_id": "wbb_…", "status": "done", "last_error": null,
 "copy": {"is_adopted": true, "generation_round": 1,
          "short": ["…"], "medium": ["…"], "long": ["…"], "headlines": ["…"], "descriptions": ["…"],
          "visual_tone": "暗調強對比", "visual_concept": "…", "validation": [{"path": "long[1]", "ok": false, "message": "…"}]} ,
 "image_prompts": {"generation_round": 1, "count": 6} | null}
```

`copy` = `workbench.adopted_output(conn, …, brief_id, "copy")` (adopted, else latest, else
`null`); `image_prompts` = the same for `image_prompt`, reduced to round and count. Deepest nodes
of the current tree with no brief (older trees, a failed submit) appear with `brief_id: null`,
`status: "missing"`.

**Sync (ADR 0068 §3):** for every entry whose `copy.is_adopted` is true, call the existing
`schedule_repo.persist_creative_result(conn, org_id, brand_id, task_id=<output llm_task_id>,
source_tree_task_id, ads=[…])` with one `ad` shaped as it already expects:
`{"node_key", "coordinates": output.coordinates_json, "visual_tone", "visual_concept",
"fields": [{"label": "主要文字（短）", "value": short}, {"label": "主要文字（中）", "value": medium},
{"label": "主要文字（長）", "value": long}, {"label": "標題", "value": headlines}, {"label": "說明", "value": descriptions}]}`.
Its `llm_task_id` guard makes the call idempotent; zero new persistence code. `performance.py`
reads `creative_candidates_for_brand` unchanged.

### 4. Retirement — callers to zero, then delete

Delete, in this order, re-running `git grep` after each step so nothing dangles:

- `app/schedule/routes.py`: `create_creative` (`:487-491`), `_run_creative` (`:219-244`),
  `NO_TREE_TO_GENERATE_CREATIVE_MESSAGE` (`:183`), the module docstring lines about
  `ad_creative.md` (`:12-15`).
- `app/schedule/jobs.py`: `schedule_creative` (`:575-637`), `_creative_params_text` (`:110-117`),
  the `_JOBS` entry (`:725`), docstring line `:14`.
- `app/schedule/state.py`: `CREATIVE_TASK_TYPE`, `CREATIVE_METHODOLOGY_TASK_LABELS`,
  `CREATIVE_DEPARTMENT_FILE` (`:34-55`), `_creative_ad_nodes` (`:145-170`), the `creative_mod`
  import if nothing else in the file uses it.
- `app/schedule/creative.py`: `build_creative`, `creative_from_task_row`, `_valid_creative_fields`,
  the three `*_MESSAGE` constants and the `plan`/`tree` imports they needed. **Keep**
  `COORDINATE_KEYS`, `VISUAL_TONE_VALUES`, `_valid_coordinates`, `_valid_visual_tone`,
  `_valid_visual_concept` (callers: `routes.py:607`, `performance.py`, `repository.py`; verify by
  grep, delete any of the five that ends with zero callers). Rewrite the module docstring to one
  paragraph: the coordinate vocabulary constants of the loop, ADR 0068 §5.
- `app/departments/creative/ad_creative.md` deleted; `app/departments/creative/` deleted when
  empty. `app/methodology/README.md:40` row 「廣告內容生成」 deleted.
- `app/llm/providers.py`: the `schedule_creative` rows in `TASK_TYPE_LABELS` (`:137`) and
  `TASK_DEFAULTS` (`:159`) deleted (app/llm shrinks; `KNOWN_MODULE_SIZES["app/llm"]` is lowered
  to the measured value — down is always allowed).
- `app/dashboard/routes_jobs_api.py:40` row → `"workbench_generate": ("workbench_generate", "素材生成中")`
  and the tuple at `:64` names `workbench_generate` instead of `schedule_creative` (the bell
  aggregates `llm_task` rows by `task_type`; workbench tasks are `workbench_copy` /
  `workbench_image_prompt` / … — read `_queue_active_jobs` and key the row on whatever it
  actually matches; if it matches `task_type` prefixes, one row per `workbench_*` type).
- `frontend/src/lib/jobsApi.ts:10,33`: `schedule_creative` → `workbench_generate: "素材生成"`
  (or the per-type keys, mirroring the backend row).
- Tests: `app/tests/test_schedule_creative.py` deleted (its subject is deleted);
  `app/tests/test_schedule.py` — `BuildCreativeTest` (`:151-…`), the T1 `build_creative` cases
  (`:480-575`), the creative-route cases (`:876-930`, `:2440-2480`, `:2573`, `:2650-…`) deleted or
  rewritten against §3 (one case: an adopted copy output on a schedule-node brief →
  `creative_candidate` row with the seven keys, idempotent on a second read);
  `app/tests/test_dashboard_jobs_boundary.py:51,63,86` → the new kind;
  `app/tests/test_methodology.py:390-398` (the `ad_creative.md` tail of
  `Adr0047VisualDirectionGateTest`) deleted, the scan above it kept; `:24`
  `test_real_readme_parses_known_task_labels` updated if it names 「廣告內容生成」.
  `TEST_LINES_CEILING` and `KNOWN_MODULE_SIZES["app/schedule"]` set to the measured values
  (both go down).
- `docs/adr/0047-…md`: `decision:` reworded to
  `One visual direction per ad node travels with its copy from the workbench; a finished image prompt exists only there.`
  and a dated amendment paragraph at the top of the body naming ADR 0068 §5; `applies-to` gains
  `app/workbench/` and drops `app/departments/creative/`.
- `docs/contracts/schedule.md`: allowed dependencies gain `app.workbench` (entry point only);
  "Exported shapes" unchanged; the `creative` paragraphs under decisions in force (the T3d
  node-matching rule) are marked retired with this ticket's date — the matching problem no longer
  exists because each brief is one node.

### 5. Frontend — copy is taken on the schedule page

- `frontend/src/lib/scheduleApi.ts`: delete `CreativeField`/`CreativeCoordinates`/`CreativeAd`/
  `CreativeResult`/`generateCreative` (`:124-160`, `:425-445`); `ScheduleState.creative` →
  `briefs: ScheduleBrief[]` typed exactly as §3's JSON.
- `SchedulePage.tsx`: remove `creativeError`, `generatingCreative`, `handleGenerateCreative`
  (`:60`, `:266`, `:316`), the `creative` props passed to `CampaignTree` (`:334`); `running`
  (`:182`) also true while any brief is `queued`/`running` (the existing 2 s poll then covers the
  copy generation). Fourth stage tab `{ value: "assets", label: "素材準備", icon: … }` after
  投放結構 (design-system §5.1 already lists the stage).
- `CampaignTree.tsx`: remove the 產素材 button and the `creative*` props (`:20-25`, `:44`, `:56-57`);
  the selected node's right pane gains one line 「素材：處理中／文案完成／失敗／尚未建立」 from
  `briefs` by `node_key`, with 「到素材準備」 (`changeTab("assets")`).
- New `frontend/src/components/schedule/CreativePackList.tsx` for the 素材準備 stage: one
  `surface` per deepest node (tree document order): node name · status badge · 「屬於先前結構」
  `secondary` badge when the brief's tree id ≠ `schedule.tree.task_id`; `ui/tabs` 短版／中版／長版
  with `LENGTH_HINTS` from `@/lib/workbenchApi` (ticket 03) above each list; every variant, headline
  and description with `CopyIconButton`; a ❌ line verbatim under a variant that missed its band;
  「圖片提示詞：尚未產／已產 N 條」 + `Link` to `/brands/:brandId/workbench?brief=<id>` 「到工作檯」;
  status 處理中 → `Skeleton` in place of the tabs; 失敗 → `role="alert"` with `last_error` and a
  link to the workbench (再產一輪 lives there, not here — one producer). Empty (no tree) →
  `EmptyState` 「先展開投放結構」.
- `frontend/e2e/smoke.spec.ts` / `width-overflow.spec.ts`: if either clicks 產素材 or asserts the
  `creative` field, update to the new tab (grep `產素材|creative` in `frontend/e2e/` first).

### 6. Docs

- `docs/design-system.md` §5.1 row 素材準備: `| 素材準備 | one card per deepest node | copy tabs 短／中／長 with the fixed hint, headlines, descriptions, copy buttons; image-prompt count + link to 素材工作檯 |`.
- `CONTEXT.md` 投放包 entry: unchanged (already describes this).

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_schedule.py app/tests/test_schedule_performance.py app/tests/test_workbench.py app/tests/test_workbench_api.py app/tests/test_dashboard_jobs_boundary.py app/tests/test_methodology.py app/tests/test_llm_gateway.py -q` green; the new §3 sync case proven red once by returning `[]` from `_briefs_for_tree` (paste the red line), then restored.
3. `uv run pytest app/tests/test_architecture_boundaries.py app/tests/test_migration_ownership.py -q` green — `LAYER_ORDER` already places workbench before schedule (ticket 02); the new import direction is the one it allows.
4. `git grep -n "schedule_creative\|_run_creative\|build_creative\|creative_from_task_row\|ad_creative.md\|廣告內容生成\|generateCreative\|onGenerateCreative\|CreativeResult"` returns **only** ADR bodies and `docs/contracts/schedule.md`'s dated retirement lines (paste the output).
5. `cd frontend && npm run build && npm run lint && npm test` green; `cd frontend && npm run e2e` green.
6. FakeProvider end-to-end in `test_schedule.py`: `POST …/tree` → worker → the tree row succeeded **and** one `workbench_brief` per deepest node exists with `source_kind='schedule_node'`, `status='queued'`; `GET …` (brand response) returns `briefs` with those `node_key`s and `status: "queued"`.
7. `git diff --name-only` ⊆ Shared files touched.
8. WALK on a **restarted** 8720 backend, fresh browser, `brd_bughunt`, codex_cli:
   1. 檔期規劃 → 方案比較 → 用這個方案展開 → 投放結構 renders; **no 產素材 button** anywhere on the page (screenshot).
   2. 素材準備 tab: one card per node, 處理中 with skeletons; wait ≤ 3 min; cards turn 完成 with three tabs, 5/3/2 variants, 5 headlines, 5 descriptions, copy icons; a ❌ line appears under any variant outside its band (expected with the local model — it is shown, not hidden).
   3. Click a copy icon → clipboard holds that variant.
   4. 「到工作檯」 → `/brands/…/workbench?brief=<id>` opens that brief selected; 採用這一輪 there → back on 素材準備 the card shows 已採用; `SELECT count(*) FROM creative_candidate WHERE llm_task_id = <output.llm_task_id>` = 1 after the page reload, still 1 after a second reload.
   5. Top-right bell during step 2 shows 素材生成 (not 「目前沒有進行中的背景工作」).
   6. 投放結構 selected-node pane shows 「素材：文案完成 · 到素材準備」.

## Shared files touched

Searched 2026-09-09 with `git grep -n -F <name>` (docs/issues/workbench and docs/adr/retired excluded); hits pasted. Every name below stops existing or changes meaning.

`schedule_creative` (task type retires):
```
app/dashboard/routes_jobs_api.py:40, :64
app/llm/providers.py:137, :159
app/schedule/creative.py:9, :178
app/schedule/jobs.py:14, :238, :476, :575, :577, :725
app/schedule/repository.py:5, :36, :323   (docstrings naming the migration file / the retiring writer — text only)
app/schedule/routes.py:14, :224
app/schedule/state.py:36, :49
app/tests/test_architecture_boundaries.py:830, :838, :1192, :1262, :1761, :2209, :2228   (reason comments — leave)
app/tests/test_dashboard_jobs_boundary.py:51, :63, :86
app/tests/test_schedule.py:876, :2452, :2474, :2650
app/tests/test_schedule_creative.py:1
docs/adr/0042:27, :146 · docs/adr/0048:25 · docs/adr/0049:22   (history — leave)
```

`CREATIVE_TASK_TYPE`: `app/schedule/jobs.py:632, :633, :725` · `app/schedule/routes.py:235, :239, :240` · `app/schedule/state.py:36, :189` · `app/tests/test_schedule.py:922, :2573`
`CREATIVE_METHODOLOGY_TASK_LABELS`: `app/schedule/jobs.py:605, :607` · `app/schedule/state.py:50`
`CREATIVE_DEPARTMENT_FILE`: `app/schedule/jobs.py:601` · `app/schedule/state.py:55`
`_run_creative`: `app/schedule/jobs.py:9, :579, :588` · `app/schedule/routes.py:219, :491, :511` · `app/tests/test_architecture_boundaries.py:2230` (comment)
`creative_from_task_row`: `app/schedule/creative.py:27, :177` · `app/schedule/state.py:193` · `app/tests/test_architecture_boundaries.py:2229` (comment)
`build_creative`: `app/schedule/creative.py:49, :123, :194` · `app/schedule/repository.py:274` (comment) · `app/tests/test_schedule.py:151, :480, :484, :494, :505, :514, :523, :534, :545, :562, :2443`
`_creative_params_text`: `app/schedule/creative.py:43` · `app/schedule/jobs.py:110, :615` · `docs/contracts/schedule.md:178`
`_creative_ad_nodes`: `app/schedule/state.py:145, :192`
`persist_creative_result` (kept, gains a second caller): `app/schedule/repository.py:321` · `app/schedule/state.py:198, :201` · `app/tests/test_schedule_performance.py:156, :161` · `app/tools/simulate_meta_spend.py:6, :256`
`ad_creative.md`: `app/methodology/meta-format-specs.md:20` (prose → point at `app/departments/workbench/copy.md`) · `app/schedule/creative.py:13` · `app/schedule/routes.py:13` · `app/schedule/state.py:55` · `app/tests/test_methodology.py:390, :393` · `app/tests/test_schedule.py:582, :604` · `docs/adr/0047:20, :34` · `frontend/src/lib/scheduleApi.ts:124`
`廣告內容生成`: `app/methodology/README.md:40` · `app/schedule/state.py:50` · `app/tests/test_schedule.py:2454`
`generateCreative`: `frontend/src/components/schedule/SchedulePage.tsx:13, :266` · `frontend/src/lib/scheduleApi.ts:425`
`onGenerateCreative`: `frontend/src/components/schedule/CampaignTree.tsx:20, :25, :44` · `frontend/src/components/schedule/SchedulePage.tsx:334`
`CreativeResult`: `frontend/src/components/schedule/CampaignTree.tsx:8, :25` · `frontend/src/lib/scheduleApi.ts:152, :239`
`產素材` (UI string): `app/dashboard/routes_jobs_api.py:35, :36, :40` · `frontend/src/components/schedule/CampaignTree.tsx:44, :56` · `frontend/src/lib/jobsApi.ts:5, :33` · `app/tests/test_dashboard_jobs_boundary.py:48, :86` · `app/tests/test_schedule.py:878, :907` · `docs/issues/ui/issue-bind-success-is-silent.md:26`, `issue-creative-crashes-without-a-product.md` (that issue is **closed by this ticket** — its path no longer exists; delete the file), `issue-drill-wording-gaps.md:49`, `issue-period-page-has-no-history.md:22` (prose in other rows' issues — leave)
`Adr0047VisualDirectionGateTest`: `app/tests/test_methodology.py:358`

Files edited: `app/schedule/{jobs,state,routes,creative,repository}.py` (repository: docstring only), `app/workbench/{jobs,prompts,validate,repository}.py`, `app/departments/workbench/copy.md`, `app/methodology/README.md`, `app/methodology/meta-format-specs.md:20`, `app/llm/providers.py`, `app/dashboard/routes_jobs_api.py`, `app/tests/{test_schedule,test_dashboard_jobs_boundary,test_methodology,test_architecture_boundaries}.py`, `frontend/src/lib/{scheduleApi,jobsApi}.ts`, `frontend/src/components/schedule/{SchedulePage,CampaignTree}.tsx`, `frontend/e2e/*` if they reference the button, `docs/adr/0047-…md`, `docs/contracts/schedule.md`, `docs/design-system.md`.
Files created: `frontend/src/components/schedule/CreativePackList.tsx`.
Files deleted: `app/departments/creative/ad_creative.md` (and the folder), `app/tests/test_schedule_creative.py`, `docs/issues/ui/issue-creative-crashes-without-a-product.md`.

## Contradiction check

- Done-check 6 (briefs are `queued` right after the tree succeeds) vs the FakeProvider fixture
  that answers every `run_task` with the tree JSON: the workbench copy job, if it runs inside the
  same test worker loop, would parse the tree JSON as copy and fail → briefs `failed`, not
  `queued`. The test must run the worker once (tree) and assert before a second worker pass, or
  give the FakeProvider a sequence; whichever it does must be stated.
- §3 sync on `is_adopted` only vs done-check 8 step 4 (candidate appears after 採用): an
  implementation syncing the *latest* round instead of the adopted one leaves step 4 green (one
  round exists) but writes a fingerprint the user did not choose — the reviewer runs two rounds,
  adopts round 1, and checks the candidate's `llm_task_id` is round 1's.
- Cheapest wrong implementation that leaves every check green: keeping `schedule_creative` code
  behind a dead flag (done-check 4's grep catches names, not behaviour — it must return only the
  documented lines); syncing by writing `creative_candidate` directly from `state.py` instead of
  through `persist_creative_result` (done-check 8 step 4's idempotency then depends on new code —
  the reviewer diffs `repository.py` for new INSERTs).
