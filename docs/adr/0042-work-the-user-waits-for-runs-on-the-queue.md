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
spent money on it.

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
