# 05 — After binding, the tree says when Meta holds the budget on a different level, and the diagnosis is told the split was Meta's

Route C: **module boundary** — `app.meta` gains one exported read function that `app.schedule` calls
(`docs/contracts/meta.md` lists what schedule may read; the list grows by one entry in this ticket). No schema,
no migration, no money arithmetic, no permission path beyond the tenant check the new read carries.
Staffing (user, 2026-09-08): Sonnet implements; an independent Sonnet agent reviews (`REVIEW (route C):`); main
chat (Fable) arbitrates; Opus reviewed the ticket list once before dispatch. Board row: 方案品質
(`docs/issues/plan-quality/spec.md`).

Graduated from `issue-budget-level-mismatch-is-never-checked.md` (2026-09-07). Scout re-verified 2026-09-08: the
claims hold, line numbers below are current.

## Background (the fact this ticket acts on)

The tree contract says which level carries the budget (`app/schedule/tree.py:10-18`, `budget_level`; Meta = 2 per
`app/schedule/channel_catalogue.json:9`) and every node on that level carries a `share`; the shares must sum to 1.0
(`tree.py:144-155`). The tree approved on 2026-09-07 had `budget_level: 2` and shares 0.55 / 0.20 / 0.25.
Read back from Meta the same day (`GET /v21.0/<id>?fields=daily_budget,…`, recorded in the issue this ticket
replaces):

```
d1 campaign  {"objective": "OUTCOME_SALES", "daily_budget": "500"}
d2 ad set    {"optimization_goal": "OFFSITE_CONVERSIONS"}      <- no daily_budget
d2 ad set    {"optimization_goal": "OFFSITE_CONVERSIONS"}      <- no daily_budget
d2 ad set    {"optimization_goal": "OFFSITE_CONVERSIONS"}      <- no daily_budget
```

The money sits on level 1 (Meta's campaign-level budget); the approved 55/20/25 is not executing, and nothing
notices: `bind_tree()` matches by name only (`app/schedule/binding.py:103-208`, never reads a budget field);
`app/meta/graph.py`'s field lists (`:199`, `:227`, `:261`, `:279-293`) carry no budget field
(`git grep -n "daily_budget\|lifetime_budget" -- app/meta app/schedule/binding.py` → no hits, 2026-09-08).
Consequence for the diagnosis: under a campaign-level budget Meta's optimiser decides which ad set spends, so
"this coordinate spent more" is Meta's choice, not the user's experiment — exactly what `ab-testing.md:72-75`
warns against (observation read as a controlled test).

**User's ruling, 2026-09-08 (option "提示＋告訴判讀「這期分配是 Meta 決定的」"):** the tree keeps emitting shares;
after binding, the screen states the mismatch in one sentence; the diagnosis prompt receives the same fact and is
told the split was Meta's. The budget placement is **read live and never stored** (no column, no migration) — it is
read twice: once in the bind response, once when a diagnosis runs.

## What

### 1. `app/meta/graph.py` — one new read

```
fetch_budgets(token: str, external_ids: list[str]) -> dict[str, dict]
```

One `GET {GRAPH_BASE_URL}/{id}` with `params={"fields": "daily_budget,lifetime_budget"}` per id, through the
existing `fetch_page()` (`graph.py:71`), so tests replace the same seam every other Graph read uses. Field names
come from the live read above (`daily_budget` returned as the string `"500"`); Meta returns both as strings in the
account's minor unit — **kept as strings, never parsed**: this ticket only asks "is a budget set here". A body in
the `{"error": …}` shape raises `graph.GraphError` exactly as `_fetch_all_pages()` (`graph.py:~100`) does for
list calls; the implementer reads that function and reuses its error detection rather than writing a second one.
A missing field is `None`. Literal example:

```json
{"120250000000000001": {"daily_budget": "500", "lifetime_budget": null},
 "120250000000000002": {"daily_budget": null, "lifetime_budget": null}}
```

### 2. `app/meta/repository.py` — the tenant-bounded wrapper `app.schedule` calls

```
budgets_for_bound_ids(conn, org_id: str, external_ids: list[str]) -> dict[str, dict]
```

- Tenant boundary, **positive**: only ids this organisation has bound reach Meta —
  `SELECT DISTINCT external_id FROM channel_entity_map WHERE org_id = %s AND external_id = ANY(%s)`; ids not in
  that result are dropped silently (fail-closed, stricter than `_refuse_if_parent_owned_by_another_org`
  at `repository.py:~336`, and the same "read schedule's table from here" precedent it cites, ADR 0056 §4).
- `get_token()` is `None` → `{}` (same as the three `*_by_exact_name` readers).
- `graph.GraphError` → `web.ApiError(502, "meta_unreachable", f"連不上 Meta，沒辦法讀預算：{exc.message}")`
  (same shape as `repository.py:326`).
- Empty input → `{}` without touching Meta.

`docs/contracts/meta.md` "Exported shapes" gains this function in the list of reads `app.schedule` may call,
stating the boundary above in the same style as the existing entries. This is the module-boundary change that
makes the ticket route C.

### 3. `app/schedule/binding.py` — the judgement, one function, one sentence

```
BUDGET_LEVEL_NOTE = "你的預算掛在「{actual}」這一層，這棵樹是照「{expected}」那一層分配的；核准的比例不會在 Meta 上生效，這一期每個{expected}花多少由 Meta 自己決定。"

budget_placement_note(conn, org_id: str, brand_id: str, tree_row: dict) -> str | None
```

- `tree = tree_mod.tree_from_task_row(tree_row)`; a tree with `failure` or no `budget_level` → `None`.
- `bound = schedule_repo.bindings_for_tree(conn, org_id, brand_id, CHANNEL_KEY, tree_row["id"])`; a node's depth
  is `node_key.count(".") + 1` (`tree.py:76`, keys are `"1"`, `"1.2"`, `"1.2.3"`). Collect bound external ids
  for depth 1 and depth 2 only — Meta ads (depth 3) carry no budget.
- No bound id on depth `expected = tree["budget_level"]` → `None` (nothing to compare yet).
- `budgets = meta_repo.budgets_for_bound_ids(conn, org_id, <ids of depth 1 and 2>)`; on `web.ApiError` → `None`
  (the note is best-effort; the binding that just succeeded is not undone by a second, unrelated read).
- `has_budget(id)` = the entry exists and `daily_budget` or `lifetime_budget` is a non-empty string.
- Any bound id on level `expected` has a budget → `None` (placement matches).
- Otherwise, the other level (1 or 2) has at least one bound id with a budget → the sentence, with
  `actual = tree["levels"][other - 1]` and `expected = tree["levels"][expected - 1]` (the platform's own level names,
  `tree.py:11-12`). Neither level shows a budget → `None` (cannot tell; say nothing).

Pure apart from the two repository reads; no write.

### 4. Where the sentence goes

- `app/schedule/tree.py:205` shell fields: add `"budget_note": None` beside `"bind_failure": None`; the docstring
  there and `tree_approval.py:31`'s shell-field list name it too, so the approval signature keeps ignoring it
  (ADR 0059: the signed shape is the agent's tree, not the shell's fields).
- `app/schedule/routes.py:344-357` `_run_bind()`: after `bind_failure`, set
  `response["tree"]["budget_note"] = binding_mod.budget_placement_note(conn, org_id, brand_id, tree_row)`.
  Only this route fills it; GET / tree / reject leave it `None` — the same rule `bind_failure` follows
  (`tree.py:202-204`).
- `app/schedule/jobs.py:557-620` `schedule_diagnosis()`: read the tree the diagnosis already reads
  (`diagnosis.tree_reminders()` uses `state._display_task_row(conn, brand_id, state.TREE_TASK_TYPE)`, `diagnosis.py:132`);
  when `budget_placement_note()` returns a sentence, add one section to the prompt join at `jobs.py:582-586`
  **after `reminders` and before `role_text(lens)`** (the instruction stays last — `docs/contracts/schedule.md`
  "Position in the prompt decides…"):

  ```
  【預算層級】
  <the sentence>
  這一期各座標花多少是 Meta 最佳化器分配的結果，不是使用者的實驗設計；花費差異不能讀成使用者的選擇，也不能當成對照實驗的結果。
  ```

  `None` → no section, prompt unchanged.
- `frontend/src/lib/scheduleApi.ts:103-116` `CampaignTreeResult`: `budget_note: string | null` with the same
  one-line comment `bind_failure` has. `frontend/src/components/schedule/CampaignTree.tsx:53`: directly below the
  `bind_failure` line, `{tree.budget_note && <p role="status" className="text-xs leading-6 text-warning">{tree.budget_note}</p>}`
  (the `text-warning` style already used at `:57`).
- `docs/contracts/schedule.md`, "Decisions in force" section, one bullet in the style of the
  `Next-period suggestion is read-time` bullet (`:115`): budget placement is read live at bind time and at
  diagnosis time, never stored; the sentence and its diagnosis framing are the user's ruling of 2026-09-08.

Not this ticket: telling the user how to change the budget on Meta; per-ad-set amounts on the name list
(issue remedy 2 — dropped, the user's ruling chose the note); anything on `budget_level` itself; storing budgets.

## How we know it's done

1. `uv run pytest app/tests/test_schedule.py -q -k budget_note` — in `BindTreeApiContractTest`, a helper
   `_platform_budgets(by_id: dict)` that patches `meta_graph.fetch_budgets` (same style as `_platform_ad_sets`,
   `test_schedule.py:1066-1078`), and three tests on a bound `budget_level: 2` tree (fixture as
   `test_second_bind_after_rename_inserts_a_new_row_for_the_new_tree`, `:1391`, but with ad sets that bind):
   (a) campaign `{"daily_budget": "500"}`, ad sets both `None` → response `tree["budget_note"]` equals
   `BUDGET_LEVEL_NOTE.format(actual="行銷活動", expected="廣告組合")` (level names from `_tree_fenced`'s default
   `levels`, `:84-87`); (b) ad sets carry `daily_budget` → `None`; (c) `fetch_budgets` raises `GraphError` →
   status 200, `budget_note` is `None`, and the `channel_entity_map` rows written by the bind are still there.
   Red proof for (a): return `None` unconditionally.
2. `uv run pytest app/tests/test_meta_daily_spend.py -q -k budgets_for_bound_ids` — on `_CrossOrgBindingFixture`
   (`test_meta_daily_spend.py:~1060`): org_a with a token calls `budgets_for_bound_ids(conn, org_a, ["camp-owned-by-org-b"])`
   → `graph.fetch_budgets` call count 0 and result `{}`; with an id org_a itself bound, `fetch_budgets` receives
   exactly that id. This is the route C class the reviewer attacks: read the other tenant's row.
3. `uv run pytest app/tests/test_schedule.py -q -k diagnosis_budget` — with the (a) fixture and
   `schedule_jobs.PROVIDER = _fake(...)`, call `schedule_jobs.schedule_diagnosis(coredb.DEV_ORG_ID, self.brand["id"])`
   directly (it opens its own connection; commit first as `_run_worker()` does) → `fake.calls[0]["messages"][0]["content"]`
   contains `【預算層級】` and the (a) sentence, and `index("【預算層級】") < index("只准對上面表格裡已經出現過的座標值")`
   (`diagnosis.py:312`, the role text that must stay last). With the (b) fixture the prompt does not contain
   `【預算層級】`. If the job cannot run on this fixture for a reason unrelated to this ticket, report
   `blocked-wall` with the traceback — do not stub the job.
4. `git grep -n "budget_note" -- app/schedule/routes.py` prints exactly one hit inside `_run_bind()`.
5. Machine gate: `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule.py app/tests/test_meta_daily_spend.py app/tests/test_schedule_diagnosis.py app/tests/test_architecture_boundaries.py -q`
   green; `cd frontend && npm run build && npm run lint && npm test` green; `cd frontend && npm run e2e` green
   (start the backend on 8720 yourself, stop it after; `supabase start` first).
6. Acceptance walk (`WALK:` post, playwright-cli, login `123@example.com` / `123456`, restarted backend): open
   `/app/brands/brd_bughunt/schedule` → the 展開結果 section renders with the 配對 button, no error banner.
   Press 配對 → the page returns without an error state; record as a fact whether a 「你的預算掛在」 line appears
   (the seed brand's bound account is real account data; its state is recorded, not acted on). Screenshot both.

## Shared files touched

`git grep -n "_run_bind" -- . ':!graphify-out'` (2026-09-08) — the route whose response gains a field:

```
app/meta/repository.py:304:    （`app.schedule._run_bind`）綁定時原樣存進 `channel_entity_map`（ADR 0055 §4）。
app/schedule/repository.py:445:    （`_run_bind`）呼叫這支，讀樹的疊圖永遠不建這一列。
app/schedule/routes.py:344:def _run_bind(conn, brand_id: str, org_id: str) -> dict:
app/schedule/routes.py:364:    `_run_tree`／`_run_bind` 的「先驗證、後動作」次序）。舊列從不覆寫，一次核
app/schedule/routes.py:444:    return _run_bind(web.conn, brand_id, actor.org_id)
app/tools/simulate_meta_spend.py:240:        # 4. 綁三個深度 3 節點：真名稱比對，比照 `_run_bind` 路由呼叫的
docs/adr/0055-a-node-is-identified-by-a-path-key-and-a-channel.md:191:The bind *action* is also Meta-specific — `_run_bind` call
docs/issues/ui/issue-bind-message-hides-partial-success.md:6:新樹 `llm_01M1YSN3…` 綁上活動 1、組合 3、廣告 7），
```

`git grep -n "bind_failure" -- . ':!graphify-out'` — the sibling shell field whose every mention is where
`budget_note` is added next to it (docstrings at `tree.py:202-205`, `tree_approval.py:31`, the frontend type and
component):

```
app/schedule/binding.py:24, :111
app/schedule/jobs.py:319
app/schedule/routes.py:355-356
app/schedule/tree.py:205
app/schedule/tree_approval.py:31
app/tests/test_approval.py:150
app/tests/test_architecture_boundaries.py:1266
app/tests/test_schedule.py:1087, :1158, :1193, :1210, :1225, :1242, :1291, :1416, :1425, :1505, :1559, :1580-1582, :1611, :1694
docs/adr/0040-approval-is-the-money-brake.md:67
docs/issues/ui/issue-bind-message-hides-partial-success.md:6
docs/issues/ui/issue-bind-success-is-silent.md:7, :29
frontend/src/components/schedule/CampaignTree.tsx:53
frontend/src/lib/scheduleApi.ts:115
```

`git grep -n "schedule_diagnosis" -- app` — the job whose prompt gains a section:

```
app/schedule/diagnosis.py:8
app/schedule/jobs.py:557, :629
app/schedule/routes.py:494
app/tests/test_architecture_boundaries.py:1369, :1373, :1387, :1755
app/tests/test_schedule_diagnosis.py:1
```

`git grep -n "budget_note\|fetch_budgets\|budgets_for_bound_ids\|budget_placement" -- . ':!graphify-out'` — no
hits (all three names are new).

`git grep -n "daily_budget\|lifetime_budget" -- app/meta app/schedule/binding.py` — no hits (the fields enter
these two files for the first time; the 26 files elsewhere that mention `daily_budget` are the rule card / period
budget, a different number, untouched).

Files this ticket edits: `app/meta/graph.py` (387 lines), `app/meta/repository.py` (737 — **92% of the 800 cap;
the completion report names it**), `app/schedule/binding.py` (208), `app/schedule/tree.py`,
`app/schedule/tree_approval.py`, `app/schedule/routes.py` (608), `app/schedule/jobs.py` (642),
`app/tests/test_schedule.py`, `app/tests/test_meta_daily_spend.py`, `frontend/src/lib/scheduleApi.ts`,
`frontend/src/components/schedule/CampaignTree.tsx` (177), `docs/contracts/meta.md`, `docs/contracts/schedule.md`.
`app/meta/repository.py` at 737 (plan review 2026-09-08 re-measured it: 63 lines of headroom). Budget for
`budgets_for_bound_ids()` **including its docstring: 30 lines** — a four-line docstring that names the boundary
and the two exits, one SQL, one loop, one `except`. If the function does not fit under the 800-line cap at that
size, stop and report `blocked-upstream` per workflow "A boundary escalation is not a menu" — do not carve out a
helper, do not trim another function's docstring to make room.

## Contradiction check

- Done-checks 1(a) and 1(c) could contradict if the Graph failure were raised from `budgets_for_bound_ids` as
  `ApiError` and not caught in `budget_placement_note()`: (c) would then return 502 after the bind rows were
  committed. The input that shows it is (c) itself; the spec settles it by catching in `binding.py`.
- Done-check 3 and the contract line "position decides" could contradict if the implementer appends the section
  after `role_text` (still "contains"); the index assertion in check 3 is what rules that out.
- Cheapest wrong implementation that leaves every check green: compute the note from `list_campaigns()`'s
  existing fetch by widening its field list, and skip `fetch_budgets` entirely for campaigns — check 2's
  `fetch_budgets` call assertions would still pass for ad sets. It is wrong because the diagnosis path has no
  name-match fetch to piggy-back on; check 3 with the (a) fixture (budget on the **campaign**, read outside any
  bind) is what catches it.
