# Contract — background (the job queue)

Five things and nothing else (container contract §1). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-05, ahead of the worker-own-process slice, because a route C ticket touching a
module registers that module first. It records the module as that slice leaves it: `app()` and
`enqueue()` are the whole surface; `start_worker()` / `stop_worker()` are gone, along with
ADR 0039, which is superseded by ADR 0063.

## Entry path

`app/background/__init__.py`. One file, no sub-modules. `app/worker.py` — the worker process
itself — is **not** part of this module: it lives beside `app/main.py` because starting a worker
needs the assembly root's task registration, and `app/background` may never import upward
(`LAYER_ORDER`, `app/tests/test_architecture_boundaries.py`).

## Exported shapes

```
app() -> procrastinate.App
    # The App the worker runs and tasks register against. Rebuilt whenever db.dsn() changes
    # (each test module gets its own schema; ADR 0062 §5a keeps DATABASE_URL uncached so this
    # comparison still sees the change). Callers: app/meta (register_task), app/schedule
    # (register_tasks), app/worker.py, this module's own tests.

enqueue(task_name: str, *, org_id: str, lock: str, **kwargs) -> bool
    # Defer one job. False (never an exception) when a job with this queueing_lock is already
    # sitting in `todo`. org_id travels as a task argument, not as a queue column (ADR 0038).
    # Callers: app/schedule/routes.py's three POST endpoints, app/brand_web's three
    # (customer voice, product research, brand report), app/intake's four (scan, question,
    # paste-fix, persona), this module's own tests.

is_active(lock: str) -> bool
    # True while a job carrying this queueing_lock is still `todo` or `doing`. The signal a
    # caller needs to refuse a second press: `llm_task` cannot answer it, because its running
    # row is written just before the provider call, not when the job is claimed — measured
    # 2026-09-05, ticket 08, where that window let a paid call run twice. Reads through
    # procrastinate 3.9.0's own `JobManager.list_jobs(queueing_lock=…, status=…)`; the
    # `queueing_lock` column is never cleared on finish (`procrastinate_finish_job_v1` touches
    # only status/abort_requested/attempts), so a finished lock reads False.
    # Callers: app/brand_web/routes_products.py, app/brand_web/routes_report_api.py,
    # app/intake/routes_api.py, app/intake/persona_generation.py.
```

Every registered task takes `org_id` as a parameter — held by
`app/tests/test_background.py::TaskSignatureOrgIdGateTest`, not by convention.

## Error shapes

`app()` propagates psycopg and procrastinate errors unwrapped; a caller that cannot reach
Postgres has nothing this module can usefully say about it. `enqueue()` is the one place that
converts an exception into a value: `procrastinate.exceptions.AlreadyEnqueued` becomes `False`.
Blocking a second press while a job is *running* is `is_active()`'s job, not `enqueue()`'s: the
`queueing_lock` unique index only covers `status = 'todo'`, so `enqueue()` alone leaves a window
between the worker claiming a job and the provider call starting. Ticket 08 measured that window
letting a paid LLM call run twice. `is_active()` returns a value, never raises.

## Must not import or touch

- Anything above `app.core` in `LAYER_ORDER` — including `app.main` and `app.worker`. The
  dependency runs the other way: feature modules import `app.background`.
- Another module's tables. This module owns no tenant table at all; the four procrastinate
  tables live in their own `<current_schema()>__queue` namespace.
- `procrastinate schema --apply` and every other procrastinate CLI/schema internal. The schema
  is vendored into `supabase/migrations/20260829000001_background_baseline.sql` and managed by
  the Supabase CLI like every other table.
- The job bodies. Handlers live in the module that owns the data they touch (`app/meta`,
  `app/schedule`); this module only carries them.

## Decisions in force

- ADR 0038 — the queue is infrastructure, not a tenant table; `org_id` travels in the job args.
- ADR 0042 — work the user waits for runs on the queue.
- ADR 0062 — `DATABASE_URL` is the one environment variable read live rather than cached,
  because `app()` needs to see it change.
- ADR 0063 — the worker is its own process (`python -m app.worker`) on every environment.

Module-local and reversible, decided here rather than in an ADR:

- `enqueue()` builds a second, module-private `App` on a `SyncPsycopgConnector` instead of
  reusing `app()`. `app()`'s async pool belongs to the worker process's loop, and deferring from
  a request thread through it drives that pool on a foreign loop. Both Apps follow the same
  "DSN changed → rebuild" rule.
- The win32 `WindowsSelectorEventLoopPolicy` switch at import stays: psycopg's async pool cannot
  run on a `ProactorEventLoop`, and `App.run_worker()` builds its loop with `asyncio.run()`,
  which reads the policy.
