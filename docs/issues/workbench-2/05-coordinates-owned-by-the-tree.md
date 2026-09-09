# 05 — a node's coordinates are owned by the tree; a 沿用 node keeps last period's; the brief, the candidate and the screen read them

route=C: the schedule → workbench boundary changes (the handoff now carries coordinates; the sync's
source of truth moves from the copy model to the brief snapshot) — ADR 0069 written and ADR 0068
§2/§3 amended by main chat before dispatch. Serves the board row 工作檯消融與閉環修正 (spec.md,
ticket 05). User ruling 2026-09-09 after drill 3: 「座標歸樹、沿用帶上一期；確認好這期結束後，能夠把
好的留下來繼續投，爛的替換掉即可」. Drill 3 fact: 沿用 node 01A scored (pain=effort, hook=outcome_led)
in period 1 and (experience, pain_question) in period 2 because `app/schedule/jobs.py:552` handed
the brief `"coordinates": None` and `state.py:194` took the copy model's guess.

## What

### 1. The tree returns coordinates (`app/departments/ads/campaign_tree.md`, `app/schedule/jobs.py`)

- Every **third-layer** node gains `coordinates`: an object with the seven dimension keys
  `audience/pain/angle/hook/proof/offer/format`, each value the **label 原文** from the brand's
  vocabulary (or `null` when a dimension does not apply). The reply skeleton (`campaign_tree.md:66-90`)
  shows it on the third-layer node only. Layers 1–2 never carry it.
- The tree prompt gains the brand's coordinate vocabulary as its **last** section (the same
  "vocabulary last" order the copy prompt uses, ADR 0068 §6): `jobs.py` builds it from
  `repository.list_coordinates()` (schedule's own reader, `app/schedule/repository.py:227`) as
  「## 座標詞彙表」 — one line per dimension, 「受眾：label1、label2、…」, disabled/rejected labels
  omitted; the dimension Chinese names come from `diagnosis.py:35-45`'s existing table. Not a
  workbench import (schedule may import only `app.workbench.__init__`, ADR 0068 §2).
- Continuity text (`jobs.py:335-343, 368-400`): `_CONTINUITY_CLOSING_LINE` becomes
  「沿用的節點可以改 share、fields、children；name 與 coordinates 都不能動——coordinates 照【上一期】
  表的座標欄逐字抄。」; `_CONTINUITY_REPLACE_HEADER` becomes 「上一期判決「賠」的節點不要沿用：換名字、
  換座標（七個維度至少一個跟舊的不同），並在該節點的 warnings 寫一句「取代上一期的 <舊名>」：」.

### 2. The parser keeps them (`app/schedule/tree.py:113-124`)

Node dict gains `"coordinates"`: for depth 3 a dict `{dimension: str | None}` over exactly the seven
dimensions (`creative.COORDINATE_KEYS`) — unknown keys dropped, a non-string value → `None`, a missing
or non-dict `coordinates` → all seven `None` (**not** a parse failure: every tree already in the DB has
none and must still render). Depth 1–2: `None`. `docs/contracts/schedule.md` tree-node shape gains the
field.

### 3. The program enforces 沿用 (`app/schedule/binding.py:76-110`)

`_continuity_map()` returns, per `(depth, node_name)`, both `node_key` and the scored row's
`coordinates_json`; `_apply_continuity()` on a depth-3 node whose name matched sets
`node["coordinates"]` to last period's keys converted to labels (`performance._coordinate_labels`,
`app/schedule/performance.py:102`, fallback = the key itself; a `None` key stays `None`), **overriding
whatever the model wrote**. Depth 2 matches keep only `continued_from_node_key` (no coordinates).
Read-time overlay, never a write — the tree JSON stays the model's; the screen and the handoff both
go through `tree_with_bindings()` (`jobs.py:541`, `state.py`), so both see the enforced values.

### 4. The handoff carries them (`app/schedule/jobs.py:552`)

`"coordinates": {k: v for k, v in (leaf.get("coordinates") or {}).items() if v}` — labels, empty
dims dropped, so a brief from an old tree still gets `{}`. `docs/contracts/workbench.md` §2 says the
snapshot is filled by schedule for `schedule_node` briefs.

### 5. The copy prompt states them (`app/workbench/prompts.py:29-32`)

The line becomes 「這個節點的座標（文案照這組座標寫；回覆的 coordinates 逐字抄回這七個值）：」 + the JSON.
`copy.md` unchanged (it already demands the seven labels and the validator checks them).

### 6. The sync prefers the snapshot (`app/schedule/state.py:178-204, :232-241`)

`_sync_creative_candidate` gains a `brief` argument; coordinates =
`{**(copy_output.get("coordinates_json") or {}), **{k: v for k, v in (brief["coordinates_snapshot_json"] or {}).items() if v}}`
— the snapshot wins per dimension, the model fills only what the snapshot left empty (a manual
brief with no snapshot keeps today's behaviour). `persist_creative_result` unchanged
(`_resolve_coordinates` still maps labels → keys, `repository.py:278-302`).

### 7. The screen shows them (`frontend/src/lib/scheduleApi.ts:70-90`, `frontend/src/components/schedule/CampaignTree.tsx:103-130`)

`CampaignTreeNode.coordinates: Partial<Record<CoordinateDimension, string | null>> | null`. In
`NodeDetail`, when `coordinates` is non-null, one `<dl>` row before `fields`: `<dt>座標</dt>` and
`<dd>` = the seven values in `COORDINATE_DIMENSIONS` order joined by 「／」, a `null` shown as 「—」
(the same marks `jobs._coordinate_cell` uses). No other UI.

Literal — a third-layer node in the tree response after this ticket:
```json
{"name": "01A｜不勒｜靜態產品主視覺", "node_key": "1.1.1", "fields": [{"label": "素材", "value": "…"}],
 "share": null, "warnings": [], "children": [], "bound_external_id": null, "spend": null, "roas": null,
 "continued_from_node_key": "1.1.1",
 "coordinates": {"audience": "陌生・知道問題", "pain": "費力", "angle": "UGC 偽裝", "hook": "結果導向",
                 "proof": "無證明", "offer": "無優惠", "format": "單圖"}}
```
and the brief it submits has `coordinates_snapshot_json` equal to that object minus `null` values.

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `env -u BRAND_OS_LLM_PROVIDER uv run pytest app/tests/test_schedule.py app/tests/test_schedule_performance.py app/tests/test_workbench.py app/tests/test_architecture_boundaries.py -q` green, with these new cases, each proven red once by reverting its one line:
   - `test_schedule.py` tree parsing: a third-layer node with `coordinates` (one unknown key, one non-string, one `null`) → exactly the seven dimensions, unknown dropped, non-string `None`; a tree without `coordinates` → all seven `None`, layers 1–2 `None`, and `build_tree` still succeeds (red by making a missing key fail).
   - `test_schedule.py` continuity overlay (next to `:2040-2070`): a settled period whose depth-3 row `01A` has `coordinates_json` `{"pain_key": "effort", "hook_key": "outcome_led", …}` and a new tree whose `01A` came back with different labels → `tree_with_bindings()` node `01A` has `coordinates.pain == "費力"` and `hook == "結果導向"` (labels via the seeded vocabulary), and a depth-3 node with no match keeps the model's labels (red by dropping the override).
   - `test_schedule.py` handoff (extend `test_tree_success_submits_one_brief_per_leaf_and_stays_queued`, `:752`): each submitted brief's `coordinates_snapshot_json` equals its leaf's non-null coordinates (red by restoring `None`).
   - `test_schedule.py` `CreativeCandidateSyncTest`: a brief whose snapshot has `angle` 「UGC 偽裝」 and no `hook`, whose copy output's `coordinates_json` has `angle` 「稀缺行銷」 and `hook` 「痛點提問」 → the `creative_candidate` has `angle_key == "ugc_disguise"` and `hook_key == "pain_question"` (red by dropping the merge).
   - `test_schedule.py` prompt text: the tree prompt contains 「## 座標詞彙表」 after 【延續】 and the new closing line (red by removing the section).
   - `test_workbench.py`: `brief_text` for a brief with a snapshot contains 「這個節點的座標」 and the JSON; without one, neither (red by restoring the old wording).
3. `cd frontend && npm run build && npm run lint && npm run depcruise && npm test && npm run e2e` green.
4. `git grep -n "延續語氣參考用" app` returns nothing; `git grep -n '"coordinates": None' app/schedule/jobs.py` returns nothing.
5. `git diff --name-only` ⊆ Shared files touched.
6. WALK (restarted 8720 backend + worker, fresh browser, `vivian2@example.com`/`drill1234`, MOVE Daily
   `brd_01M22DNZM1BB1RT6Z7TNAHTACP`, whose settled period `cpd_01M22EVEX94GJJ369F99NQJ6GZ` scored 01A as
   `pain_key=effort, hook_key=outcome_led, audience_key=cold_problem_aware, angle_key=ugc_disguise`):
   1. 檔期規劃 → 設定檔期 → the existing plans → 方案 1 → 用這個方案展開 → wait for the tree (3–8 min).
   2. 投放結構 → node 01A｜不勒｜靜態產品主視覺 → the 座標 row reads 「陌生・知道問題／費力／UGC 偽裝／結果導向／…」 (paste it) and the badge 延續上一期 is shown; node 測試01 → its 座標 row differs from 01B's last-period tuple in ≥1 dimension (paste both).
   3. Wait for the copy briefs (素材準備 shows 文案完成 for 01A), then in a shell:
      `select audience_key, pain_key, angle_key, hook_key from creative_candidate cc join creative_slot s on s.id=cc.slot_id where s.node_key='1.1.1' and s.source_tree_task_id='<new tree task id>'` → `cold_problem_aware, effort, ugc_disguise, outcome_led` (paste).
   4. 素材工作檯 → 01A's brief → the copy card's 文案 mentions nothing about coordinates (no user-visible change); 工單 header shows nothing new. Screenshot of step 2.

## Shared files touched

Searched 2026-09-09 with `git grep -n -F`:

- `_CONTINUITY_CLOSING_LINE` / `_CONTINUITY_REPLACE_HEADER`: `app/schedule/jobs.py:339-343, :399` (edited).
- `_continuity_map` / `_apply_continuity`: `app/schedule/binding.py:76-110` (edited) · `app/tests/test_architecture_boundaries.py:2025` (comment, unchanged).
- `_sync_creative_candidate`: `app/schedule/state.py:178, :239` (signature + call edited) · `app/schedule/repository.py:328`, `app/tests/test_architecture_boundaries.py:1942` (comments, unchanged).
- `既有座標`: `app/workbench/prompts.py:31` (edited) · `app/workbench/repository.py:187` (docstring, unchanged).
- `coordinates_snapshot_json` readers: `app/workbench/prompts.py:27`, `app/workbench/repository.py:115, :382`, `app/schedule/repository.py:353` (unchanged) · `docs/contracts/workbench.md:106`.
- `_coordinate_labels`: `app/schedule/performance.py:102` (definition; new reader in `binding.py`) · `jobs.py:295, :440`, `diagnosis.py:36` (unchanged).
- `continued_from_node_key`: `app/schedule/binding.py:78-103`, `app/schedule/tree.py:120-123`, `frontend/src/lib/scheduleApi.ts:81`, `frontend/src/components/schedule/CampaignTree.tsx:109`, `app/tests/test_schedule.py:2045-2068`, `docs/contracts/schedule.md:160`.
- `COORDINATE_KEYS`: `app/schedule/creative.py:13` (unchanged; new readers in `tree.py`, `binding.py`).
- `list_coordinates`: `app/schedule/repository.py:227` (unchanged; new reader in `jobs.py`).
- `COORDINATE_DIMENSIONS`: `frontend/src/lib/coordinatesApi.ts:12` (unchanged; new reader in `CampaignTree.tsx`).
- `campaign_tree.md` reply skeleton: `app/departments/ads/campaign_tree.md:28-90` (edited).

Files edited: `app/departments/ads/campaign_tree.md`, `app/schedule/{jobs,tree,binding,state}.py`,
`app/workbench/prompts.py`, `app/tests/{test_schedule,test_workbench,test_architecture_boundaries}.py`,
`frontend/src/lib/scheduleApi.ts`, `frontend/src/components/schedule/CampaignTree.tsx`,
`docs/contracts/{schedule,workbench}.md`. No file created; no migration (all columns exist).

## Contradiction check

- §3 (program overrides 沿用 coordinates) vs §1 (the model is told to copy them): both are wanted —
  the input that separates them is a model that copies wrongly (drill 3's local model dropped a
  space in a seed); the override test in done-check 2 feeds exactly that. An implementation that
  only edits the prompt passes the prompt-text test and fails the overlay test.
- §6 (snapshot wins) vs the existing `test_adopted_round_not_latest_syncs_to_creative_candidate_idempotently`
  (`test_schedule.py:2413`, asserts `angle_key == "scarcity_marketing"` from the model): that brief
  has an empty snapshot, so the model's value still lands — the new merge case is the one with a
  snapshot. Both must stay green.
- §2 (missing `coordinates` → all `None`, no failure) vs §1 (the prompt requires it): the tree
  validators reject malformed `fields`/`share` today (`tree.py:35-99`); a missing `coordinates` is
  the old-tree case and must not reject — the reviewer checks no `return None` was added for it.
- Cheapest wrong implementation leaving every check green: converting last period's keys to labels
  with the *workbench* vocabulary reader (a boundary violation the dependency test catches only if
  it imports `app.workbench.repository` — the reviewer greps `binding.py` imports); rendering the
  座標 row from `fields` instead of `coordinates`.
