---
id: 0063
decision: The procrastinate worker runs as its own process, `python -m app.worker`, on every environment including this laptop.
applies-to: [app/background/, app/main.py, app/llm/gateway.py, app/tools/boot_launcher.py, 啟動行銷系統.bat, 關閉行銷系統.bat]
supersedes: [0039]
status: in-force
---

# The worker is its own process, everywhere

ADR 0039, which this one supersedes, put the procrastinate worker on a thread inside the
uvicorn process and wrote its own
expiry date: *"On the move to cloud … that is the point at which `start_worker()` /
`stop_worker()` stop being called from `lifespan` and become their own entry point."* This is
that change, taken before the cloud rather than on the day of it.

(`app/worker.py` is created by the ticket this ADR was written for; it joins `applies-to`
above in the same commit that creates it, because the index refuses a path that does not exist.)

**`python -m app.worker` is the worker. `app/main.py` starts no worker, on any environment.**
Locally, `啟動行銷系統.bat` opens it in a second (minimised) window and
`app/tools/boot_launcher.py` spawns it as a child of the web process, so the number of things
the user clicks stays at one — rule 6, automation is addition, and ADR 0034, a feature must
remove work, not relocate it.

## Why not keep riding in-process locally and split only in the cloud

That option was on the table and is rejected: it is two deployment shapes, and the cloud one
would never run on the machine anyone develops on. Constitution rule 1 says single-machine is
today's deployment and never a design premise; rule 3 says opening a deferred thing must be
flipping a switch, not a rewrite. A branch on `BRAND_OS_ENV` inside `lifespan` is exactly the
switch that only ever gets tested in one position. Cost of the option taken: two console windows
locally instead of one, and a shutdown script that kills by window title as well as by port.

## What this changes about interrupted work, and why that is not a detour

`app/llm/gateway.py`'s `fail_interrupted_tasks()` marks every `llm_task` row still in `running`
as failed, on the assumption that a fresh process means no such row can still be alive. Under
the superseded ADR 0039 the web process and the worker were the same process, so the web's `lifespan` was a
correct place to run it. **After this ADR it is not**: restarting the site while the worker is
mid-job would mark a live job failed, and the user would be told to press again for work that is
still running and still being paid for.

The caller moves to `app/worker.py`'s startup, before the worker takes its first job. The
invariant is unchanged in strength — one worker process owns every `running` row, and it owns
none at the moment it boots. The `ponytail:` note in that function is corrected accordingly: the
day it needs a heartbeat or an age check is the day there is **more than one worker process**
(cloud autoscale), not the day the worker left `lifespan`.

## What we looked at (reuse-first §2)

- **procrastinate's own CLI** (`procrastinate --app=… worker`, shipped in 3.9.0 as
  `.venv/Scripts/procrastinate.exe`): rejected, and worth recording why so nobody re-proposes
  it. `--app` loads a dotted path that must already **be** a `procrastinate.App`; ours is
  `app.background.app()`, a function, because the App is rebuilt whenever `DATABASE_URL` changes
  (ADR 0062 §5a). The CLI also registers no tasks — `meta.register_task()` and
  `schedule.register_tasks()` run in the assembly root — so a CLI worker would start, find every
  task name unknown, and quietly do nothing.
- **Celery / RQ / APScheduler**: not looked at again. The queue decision is ADR 0038 and is not
  reopened by moving where the worker runs.
- The entry point therefore reuses what exists: `import app.main` for `.env`, logging and task
  registration — the same line `app/meta/daily_pull.py`'s `__main__` block already uses for the
  same reason — plus procrastinate's own `App.run_worker()`.

## Consequences

- `app/worker.py` is a second assembly-root sibling of `app/main.py`, not a file inside
  `app/background/`: task registration lives in the assembly root, and `app/background` may
  never import upward (`LAYER_ORDER`, `app/tests/test_architecture_boundaries.py`).
- `app/background/__init__.py` loses `start_worker()`, `stop_worker()` and all of the thread and
  loop plumbing they needed. The win32 event-loop policy switch stays: `App.run_worker()` builds
  its loop with `asyncio.run()`, which reads the policy, and psycopg's async pool still cannot
  run on a `ProactorEventLoop`. The module's entry points become `app()`, `enqueue()`.
- `app/main.py` loses its `lifespan` entirely — with the worker gone and
  `fail_interrupted_tasks()` moved, nothing was left in it.
- A worker that dies no longer takes anything down and no longer needs to swallow its own
  failures to protect the site: it is allowed to crash loudly in its own window. the superseded ADR 0039's
  "a worker that cannot start must not take the site down" is satisfied structurally instead.
- `關閉行銷系統.bat` gains a window-title kill for the worker window. The autostart path needs
  nothing new: the worker is a child of the launcher process and the existing
  `taskkill /PID … /T` already takes the tree.
- The cron trigger time (`0 3 * * *`, server-local) is **not** part of this ADR and stays as
  ADR 0039 left it before being superseded here. Since ticket 04-1b the date being pulled comes from the org's timezone
  (`_pull_one_account`) and `daily_pull` re-pulls a 7-day attribution window every run, so the
  hour the trigger fires no longer decides which day gets labelled what. It becomes real work
  only when a hosted deployment's local time is meaningfully different from every tenant's, and
  that is a scheduling decision to take with the platform, not before it.
- The hole the superseded ADR 0039 named honestly — nobody pulls the days the machine is off — is **not** closed
  by this ADR and never was its job. `daily_pull.backfill()` (ticket S1) is the path that closes
  it, and a hosted worker is what makes it stop mattering.
