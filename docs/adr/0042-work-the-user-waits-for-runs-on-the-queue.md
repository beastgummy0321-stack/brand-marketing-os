---
id: 0042
decision: Any generation the user waits for is deferred to the queue; the request validates, enqueues and returns.
applies-to: [app/schedule/jobs.py, app/background/]
supersedes: none
status: in-force
---

# Work the user waits for runs on the queue, not in the request

Ticket 05-1, 2026-08-30. The three schedule generations — plan, campaign tree, ad creative — ran
their LLM call inside the HTTP request. The person had to keep the tab open for two to six
minutes, and killing the process mid-request left an `llm_task` row `running` forever, which the
screen reports as "still going" and never leaves.

**Any generation the user waits for is deferred to the procrastinate queue. The request
validates, enqueues and returns; the worker does the work.**

## What the numbers said

Measured from this project's own `llm_task` rows on 2026-08-30, not from a benchmark:

| task_type | succeeded avg | max | timeout | orphan |
|---|---|---|---|---|
| `schedule_plan` | 106 s | 171 s | 1 × 362 s | — |
| `schedule_tree` | 139 s | 252 s | 3 × 362 s | 1 row `running` since 2026-08-29 09:08 |
| `schedule_creative` | 29 s (n=1) | — | — | — |

Four timeouts and one permanently stuck row out of nineteen runs. The orphan was cleared by this
ticket's startup sweep on first boot, which is the cheapest possible proof that the sweep works.

## The three rulings behind it (user, 2026-08-30)

1. **An interrupted run is marked failed, never re-run automatically.** A re-run spends a second
   LLM call on work that may have been nearly finished. The screen says it was interrupted and
   the person presses again. The manual path stays the decision-maker (rule 6).
2. **One run at a time, per brand per task type.** A second press while one is running is refused
   with a message, not queued: queueing spends twice for a result only the last one is visible as.
   Two mechanisms, because one does not cover the window the other does — procrastinate's
   `queueing_lock` (whose unique index is `WHERE status = 'todo'`) closes "pressed twice before
   the worker picked it up", and a check on the `llm_task` row closes "pressed again while it is
   actually running".
   **Amended the same day: the subject is the work item, not (brand, task type).** The refusal
   rule above is unchanged; only what counts as "the same run" moves. The lock strings and the
   reasoning are at the end of this file, under "Amended 2026-08-30".
3. **This is now the pattern.** Any future generation the user has to wait for is built this way
   from the start: background job, closing the tab costs nothing, interrupted means interrupted.
   This ADR is the memo the user asked for so the next slice does not re-decide it.

## What was deliberately not built

- **`cancel`.** BOARD.md called this ticket "`enqueue`／`status`／`cancel`". Nothing has ever
  needed to stop a run mid-flight and no screen offers it. `enqueue` is the only new public shape
  on `app/background`.
- **A status endpoint, a status table, a status field.** Status already exists: the `llm_task`
  row, which `_display_task_row` publishes as `running: boolean` and the screen already polls
  every two seconds. Adding a second source of truth for the same fact is how they drift apart.
- **The five in-memory `JobRegistry` jobs** (brand library, product research, brand report, two
  in the intake wizard). They lose their work on restart the same way, but nothing has measured
  pain on them, so they stay where they are. They remain on the board's list.

## The seam that had to be pinned

A job that re-reads "the newest row for this brand" at run time is reading a moving target: the
one-at-a-time rule is **per task type**, so a different type's job can insert a newer `running`
row in the gap between enqueue and run. `tree_from_task_row` returns an empty tree for a running
row without raising, so the creative job would have built a prompt around an empty campaign and
spent money on it. (Amended 2026-08-30: the one-at-a-time rule is no longer per task type. The pin
survives the change and matters more under it — with N producers live for one brand, "the newest
row for this brand" is not merely a moving target, it is the wrong row most of the time.)

**The source row's id is pinned into the job's arguments at enqueue time.** The request already
found and validated that row; the job loads exactly it, by id. This is the same pattern the
creative run already used one level down (`context_scope_json.source_plan_task_id`).

## The ceiling, and when this expires

The startup sweep marks **every** `running` row failed, which assumes one process owns all of
them. That is exactly where ADR 0039 stands today ("the worker rides inside the web process,
until a second machine exists"). When the worker becomes its own process, the sweep must become
heartbeat- or age-based — the same day `start_worker()` leaves `lifespan`, not a separate one.

Stale procrastinate jobs left `doing` by a crash are not touched: procrastinate never re-runs
them on its own, they hold no `queueing_lock`, and at this volume they cost nothing.

## What we looked at

Nothing new was adopted. procrastinate was already installed and its worker already running
(ticket 01, ADR 0038/0039); this ticket only gave it more work. `queueing_lock`, `SyncPsycopgConnector`
and `configure_task(allow_unknown=True)` are the library's own features, read out of the pinned
3.9.0 source rather than from memory.

One trap is worth recording so it is not re-discovered: **the worker's `PsycopgConnector` cannot
be used to defer from a request thread.** Its async pool is opened on the worker thread's own
loop, `get_sync_connector()` returns that same async connector while the pool is open, and every
sync call then routes through `async_to_sync`, which drives the coroutine on a brand-new event
loop. Deferring uses a second, module-private `App` on a `SyncPsycopgConnector`. This is the same
family of mistake as ADR 0039's Windows loop bug, and it was avoided by reading the library, not
by testing until it worked.

## Consequences

- `app/background` gains `enqueue(task_name, *, org_id, lock, **kwargs) -> bool` and nothing else.
- `app/schedule` gains `register_tasks()` and a private `jobs.py`; `routes.py` shrank from 798 to
  661 lines because the work moved out of it.
- `app/llm` gains `fail_interrupted_tasks(conn)`, called once from `_lifespan` before the worker
  starts — before, so it cannot mark this boot's own live jobs as interrupted.
- `app/schedule` still never imports `procrastinate`. The queue is reachable only through
  `app/background`'s entry point.

## Amended 2026-08-30: the lock's subject is the work item

Amended the same day it was written, and not because it was wrong. Ruling 2 was correct for what
existed: one plan, one tree, one creative call per brand, each a single big LLM call that nothing
else could usefully overlap. The ad loop specced the same day produces many small calls of the
same type at once — one producer per tree node, one analyst per node per period. Under the lock as
built, the second of them is refused: `enqueue()` returns `False` for a duplicate lock
(`app/background/__init__.py:175-185`), the endpoint turns that into a 409 `already_running`
(`app/schedule/routes.py:94`), and the fan-out stops at one node with a message that is true and
useless. That is not a bug for a slice to fix. It is this ruling, and it changes here.

Amended in place, no successor ADR (user ruling, 2026-08-30), so this file stays the one place the
rule is read. **Rulings 1 and 3 stand exactly as written** — an interrupted run is still marked
failed and never re-run automatically, and the queue is still the pattern for any generation the
user waits for — and so does everything under "What was deliberately not built": parallel
production buys no `cancel`, no status table, no second source of truth for `running`.

**Ruling 2's subject moves from (brand, task type) to the work item.** One run at a time per
*thing being produced*. The refusal, its message and its reason are unchanged: a second press on
the same work item is still refused rather than queued, because queueing still spends twice for a
result only the last one is visible as. Only what counts as "the same run" changes.

The lock strings, literally. This table is the authority — a slice that writes a different string
is wrong, not merely inconsistent. Four of these subjects postdate this ADR, so they are named
here rather than left to the slice: a **period** is one run of the ad loop with its own dates; the
**producer** writes one deepest tree node's ad copy; the **analyst** reads one node's numbers for
one period; the **onboarding** read imports one campaign that already exists on the platform,
before any period exists; the **writer** turns the analysts' conclusions into that period's single
adjustment.

```
planner    schedule_plan:{brand_id}                     unchanged - one global judgement at a time
producer   schedule_creative:{tree_task_id}:{node_key}
analyst    schedule_analysis:{period_id}:{node_key}
onboarding onboarding_read:{ad_account_id}:{campaign_id}
writer     schedule_review:{period_id}
```

The planner keeps the old shape on purpose: its subject really is the brand, and one global
judgement at a time is the decision there, not a leftover.

**Ruling 2 named two mechanisms, and this moves both.** The `queueing_lock` half is the table
above, and nothing resists it: no code takes a lock apart, no test asserts its format, and
Postgres holds it as opaque text under one unique index on the whole value
(`supabase/migrations/20260829000001_background_baseline.sql:119`, `:148`). The other half — the
check on the `llm_task` row that closes "pressed again while it is actually running"
(`app/schedule/routes.py:407`, `:433`, `:458`) — asks whether the *newest* row for this brand and
this task type is `running` (`:146-148`), and left alone it would refuse producer 2 for exactly
the reason the lock stopped refusing it. Its subject moves the same way: the newest row for *this
work item*. The whole cost of this amendment sits in that second half, which is the read path.

**The read side must still never let a run in progress hide an already-finished result.** That
rule — the 2026-08-29 fix in `_display_task_row` (`app/schedule/routes.py:138-154`, its docstring
at `:141-144` recording the finished 12,815-character tree the next attempt hid) — survives this
amendment untouched. Its implementation does not. `_display_task_row` and `_latest_task_row` both
find their row with `ORDER BY started_at DESC LIMIT 1` over brand and task type (`:150-151` and
`:131-132`), and "newest" names the right row only while there is exactly one of them. With N
producers live for one brand, the newest is one of N and the screen shows some other node's work.
The replacement is the key the lock now carries: the row is found by its work item — the period,
or the tree node — never by being the most recent. This ADR rules that; the slice that fans
production out implements it.

**Every `background.*` task still carries `org_id`.** ADR 0038 put the tenant in the task
arguments and `app/tests/test_background.py:130` gates it. More jobs of one type means more rows
each carrying `org_id`, not an exemption for any of them. A lock string is not a tenant boundary
and must not be read as one, however many ids it now holds.

**`approval.scope_ref` moves from the approved tree's `llm_task` id to the period.** ADR 0040
predicted this in as many words: *"The day a second concurrent subject of the same type exists,
this lookup needs a subject key — and `scope_ref` will already be holding the right value for
it."* (`docs/adr/0040-approval-is-the-money-brake.md:88-89`). That day is the period slice. A
brand accumulates period after period, so `latest()` filtering on `org_id + brand_id + scope_type`
alone (`app/core/approval.py:59-60`) would let one period's approval answer for another period's
spend — the money path, and the worst place to be approximately right. Both halves move together
and neither is optional: the stored value becomes the period, and the lookup gains the period as a
key. Whether `scope_type` keeps the string `schedule_tree` is a naming question the slice settles;
what this amendment forbids is leaving the lookup keyed on brand and type alone once one brand has
more than one period.

One correction cannot be made where it is written. The approval migration explains at length that
`scope_ref` holds the tree's own `llm_task` id and is deliberately not what the lookup filters on.
Applied migrations are never edited in this repo, so that comment stays and is wrong from the day
the period lands; this paragraph is where it is corrected. The same explanation in
`app/core/approval.py:51-57` and `app/schedule/routes.py:192-197` is ordinary prose and the slice
rewrites it, along with the one test that pins the current value (`app/tests/test_approval.py:174`)
— re-pointed at the period, never loosened to assert less.

**Nothing goes red the day this is written; it is a document.** The lock format is untested: the
one test in this area (`app/tests/test_schedule.py:480-510`) takes its 409 from the `llm_task`
running check rather than from the lock, and the three branches where `enqueue()` returns `False`
(`app/schedule/routes.py:413`, `:439`, `:466`) have no test at all — which is how a wrong lock
string could ship unnoticed, so the slice that implements the table above brings that test with
it. What that test protects is money: a lock too broad refuses a producer silently, one too narrow
lets the same node be produced and paid for twice. That slice also moves the frozen `app/schedule`
line count in `app/tests/test_architecture_boundaries.py` (1452 on the day this was written) and,
if it adds test lines, `TEST_LINES_CEILING` — each in the same diff as the written reason for
moving it (ADR 0041).
