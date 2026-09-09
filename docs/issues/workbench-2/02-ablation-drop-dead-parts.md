# 02 — ablation: stop writing the eight dead columns, drop the dead 目標張數 input, read `capture_line`, show `warnings`, trim ADR 0068 §4

route=C: a module entry point changes signature (`workbench.submit_brief` loses `created_by`). No
schema change: the eight columns are nullable and have zero readers (`.scratch/ablation/inventory.md`,
2026-09-09; Opus plan review the same day: stop writing, no migration — the same-named `*_key`
columns on schedule tables are alive at `app/schedule/repository.py:352,524,629` and must not be
touched). Serves the board row 工作檯消融與閉環修正 (spec.md). The five parts the user chose to keep
(close/reopen, 帶品牌資料 switch, manual 圖片提示詞 + 圖上文字, 風格 dropdown, the four provider-seat
columns) are **not** touched.

## What

### 1. The eight columns stop being written

`app/workbench/repository.py:116-127` INSERT drops `audience_key, pain_key, angle_key, hook_key,
proof_key, offer_key, format_key, created_by` from the column list and the values;
`create_brief`'s signature (`:70`) and `submit_brief` (`app/workbench/__init__.py:8, :56-61`) lose
the `created_by` keyword; `routes.py:80` and the tree handoff in `app/schedule/jobs.py`
(`created_by="system"`) stop passing it; tests that pass `created_by=` are updated (grep
`created_by=` in `app/tests/test_workbench.py`, `app/tests/test_workbench_api.py`,
`app/tests/test_schedule.py`). The seven coordinate keys remain readable from
`coordinates_snapshot_json` (unchanged). `docs/contracts/workbench.md` §2 signature updated, and one
line under decisions in force: 「`workbench_brief.audience_key … format_key, created_by` unused
since 2026-09-09; drop them in the next workbench migration that touches the table」.

### 2. The dead 目標張數 input goes; the grey line stays

`frontend/src/components/workbench/BriefDetail.tsx:219, :292-293`: remove `targetCount`/
`setTargetCount` and the 「目標張數」 `Input`; the grey line (`copy.ts` `IMAGE_PROMPT_ADVISORY`,
「AI 生圖有不確定性，建議多產幾條備用，建議目標張數的 1.5 倍」) sits beside 「要幾條提示詞」. ADR 0068 §7
already names exactly one integer field (`:102`); the second input was a frontend-only extra.

### 3. `capture_line` is read

`app/workbench/prompts.py:35`: the 風格 line becomes
`風格：{label}（{authenticity_hint}）；攝影形式：{capture_line}` — the fixed block's 攝影形式 now comes
from the catalogue. `image_styles.json` unchanged; `frontend/src/lib/workbenchApi.ts:86` type unchanged.

### 4. `warnings` are shown

Every task file asks the model for `warnings` (the honest 「這是佔位，投放前核對」 lines); nothing renders
them (`CampaignTree.tsx`'s `warnings` is schedule's own, not this). `BriefDetail.tsx`: under each
part card, when `body_json.warnings` is a non-empty array of strings, a muted list titled 「模型的提醒」
(one `<li>` per string; design-system §8 vocabulary, muted token). The 投放包 shows the copy part's
warnings the same way: `app/schedule/state.py::_copy_summary` (`:141-150`) adds
`"warnings": [w for w in body.get("warnings") or [] if isinstance(w, str)]`,
`frontend/src/lib/scheduleApi.ts` `ScheduleBriefCopy` gains `warnings: string[]`,
`frontend/src/components/schedule/CreativePackList.tsx` renders the same list under the length tabs.
`docs/contracts/schedule.md` brand-response shape gains the key. Literal:

```json
{"copy": {"is_adopted": false, "generation_round": 1,
          "warnings": ["3 顆體驗包的價格是佔位，投放前請核對。"], "short": ["…"]}}
```

### 5. Docs

ADR 0068 §4 already shortened to one sentence by main chat (2026-09-09); `docs/contracts/workbench.md`
(§1 signature, the styles sentence now says `capture_line` is rendered into the fixed block, the
decisions-in-force line from §1).

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_workbench.py app/tests/test_workbench_api.py app/tests/test_schedule.py -q`
   green with one new case in `test_workbench.py`: a `copy` reply carrying two `warnings` strings and
   one non-string → the brief detail's output `body_json.warnings` has exactly the two strings, and
   the schedule brand response's `briefs[].copy.warnings` (through the existing tree-handoff fixture
   in `test_schedule.py`, or a second case there) carries the same two; a reply without `warnings`
   → `[]`. Proven red once by dropping the key from `_copy_summary`.
3. `uv run pytest app/tests/test_architecture_boundaries.py -q` green (ratchets measured).
4. `git grep -n "audience_key\|created_by" -- app/workbench app/schedule/jobs.py frontend/src/lib/workbenchApi.ts frontend/src/components/workbench` returns nothing; `git grep -n "targetCount"` returns nothing.
5. `cd frontend && npm run build && npm run lint && npm test && npm run e2e` green.
6. `git diff --name-only` ⊆ Shared files touched.
7. WALK (restarted 8720 backend + worker, fresh browser, `brd_bughunt` or any brand with a done copy
   brief — create one via 新工單 → 文案 if none): the copy card shows 「模型的提醒」 with ≥1 line when the
   reply carried warnings (if the list is empty, 再產一輪 once and check again; report either way);
   the 圖片提示詞 card has exactly one numeric field 「要幾條提示詞」 with the grey line beside it and no
   「目標張數」; enter 3 → 產提示詞 → 完成 → three prompts whose 攝影形式 segment contains the UGC
   `capture_line` text from `image_styles.json`; 檔期規劃 → 素材準備 shows 「模型的提醒」 under a card
   whose copy has warnings (screenshots of all three).

## Shared files touched

Searched 2026-09-09 with `git grep -n -F`:

- `audience_key` (workbench copy only): `app/workbench/repository.py:116` · `supabase/migrations/20260909000001_workbench_baseline.sql:28` (applied; not edited). Schedule's own `audience_key` at `app/schedule/repository.py:352,524,629` and elsewhere: **not touched**.
- `created_by`: `app/workbench/__init__.py:8, :56, :61` · `app/workbench/repository.py:70, :118, :127, :149, :157` · `app/workbench/routes.py:80` · `docs/contracts/workbench.md:22` · `supabase/migrations/20260909000001_workbench_baseline.sql:39` (applied) · `app/schedule/jobs.py` (grep `created_by="system"`) · tests (grep `created_by=`).
- `capture_line`: `app/workbench/image_styles.json:5` · `docs/contracts/workbench.md:99` · `frontend/src/lib/workbenchApi.ts:86`.
- `targetCount`: `frontend/src/components/workbench/BriefDetail.tsx:219, :292`.
- `warnings` (workbench sense): `app/departments/workbench/{copy,free,image_prompt,video_script}.md` (unchanged) · new readers in §4.
- `authenticity_hint`: `app/workbench/prompts.py:35` (the line that changes).

Files edited: `app/workbench/{__init__,repository,routes,prompts}.py`, `app/schedule/{jobs,state}.py`,
`app/tests/{test_workbench,test_workbench_api,test_schedule,test_architecture_boundaries}.py`,
`frontend/src/lib/{workbenchApi,scheduleApi}.ts`, `frontend/src/components/workbench/BriefDetail.tsx`,
`frontend/src/components/schedule/CreativePackList.tsx`, `docs/contracts/{workbench,schedule}.md`.
No file created.

## Contradiction check

- §1 vs the applied baseline still declaring the columns NOT NULL? Checked: all eight are nullable
  (`…_workbench_baseline.sql:28-29, :39`), so an INSERT without them succeeds; done-check 2 exercises
  `submit_brief` after the change.
- §4 vs ADR 0068 §6 「JSON-only reply」: showing `warnings` adds no parsing; the key was always in the
  object. A reply without it must still validate — done-check 2's third input.
- Cheapest wrong implementation leaving every check green: rendering `warnings` in the workbench only
  and forgetting the 投放包 (done-check 7's last step); leaving `created_by` accepted-and-ignored in the
  signature (done-check 4's grep); hard-coding the UGC capture text in `prompts.py` instead of reading
  the catalogue (done-check 7 passes — the reviewer reads `prompts.py:35`).
