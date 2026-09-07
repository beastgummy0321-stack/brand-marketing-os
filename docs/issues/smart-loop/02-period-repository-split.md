# 02 — Move the period and node-result SQL out of `repository.py` (`period_repository.py`)

Route C: module boundary (a file split inside `app/schedule/`, no behaviour change). Board row 越排越好. Scheduled
**before** cut 2 (last period into prompts) because that cut needs a new read ("latest settled period") and
`app/schedule/repository.py` is at exactly 800 lines, the cap held by `FileLineCapTest` (measured 2026-09-08 after
ticket 01). Per workflow "a boundary escalation is not a menu": the READ-ONLY inventory of 2026-09-08 answered what
the file may contain and where every function goes; this ticket executes that answer. Nothing is carved out "to
make room"; the two groups that move are the two that handle money-adjacent rows, which is a boundary of its own.

## What

Literal example: N/A — a pure move; every function keeps its signature and return shape, so the contract's literal
shapes are the ones already in the docstrings of the moved functions (e.g. `period_node_results()` still returns the
list of dicts ticket 01 documented). Only the module path of eleven names changes.

New file `app/schedule/period_repository.py`, private to the package, imports only `app.core.db` (`Conn`,
`ConnProxy`, `jsonb`, `new_id`, `now_utc` as needed) — **no `from app.schedule …` import at all** (the moved code
uses none today; verified by the inventory: `repository.py`'s only in-package import is `creative.COORDINATE_KEYS`,
used by the coordinate group that stays).

Moves, verbatim (bodies, docstrings and section comments unchanged; only the file changes):

- section `# ---- campaign_period（票 T2b，ADR 0053）` (`repository.py:399-505`): `upsert_draft_period`,
  `get_latest_period`, `get_period`, `list_non_draft_periods`, `approve_draft_period`,
  `advance_period_to_awaiting_data`, `write_settlement`.
- section `# ---- Ticket smart-loop 01 (ADR 0066): period_node_result` (`repository.py:690-757`):
  `period_node_memberships_for_period`, `replace_period_node_results`, `_NODE_RESULT_NUMERIC_COLS`,
  `period_node_results`.

Stays in `repository.py`: coordinates (1–273), creative loop persistence (274–369), feedback (370–398),
bindings / `channel_entity_map` (506–637), `period_node_membership` (638–689), brand-delete cleanup (758–800,
including `_CHILD_TABLES` with `period_node_result` and the `cleanup.register` call — deletion stays with the
module's one registry).

Callers change their import only (`from app.schedule import period_repository as period_repo`) and their call
sites (`schedule_repo.<name>` → `period_repo.<name>`) for the eleven names above, nowhere else:
`app/schedule/period.py`, `app/schedule/routes.py`, `app/schedule/binding.py` (`get_latest_period`),
`app/schedule/scoring.py` (`get_period`, `period_node_memberships_for_period`, `replace_period_node_results`).
No test calls any of the eleven directly (scan below). `docs/adr/0066` line 41 names
`schedule_repo.period_node_results()` — update that one mention to `period_repo`.

Contract page `docs/contracts/schedule.md`: the entry-path file list gains `period_repository.py`; the
import-direction paragraph gains one sentence: `period_repository` imports nothing from the package and is imported
by `period`, `routes`, `binding`, `scoring`.

## How we know it's done

Run with `BRAND_OS_LLM_PROVIDER` unset.

1. `git diff --stat` shows `app/schedule/repository.py` losing exactly the lines of the two sections and no other
   line changed in it; `wc -l app/schedule/repository.py` ≤ 630 and `wc -l app/schedule/period_repository.py` ≤ 200
   (inventory estimate 173 code lines + header + imports). Report both numbers.
2. `git grep -n "schedule_repo\.\(upsert_draft_period\|get_latest_period\|get_period\|list_non_draft_periods\|approve_draft_period\|advance_period_to_awaiting_data\|write_settlement\|period_node_memberships_for_period\|replace_period_node_results\|period_node_results\)"` → zero hits.
3. `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule_period.py app/tests/test_schedule.py app/tests/test_schedule_performance.py app/tests/test_brand_delete.py app/tests/test_architecture_boundaries.py -q` green, **with no change to any test file** and no ratchet constant moved: production line total is unchanged by a move (plus the new file's header — if `_module_sizes()["app/schedule"]` grows past 4278 by the header lines only, raise the constant to the measured value with the reason "file split, header lines"; nothing else).
4. `cd frontend && npm run e2e` (the one end-to-end smoke; frontend untouched).
5. Red proof: none needed for a move — the suite in check 3 is the proof; run it once before the move (green) and once after.
6. Acceptance: restart backend + worker, open 排程 for `brd_bughunt`, the settled period 2026-09-07 still shows its
   10-row node table (data unchanged, read path moved).

## Shared files touched

Files edited or created: `app/schedule/period_repository.py` (new), `app/schedule/repository.py`,
`app/schedule/period.py`, `app/schedule/routes.py`, `app/schedule/binding.py`, `app/schedule/scoring.py`,
`docs/contracts/schedule.md`, `docs/adr/0066-settling-a-period-scores-every-bound-node.md` (one mention),
`app/tests/test_architecture_boundaries.py` only if check 3's header-lines clause triggers.

Every name that changes its module, scanned whole-repo 2026-09-08 (docs/issues excluded; the `def` lines in
`repository.py` omitted):

```
### git grep -n "upsert_draft_period"
app/schedule/routes.py:255:    period_id = schedule_repo.upsert_draft_period(
### git grep -n "get_latest_period"
app/schedule/binding.py:99:    # （`schedule_repo.get_latest_period`），不是另開一條。沒有檔期（這個品牌從沒出過
app/schedule/binding.py:103:    period = schedule_repo.get_latest_period(conn, org_id, brand_id)
app/schedule/period.py:7:`schedule_repo`；本檔只讀（`schedule_repo.get_latest_period()` 等）＋算。
app/schedule/period.py:260:    一列，見 `schedule_repo.get_latest_period()` 的說明），`None` 代表這個品牌從沒出過
app/schedule/period.py:262:    period = schedule_repo.get_latest_period(conn, org_id, brand_id)
app/schedule/routes.py:193:    period = schedule_repo.get_latest_period(conn, org_id, brand_id)
app/schedule/routes.py:222:    current_period = schedule_repo.get_latest_period(conn, org_id, brand_id)
app/schedule/routes.py:330:    current_period = schedule_repo.get_latest_period(conn, actor.org_id, brand_id)
app/tests/test_schedule_period.py:204:        period was 'latest' (schedule_repo.get_latest_period()). Fixture for the ticket's
### git grep -n "get_period"
app/schedule/period.py:304:    租戶界線在 `schedule_repo.get_period()` 的 WHERE 裡（`org_id`／`brand_id` 都要對得上，
app/schedule/period.py:307:    period = schedule_repo.get_period(conn, org_id, brand_id, period_id)
app/schedule/routes.py:401:    `schedule_repo.get_period()` 的 WHERE 裡，不是靠 `require_brand` 就夠——`brand_id`
app/schedule/routes.py:411:    settled_period = schedule_repo.get_period(conn, org_id, brand_id, period_id)
### git grep -n "list_non_draft_periods"
app/schedule/period.py:273:        competitors = schedule_repo.list_non_draft_periods(conn, org_id, brand_id)
app/schedule/period.py:313:    competitors = schedule_repo.list_non_draft_periods(conn, org_id, brand_id)
### git grep -n "approve_draft_period"
app/schedule/routes.py:383:    schedule_repo.approve_draft_period(conn, org_id, brand_id)
### git grep -n "advance_period_to_awaiting_data"
app/schedule/period.py:252:    schedule_repo.advance_period_to_awaiting_data(conn, org_id, period["id"])
### git grep -n "write_settlement"
app/schedule/period.py:335:    schedule_repo.write_settlement(
### git grep -n "period_node_memberships_for_period" / "replace_period_node_results"  (only the untracked scoring.py)
app/schedule/scoring.py:65:    period = schedule_repo.get_period(conn, org_id, brand_id, period_id)
app/schedule/scoring.py:68:    memberships = schedule_repo.period_node_memberships_for_period(conn, org_id, brand_id,
app/schedule/scoring.py:122:    return schedule_repo.replace_period_node_results(conn, org_id, brand_id, period_id, rows)
### git grep -n "period_node_results"
app/schedule/period.py:295:        "node_results": schedule_repo.period_node_results(conn, org_id, brand_id, period["id"]),
docs/adr/0066-settling-a-period-scores-every-bound-node.md:41:   for prompts and screens go through `schedule_repo.period_node_results()`; the scoring code lives in
### git grep -n "_NODE_RESULT_NUMERIC_COLS"
app/schedule/repository.py:752:        for c in _NODE_RESULT_NUMERIC_COLS:
### section markers in repository.py (grep -n '^# ----')
274 creative loop persistence | 370 feedback | 399 campaign_period | 506 bindings | 638 period_node_membership |
690 period_node_result | 758 brand-delete cleanup
### import lines in repository.py
29:from app.core import cleanup
30:from app.core.db import Conn, ConnProxy, jsonb, new_id, now_utc
31:from app.schedule.creative import COORDINATE_KEYS
```

## Contradiction check

- **Check 1 (only the two sections' lines leave `repository.py`) vs. check 2 (zero `schedule_repo.<moved>` hits)**:
  the docstring mentions in `period.py:7,260,304` and `routes.py:401` and `binding.py:99` are prose naming
  `schedule_repo.get_latest_period` / `get_period`; check 2's regex matches them. Resolution: those prose mentions
  are updated to `period_repo` in the same diff (they are in caller files, not in `repository.py`, so check 1 holds).
- **Check 3 (no test file changes) vs. the ratchet**: a split adds a module header and import block (~10–30
  lines) to `_module_sizes()["app/schedule"]`; the constant is at the measured value 4278, so the gate goes red
  by exactly those lines. The clause in check 3 authorises raising it by that measured amount only; an implementer
  who instead trims docstrings to stay at 4278 is doing the thing this ticket forbids (making room).
- **Cheapest wrong implementation that leaves every check green**: leaving thin wrappers in `repository.py` that
  re-export the moved names (`get_period = period_repo.get_period`) — check 2 stays green because callers were
  switched, check 1 fails on the line count only if the wrappers are many. The reviewer greps `repository.py` for
  the eleven names: zero hits expected.
