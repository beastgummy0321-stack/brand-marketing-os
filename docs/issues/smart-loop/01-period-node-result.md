# 01 — Settling a period scores every bound node (`period_node_result`)

Route C: schema (one new table). Board row 越排越好 (`docs/issues/smart-loop/spec.md`, cut 1). ADR 0066 (written
by main chat at station ①) governs this ticket. Staffing (user 2026-09-08): Sonnet implements, a different Sonnet
reviews; Opus reviewed the spec once.

Why: the system cannot answer "was last period's decision right" because nothing stores per-node outcomes.
`period.settle()` freezes two brand-level numbers (`period.py:298-338`); the tree, its approved shares, the bindings
and the spend all exist separately and are never joined at settle time. Measured 2026-09-08 on `brd_bughunt`:
`period_node_membership` 3 rows, `channel_entity_map` depth 1/2/3 = 1/3/7 rows, `creative_candidate` 7 tagged,
period `cpd_01M1Y012CPJJW2F07KV8TJAC8J` (2026-09-07 ~ 2026-09-14) `running`, unsettled. **The bound Meta objects
have zero spend rows** (`channel_entity_map LEFT JOIN meta_entity_spend ON entity_id` → 0 rows at every depth; the
bound campaign is paused, all real spend is on the user's hand-built ads). So settling today writes rows with
`actual_spend 0` and verdict `unclear` — that is the honest answer, and the acceptance step below expects it.
Plan review (Opus, 2026-09-08) also found `breakeven_roas()` returns 1.0 from a 100% margin because the product's
cost is filled as 1.05 — data, not code; the row stores the break-even's `source` so a reader can see it.

Not this ticket: putting the results into any prompt (cut 2); name continuity (cut 3); reading Meta's
`daily_budget` to tell whose allocation it was (spec decision 5: approved vs actual are stored side by side, nothing
is inferred); any change to `app/meta`.

## What

### 1. Migration — `supabase/migrations/20260908000001_schedule_period_node_result.sql`

```sql
-- Module: schedule (ADR 0049). Ticket: smart-loop 01. ADR 0066.
CREATE TABLE period_node_result (
    id TEXT PRIMARY KEY,                                   -- pnr_*, via db.new_id("pnr")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    campaign_period_id TEXT NOT NULL,
    source_tree_task_id TEXT NOT NULL,                     -- the tree whose bindings were scored
    channel_id TEXT NOT NULL REFERENCES ad_channel(id),
    node_key TEXT NOT NULL,
    depth SMALLINT NOT NULL CHECK (depth IN (2, 3)),                -- 2 = ad set (carries share), 3 = ad (carries coordinates); depth 1 is one campaign, nothing to score
    node_name TEXT NOT NULL,                               -- node_name_at_bind
    external_id TEXT NOT NULL,                             -- the Meta object the node was bound to
    approved_share numeric(6,4),                           -- NULL on a depth that carries no share
    approved_daily_amount numeric(14,2),                   -- NULL on a depth that carries no share
    actual_spend numeric(14,2) NOT NULL,
    revenue_tracked numeric(14,2),                         -- NULL when no day tracked a ROAS
    roas_conservative numeric(10,4),                       -- revenue_tracked / actual_spend
    roas_optimistic numeric(10,4),                         -- revenue_tracked / spend on tracked days
    roas_coverage numeric(5,4) NOT NULL,                   -- tracked rows / rows
    breakeven_roas numeric(10,4),                          -- diagnosis.breakeven_roas() at settle; NULL = none
    breakeven_source TEXT NOT NULL,                        -- the source string breakeven_roas() returns, verbatim
    verdict TEXT NOT NULL CHECK (verdict IN ('win','lose','unclear')),
    coordinates_json jsonb,                                -- depth 3 only: the seven *_key values
    settled_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id),
    UNIQUE (org_id, brand_id, campaign_period_id, channel_id, node_key)
);
CREATE INDEX period_node_result_org_id_idx ON period_node_result(org_id);
CREATE INDEX period_node_result_brand_period_idx ON period_node_result(brand_id, campaign_period_id);
-- RLS block: copy lines 82-88 of 20260903000001_schedule_campaign_period.sql verbatim with the table and
-- policy name swapped (ENABLE ROW LEVEL SECURITY; GRANT SELECT, INSERT, UPDATE, DELETE TO authenticated;
-- DROP POLICY IF EXISTS …_org_isolation; CREATE POLICY …_org_isolation keyed on the app.org_id GUC). ADR 0052.
```

Apply locally with `supabase migration up --local` (PATH prefix `/c/Users/User/scoop/shims` in bash; the tests
bootstrap their own schema from `supabase/migrations/` via `app/tests/conftest.py`, so the local apply is for the
acceptance step and the schema-drift test, not for pytest).

The composite FK mirrors `20260905000002_schedule_campaign_period_composite_fk.sql`. `grep -rn "REFERENCES
period_node_result" supabase/migrations/` → nothing (new table). Before writing: `grep -rn "REFERENCES campaign_period"
supabase/migrations/` shows the composite convention; follow it.

### 2. Scoring — new file `app/schedule/scoring.py`

Private to the package. Imports allowed: `app.schedule.performance` (`_bucket`), `app.schedule.diagnosis`
(`breakeven_roas`), `app.schedule.repository`, `app.schedule.tree` (`tree_from_task_row`), `app.llm.gateway`
(`get_task`), `app.meta.repository` (`daily_entity_spend`, `bound_account_ids_for_brand`), `app.core.db`.
**Never imported by `period.py` or `state.py`** — the in-package import direction is `state → period` and
`performance → state`, so scoring is called from `routes.py` only (see §4). Contract page gets that sentence.

```
score_period(conn, org_id: str, brand_id: str, period_id: str, settled_at) -> int   # rows written
verdict(roas_conservative: float | None, roas_optimistic: float | None, breakeven: float | None) -> str
```

`score_period`:
1. `period = schedule_repo.get_period(conn, org_id, brand_id, period_id)`; `None` → 0. The period's own
   memberships (`period_node_membership` rows with this `campaign_period_id`; add
   `schedule_repo.period_node_memberships_for_period(conn, org_id, brand_id, period_id)` — same JOIN shape as
   `period_node_memberships_for_brand()` at `repository.py:666`, filtered by period, returning also `channel_id`,
   `node_key`, `source_tree_task_id`). No memberships → 0 rows, nothing deleted.
2. `source_tree_task_id` = the memberships' value (they agree by construction; if more than one distinct value,
   take the one on the newest membership row). `tree = tree_mod.tree_from_task_row(gateway.get_task(conn, id))`
   gives every node with `node_key`, `name`, `share`, `daily_amount`, depth by `node_key` dots + 1.
3. `bindings = schedule_repo.bindings_for_tree(conn, org_id, brand_id, "meta", source_tree_task_id)` →
   `node_key → {external_id, node_name_at_bind}`. Only bound nodes at **depth 2 and 3** are scored (depth from
   `node_key` dots + 1; depth 1 is skipped — one campaign, no share, no coordinates). A node never bound has no
   spend to read and gets no row.
4. Spend: two reads, `meta_repo.daily_entity_spend(conn, org_id, account_ids, start_date, end_date + 1 day,
   level="adset")` for depth 2 and `level="ad"` for depth 3; keep rows whose `entity_id` is bound at that depth;
   group by entity; `performance._bucket(rows)` gives `spend`, `revenue`, `roas` (optimistic), `roas_conservative`,
   `roas_coverage`. **Rows of different depths are never summed** (the same money sits on both levels). A bound
   node with no rows: `actual_spend 0`, ROAS `NULL`, coverage `0`, verdict `unclear`.
5. `breakeven, source = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)` once per settle; both stored.
6. `coordinates_json` for depth 3 from `schedule_repo.creative_candidates_for_brand()[(node_key, source_tree_task_id)]`
   (the seven `*_key` fields), else `NULL`.
7. Write rows with `schedule_repo.replace_period_node_results(conn, org_id, brand_id, period_id, rows)` — a
   `DELETE WHERE campaign_period_id = %s AND org_id = %s` then INSERTs, one transaction, `commit()` at the end
   (resettle rewrites the whole set; the audit of the brand-level snapshot already happens in `period.settle()`).
   **`repository.py` is at 731 of the 800-line file cap** (measured 2026-09-08): the three new functions
   (`period_node_memberships_for_period`, `replace_period_node_results`, `period_node_results`) must fit in the
   remaining 69 lines with docstrings of one or two lines each. If they cannot, stop and report `blocked-upstream`
   — do not carve anything out of `repository.py` and do not add it to any oversized list.

`verdict` (pure; spec decision 1, contract "two ROAS values"):
`breakeven is None or roas_conservative is None` → `unclear`; `roas_conservative >= breakeven` → `win`;
`roas_optimistic < breakeven` → `lose`; else `unclear`.

Literal example (one row, numbers from the 2026-09-08 ad-level measurement on `brd_bughunt`, any period):

```json
{"node_key": "1.1.2", "depth": 3, "node_name": "Beast Gummy｜效率補給｜再行銷", "external_id": "120251176290760671",
 "approved_share": null, "approved_daily_amount": null,
 "actual_spend": 1300.0, "revenue_tracked": 6594.97, "roas_conservative": 5.0731, "roas_optimistic": 7.4858,
 "roas_coverage": 0.75, "breakeven_roas": 1.0, "breakeven_source": "這一期產品填的售價與成本，毛利率 100%", "verdict": "win",
 "coordinates_json": {"audience_key": "…", "pain_key": "…", "angle_key": "…", "hook_key": "…", "proof_key": "…", "offer_key": "…", "format_key": "…"}}
```

### 3. Read — `schedule_repo.period_node_results(conn, org_id, brand_id, period_id) -> list[dict]`

Ordered by `depth, node_key`. `period.brand_period_response()` adds one key to the existing `period` dict:
`"node_results": [...]` (empty list until settled; each item = the columns above minus ids, plus `depth_label`
computed in the frontend, not here). `test_schedule_period.py:266` asserts the literal key set of `period` — it
gains exactly `node_results`.

### 4. Route — `app/schedule/routes.py` `_run_settle()`

After `period_mod.settle()` returns `None`: `scoring_mod.score_period(conn, org_id, brand_id, period_id,
settled_at=…)`. `settle()` does not return `settled_at`; read it back from `schedule_repo.get_period()` (the row
was just written) rather than changing `settle()`'s return shape. Two calls in sequence, no branch beyond the
existing error mapping (container contract §7).

### 5. Screen — `frontend/src/components/schedule/PeriodPanel.tsx`

When `period.node_results.length > 0`, below the settled numbers: a table 節點｜層｜核准比例｜實花｜保守 ROAS｜樂觀 ROAS｜判決,
verdict rendered as 賺／賠／看不出 (`win`/`lose`/`unclear`), depth as 組合／廣告 (2/3), plus one line with the
break-even and its source (`breakeven_roas` / `breakeven_source` of the rows). When every row has `actual_spend 0`,
one sentence above the table: 這期綁定的 Meta 物件沒有花費紀錄，判決全部是「看不出」。 Wording per
`docs/design-system.md`. `frontend/src/lib/scheduleApi.ts` `SchedulePeriod` gains `node_results: SchedulePeriodNodeResult[]`.

### 6. Brand delete — `app/schedule/repository.py` `_CHILD_TABLES`

Add `("period_node_result", "檔期節點記分")` before the period tables it references (it references
`campaign_period`, which is deleted by `app.core.cleanup` order — put it first in the tuple).

### 7. Contract page — `docs/contracts/schedule.md`

Entry path list gains `scoring.py`; "Decisions in force" gains `ADR 0066`; the import-direction paragraph gains
"`scoring` is called from `routes` only; `period`/`state` never import it".

## How we know it's done

Run with `BRAND_OS_LLM_PROVIDER` unset. Migration applied locally with `supabase db reset` is **not** required —
`supabase migration up` (or the project's test bootstrap, see `app/tests/conftest.py`) applies new files; say which
you used.

1. `app/tests/test_schedule_period.py`, new class `SettleScoresNodesTest(_PeriodTestBase)`: bind a tree with one
   depth-2 node (existing helpers in the file), seed ad-set-level spend on its `external_id` for two days inside
   the period: day A spend 100 roas 3.0, day B spend 100 roas `None`; set a break-even that yields 1.0 (the
   file's existing fixture path — the rule card `gross_margin` 1.0 or product economics); settle → one
   `period_node_result` row with `actual_spend 200`, `roas_conservative 1.5`, `roas_optimistic 3.0`,
   `roas_coverage 0.5`, `verdict 'win'`. Change day A roas to 0.5 → `lose` (optimistic 0.5 < 1.0). Day A roas 1.2
   → conservative 0.6, optimistic 1.2 → `unclear`. Remove both days → `actual_spend 0`, `verdict 'unclear'`, row
   still written. A depth-1 binding in the same tree gets **no** row. Red proof: comment out the `score_period`
   call in `_run_settle` → zero rows → fails.
2. Same class: settle twice (resettle) → still exactly one row per node, `settled_at` updated.
3. `SettleTenantIsolationTest` (existing, line 221): extend with one assertion — settling org B's period writes no
   `period_node_result` row for org A's node, and org A's read returns none of org B's rows.
4. `PeriodApiContractTest.test_get_returns_null_then_the_literal_key_set_once_settled` (line 250): key set gains
   `node_results` and nothing else.
5. Migration gate, verbatim:
   `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py app/tests/test_migration_ownership.py app/tests/test_rls_tenant_policy.py app/tests/test_real_db_schema_drift.py -q`
   (the last two hold ADR 0052's policy-on-every-org-table rule and the local-DB-vs-fresh-migrate drift; the drift
   test needs the local apply above).
6. Machine gate, verbatim:
   `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule_period.py app/tests/test_schedule.py app/tests/test_brand_delete.py -q`
   then `cd frontend && npm run typecheck && npm run build && npm run e2e` (8720 backend per `CLAUDE.md`).
7. Ratchets measured 2026-09-08 after plan-quality ticket 01: `_line_totals()` tests 20346 = `TEST_LINES_CEILING`;
   `_module_sizes()["app/schedule"]` 4080 = `KNOWN_MODULE_SIZES["app/schedule"]`. **This ticket authorizes raising
   both to the measured value after the change** with a one-line reason at each constant (production: scoring is
   arithmetic and a write path for money-adjacent data; tests: checks 1–4 name data correctness, money arithmetic
   and tenant isolation). `KNOWN_OVERSIZED_FILES` and every other list stay as they are.
8. Acceptance on a restarted backend + worker: open 排程 for `brd_bughunt` → the period 2026-09-07 ~ 2026-09-14
   shows 結算這期 (early settle is allowed; the screen warns about the advice date) → press → the panel shows the
   settled numbers **and** the node table with 10 rows (3 ad sets + 7 ads bound on 2026-09-07), every row
   `actual_spend 0` and 看不出, the sentence 這期綁定的 Meta 物件沒有花費紀錄 above it, and the break-even line
   showing 1.00x with its source; the DB has the same 10 rows (`select count(*) from period_node_result where
   campaign_period_id='cpd_01M1Y012CPJJW2F07KV8TJAC8J'`). The three verdict values are proven by check 1 on
   seeded data; the real account's state is recorded as a fact, never as a step for the user.

## Shared files touched

Files edited or created: `supabase/migrations/20260908000001_schedule_period_node_result.sql` (new),
`app/schedule/scoring.py` (new), `app/schedule/repository.py` (three functions + `_CHILD_TABLES`),
`app/schedule/period.py` (`brand_period_response` adds `node_results`), `app/schedule/routes.py` (`_run_settle`),
`frontend/src/lib/scheduleApi.ts`, `frontend/src/components/schedule/PeriodPanel.tsx`,
`app/tests/test_schedule_period.py`, `app/tests/test_architecture_boundaries.py` (two constants),
`docs/contracts/schedule.md`, `docs/adr/0066-*.md` (main chat writes it before dispatch).

Names whose meaning or callers change, scanned whole-repo 2026-09-08:

```
### git grep -n "period_mod.settle\|def settle("
app/schedule/period.py:298:def settle(conn, *, org_id: str, brand_id: str, period_id: str, actor: str) -> str | None:
app/schedule/routes.py:403:    error = period_mod.settle(conn, org_id=org_id, brand_id=brand_id, period_id=period_id,
### git grep -n "write_settlement"
app/schedule/period.py:334:    schedule_repo.write_settlement(
app/schedule/repository.py:483:def write_settlement(conn: _AnyConn, *, org_id: str, period_id: str, spend: float,
### git grep -n "brand_period_response"
app/schedule/period.py:258:def brand_period_response(conn, org_id: str, brand_id: str) -> dict | None:
app/schedule/state.py:197:        "period": period_mod.brand_period_response(conn, org_id, brand_id),
### git grep -n "SchedulePeriodSettled\|settle_advice_date"
app/schedule/period.py:293:        "settle_advice_date": advice_date.isoformat(),
app/tests/test_schedule_period.py:266:             "settle_advice_date", "settled"},
frontend/src/components/schedule/PeriodPanel.tsx:37:            這期已結束。Meta 的成交回報最長 7 天才補齊，建議 {period.settle_advice_date} 之後再結算。
frontend/src/lib/scheduleApi.ts:159:export interface SchedulePeriodSettled {
frontend/src/lib/scheduleApi.ts:175:  settle_advice_date: string;
frontend/src/lib/scheduleApi.ts:176:  settled: SchedulePeriodSettled | null;
### git grep -n "_CHILD_TABLES"   (schedule module's own tuple; the brand_intelligence ones are another module's)
app/schedule/repository.py:692:_CHILD_TABLES = (
app/schedule/repository.py:705:    for table, label in _CHILD_TABLES:
app/schedule/repository.py:715:    for table, _label in _CHILD_TABLES:
### git grep -n "_run_settle"
app/schedule/routes.py:398:def _run_settle(conn, brand_id: str, org_id: str, period_id: str, actor: str) -> dict:
app/schedule/routes.py:472:    return _run_settle(web.conn, brand_id, actor.org_id, period_id, str(actor.user_id))
### git grep -n "def tree_from_task_row\|def latest("
app/core/approval.py:56:def latest(
app/schedule/tree.py:162:def tree_from_task_row(row: dict) -> dict:
### in-package import direction (grep '^from app.schedule' per file)
period: repository, plan     state: binding, creative, period, plan, repository, tree_approval
performance: binding, repository, state, creative     diagnosis: performance, state, tree     binding: repository, tree
```

## Contradiction check

- **Check 1 (`win` at conservative 1.5 vs break-even 1.0) vs. check 3 (tenant isolation)**: an input with the same
  `external_id` bound in two orgs (Meta ids are global) — the spend rows are read through `bound_account_ids_for_brand`
  and `org_id`, so org B's rows never reach org A's bucket; check 3 must seed that exact input (same external id, two
  orgs) or it proves nothing.
- **Check 1 vs. `period.node_level_spend()`'s ownership rule (ADR 0053 §4, ties split evenly)**: this ticket scores
  spend on the period's own `[start_date, end_date]` days without the tie split. Input that shows it: two periods
  overlapping on a day with the same bound node — brand-level `settled_spend` splits that day, the node row counts
  it fully. Settled here: the node row is a per-node reading, not a money ledger; `settled_spend` stays the money of
  record. The reviewer checks the docstring says so.
- **Plan review 2026-09-08 (Opus) on the spec, folded in here**: depth 1 dropped and depths never summed (the same
  money sits on every level; `node_level_spend()` is pinned to `adset` for the same reason); `breakeven_source`
  stored because today's 1.0 comes from a 100% margin the user has not filled; the acceptance step expects
  all-`unclear` rows because the bound campaign has no spend.
- **Cheapest wrong implementation that leaves every check green**: (a) reading the tree's *current* bindings
  (`bindings_by_node_key`) instead of the period's tree (`bindings_for_tree` with the membership's
  `source_tree_task_id`) — passes with one tree in the DB; check 2 (resettle) must bind a second tree first and
  assert the rows still name the first tree's `source_tree_task_id`; (b) `verdict` computed from optimistic ROAS
  only — caught by check 1's `lose` case only if day A roas 0.5 gives optimistic 0.5 < 1.0 *and* a second case
  (day A roas 1.2, day B None → conservative 0.6, optimistic 1.2) gives `unclear`, so add that case to check 1.
