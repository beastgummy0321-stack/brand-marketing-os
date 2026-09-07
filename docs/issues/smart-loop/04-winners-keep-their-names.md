# 04 — Winners keep their names: the next tree continues last period's nodes

Route B: behaviour change (one tree-prompt section, one read-time overlay field, one screen badge); no schema, no
money path, no permission path. Board row 越排越好, spec cut 3. Depends on ticket 03 (`_last_period_text()` and
`scoring.VERDICT_LABELS` exist; the tree prompt already carries 【上一期】). Staffing: Sonnet implements, a different
Sonnet reviews.

Why: today every period gets a brand-new tree with names the agent writes fresh (`tree.py:79-80`), and binding
matches by exact name (`binding.py:73-126`, `meta_repo.campaign_ids_by_exact_name`). So a node that won last
period is only re-bound to the same Meta object by coincidence, and the platform-side learning of that object is
lost. Spec decision 2 (user, 2026-09-08): nodes whose verdict is `win` or `unclear` keep their exact names; `lose`
nodes get new coordinates and new names. Because binding is by exact name, keeping the name is what reconnects.

Not this ticket: writing anything to Meta; changing the department task file `app/departments/ads/campaign_tree.md`;
the next-period budget/date suggestion (05); the copy-name button (`docs/issues/ui/issue-tree-node-names-have-no-copy-button.md`).

## What

### 1. Tree prompt — `app/schedule/jobs.py`

```
_continuity_text(node_results: list[dict]) -> str        # "" when node_results is empty
```
Called in `schedule_tree()` only, with the same `period_node_results` rows `_last_period_text()` reads (read once,
pass the list to both; do not query twice). Appended as the **last** element of the tree tuple, after the
【上一期】 section (it is the instruction that acts on that section; contract "Position in the prompt decides
whether an instruction runs"). Literal:

```
【延續】
上一期判決「賺」或「看不出」的節點，這一期**名字一字不改**地沿用（系統靠名稱把它接回同一個 Meta 物件，改一個字就接不回去）：
- 組合：Beast Gummy｜效率補給
- 廣告：Beast Gummy｜效率補給｜再行銷
上一期判決「賠」的節點不要沿用：換座標、換名字，並在該節點的 warnings 寫一句「取代上一期的 <舊名>」：
- 組合：Beast Gummy｜送禮組合
沿用的節點可以改 share、fields、children；只有 name 不能動。
```

Names come from `node_name` of the rows; grouped by depth (`組合` = 2, `廣告` = 3), ordered as the rows are
(depth, node_key). When there is no `lose` row the second block is omitted; when there is no `win`/`unclear` row
the first block is omitted; both empty → `""` (the function returns `""` and the `if section` filter drops it).

### 2. Read-time overlay — `app/schedule/binding.py`

`tree_with_bindings()` gains one overlay after `_apply_bindings()`: for the latest settled period
(`period_repo.latest_settled_period()`, from ticket 03) read its `period_node_results()`; every tree node whose
`(depth, name)` equals a row's `(depth, node_name)` gets `continued_from_node_key = row["node_key"]`, every other
node `None`. Depth 1 nodes always `None` (never scored). Read the results **once** per call. `tree.py` gains the
key in the node dict it builds (`"continued_from_node_key": None`, next to `bound_external_id`), so the shape is
the same whether or not binding overlays anything. No settled period → all `None`.

Literal (one node of the tree the API returns):

```json
{"name": "Beast Gummy｜效率補給", "node_key": "1.1", "share": 0.55, "daily_amount": 1100,
 "fields": [], "warnings": [], "children": [],
 "bound_external_id": "120251176092460671", "continued_from_node_key": "1.1", "spend": null, "roas": null}
```

### 3. Screen — `frontend/src/components/schedule/CampaignTree.tsx`, `frontend/src/lib/scheduleApi.ts`

`CampaignTreeNode` gains `continued_from_node_key: string | null`. In `NodeDetail`, next to the level badge, a
second `Badge` 「延續上一期」 when `continued_from_node_key !== null`. Nothing else changes; a node without the
badge is the one the user creates fresh on Meta. Wording per `docs/design-system.md`.

### 4. Contract page — `docs/contracts/schedule.md`

One bullet under "Module-local and reversible": the tree prompt ends with 【延續】 naming last period's
`win`/`unclear` nodes to keep verbatim and `lose` nodes to replace; `binding.tree_with_bindings()` marks a node
`continued_from_node_key` when its name and depth equal a scored node of the latest settled period (read-time,
not stored).

## How we know it's done

Run with `BRAND_OS_LLM_PROVIDER` unset.

1. `app/tests/test_schedule.py`, bound-account base, reusing ticket 03's seeded settled period (a depth-2 `win`
   row named A, a depth-3 `lose` row named B): POST a tree, run the worker, read the prompt: contains `【延續】`,
   `- 組合：A` under the keep block, `- 廣告：B` under the replace block, and `index("【延續】") > index("【上一期】")`.
   Red proof: drop `continuity_text` from the tuple → fails.
2. Same base: the fake tree reply names its depth-2 node exactly `A` → `GET /api/schedule/brands/{id}` returns that
   node with `continued_from_node_key == "<A's node_key from the settled rows>"`; a node named `A ` (trailing
   space) or `A` at depth 3 → `None`. A brand with no settled period → every node `None` and the key present.
3. Only `win`/`unclear` names are in the keep block: add an `unclear` row named C to the seed → `- 組合：C` appears
   in the keep block, never in the replace block.
4. Gate, verbatim: `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule.py app/tests/test_schedule_period.py app/tests/test_architecture_boundaries.py -q`
   then `cd frontend && npm run build && npm run e2e`.
5. Ratchets: measure `_line_totals()` and `_module_sizes()["app/schedule"]` before and after; **this ticket
   authorizes raising both to the measured value after the change** with a one-line reason at each constant.
6. Acceptance on a restarted backend + worker: 排程 → 出方案 → 展開活動樹 (plan 1) → wait → the tree's node names
   include at least one name from the settled period's node table verbatim (count them: 10 possible) and those
   nodes show the 「延續上一期」 badge; then 綁定 → the continued nodes bind without the user creating anything on
   Meta (the bound campaign is paused; binding by name still resolves). Counts reported, not judged.

## Shared files touched

Files edited: `app/schedule/jobs.py` (`_continuity_text`, tree tuple), `app/schedule/binding.py`
(`tree_with_bindings` overlay), `app/schedule/tree.py` (node dict key), `frontend/src/lib/scheduleApi.ts`,
`frontend/src/components/schedule/CampaignTree.tsx`, `app/tests/test_schedule.py`,
`app/tests/test_architecture_boundaries.py` (two constants), `docs/contracts/schedule.md`.

Names whose meaning changes — scanned 2026-09-08 (before ticket 03 ships; refresh `jobs.py` lines after it):

```
### git grep -n "def tree_with_bindings\|tree_with_bindings("
app/schedule/binding.py:58:def tree_with_bindings(conn, tree_row: dict, org_id: str, brand_id: str) -> dict:
app/schedule/state.py:165:    tree = (binding_mod.tree_with_bindings(conn, tree_row, org_id, brand_id)
(plus test_schedule.py callers around lines 1157-1208, which assert bound_external_id and keep passing)
### git grep -n "\"bound_external_id\": None" app/schedule/tree.py
app/schedule/tree.py:~120:            "bound_external_id": None, "spend": None, "roas": None,
### grep -n "^from app.schedule" app/schedule/binding.py
app/schedule/binding.py:  repository as schedule_repo; tree as tree_mod; period_repository as period_repo (added by ticket 02)
### grep -n "bound_external_id" frontend/src/lib/scheduleApi.ts frontend/src/components/schedule/CampaignTree.tsx
frontend/src/lib/scheduleApi.ts:73:  bound_external_id: string | null;      (inside `export interface CampaignTreeNode`, line 65)
frontend/src/components/schedule/CampaignTree.tsx:95-99  (NodeDetail: level Badge, share/daily_amount, spend/roas)
### git grep -n "campaign_ids_by_exact_name"
app/meta/repository.py:298:def campaign_ids_by_exact_name(
app/schedule/binding.py  (bind_tree, ~line 100-126)   — unchanged by this ticket; continuity relies on it as is
```

## Contradiction check

- **Check 1 (keep block lists `win`/`unclear`) vs. spec decision 2 as the user might read it** ("看不出 = not
  tested yet"): an `unclear` node with `actual_spend 0` (never ran) is kept by name even though nothing was learned.
  Settled by the user's own reasoning in the spec (換掉等於永遠測不出來). Not a contradiction inside the checks.
- **Check 2 (overlay by `(depth, name)`) vs. `_apply_bindings` (by `node_key` + name)**: a node that keeps its name
  but moves position (was `1.2`, now `1.1`) is `continued` (name match) but shows unbound until the user binds the
  new tree — expected: continuity is about the platform object, binding is per tree (ADR 0064). Check 2's second
  case must use a different `node_key` than the settled row's to prove the overlay ignores position.
- **Cheapest wrong implementation that leaves every check green**: (a) overlay matching name only, ignoring depth
  — caught by check 2's depth-3 `A`; (b) `_continuity_text` reading `bindings_by_node_key` (current bindings)
  instead of the settled rows — check 1 seeds a settled row for a node that is not bound in the current tree, so the
  name appears only if the rows are read; (c) listing `lose` nodes in the keep block — caught by check 1's block
  assertion only if the test asserts the line is under the correct heading (assert on the substring
  `不要沿用：\n- 組合：B` or equivalent ordering), not merely that `B` appears.
