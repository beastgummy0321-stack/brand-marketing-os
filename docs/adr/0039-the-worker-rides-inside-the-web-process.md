---
id: 0039
decision: The procrastinate worker is an asyncio task inside the uvicorn process, until a second machine exists.
applies-to: [app/main.py, app/background/]
supersedes: none
status: in-force
---

# The worker rides inside the web process, until a second machine exists

Ticket 05 needed a daily Meta spend pull that runs unattended. Procrastinate was already
installed (ticket 01, ADR 0038) and its tables already live in their own schema, but nothing in
this deployment ran a worker: jobs could be deferred and nothing would ever pick them up.

**The worker is an asyncio task inside the existing uvicorn process, started and stopped by
FastAPI's `lifespan`.** No second process, no OS scheduler, no supervisor.

Approved by the user on 2026-08-29 after the ticket 05 review round raised it. The implementer
made the call, flagged it as a rule 9 question rather than hiding it, and the user ratified it.

## Why this is rule 6, not rule 9

Constitution rule 9 requires a plan and approval before core architecture changes. Rule 6 says
the manual path stays a first-class citizen and automation is additive.

`啟動行銷系統.bat` already starts exactly one long-lived process and the user already leaves it
running; that is the deployment shape, and it is unchanged. What was added is a second job for
a process that was already there. The manual trigger stayed:
`uv run python -m app.meta.daily_pull` still works and is still the path a person uses when they
want the numbers now.

The alternative that was rejected — telling the user to keep a second terminal open running
`procrastinate worker` — relocates work onto the user instead of removing it, which ADR 0034
forbids outright.

## What this costs, stated plainly

- **The pull only happens while the site is open.** Close the window overnight and that day's
  rows are not pulled. The handler is idempotent and pulls by date, so the next run catches up
  the day it is asked for — but nothing catches up a day nobody asked for. This is honest for a
  desktop deployment and dishonest for a cloud one.
- **One worker, one process.** Two copies of the app running against the same database means two
  workers competing for the same queue. Procrastinate's locking makes that safe, not wrong, but
  it was not designed for here.
- **The cron time (`0 3 * * *`) is server-local with no timezone handling.** A few hours' drift
  does not change whether today got pulled. It will matter the moment two organisations are in
  two timezones; ticket 04-1b's `org_timezone` is where that gets solved, not here.

## When this decision expires

**On the move to cloud.** A multi-tenant deployment separates the web process from the worker
process — web scales on request volume, workers scale on queue depth, and a worker that dies
must not take the site down with it. That is the point at which `start_worker()` /
`stop_worker()` stop being called from `lifespan` and become their own entry point.

Until then, building the split now would be a second deployment shape maintained for a machine
that does not exist. Rule: build only what has hurt.

## Consequences

- `app/background/__init__.py` gains `start_worker()` / `stop_worker()` alongside `app()`. They
  are idempotent and cancel cleanly; the module still owns no table and still exposes one entry
  point (container contract §1).
- `app/main.py` gains a `lifespan=` and calls only those two shapes. It does not import
  procrastinate and does not know what a worker is.
- Ticket 05-1's remaining scope shrinks to the `enqueue` / `status` / `cancel` contract and the
  job registry. The worker entry point is done.
- `install_signal_handlers=False` is required, not optional: the worker shares uvicorn's event
  loop, and installing its own signal handlers fights uvicorn's Ctrl+C and SIGTERM handling.

## Amended 2026-08-29: it rides in the process, not on the loop

The first implementation put the worker on **uvicorn's own event loop**, and the site would not
start at all. Booting it produced `PoolTimeout: pool initialization incomplete after 30.0 sec`
out of the FastAPI lifespan, then `Application startup failed. Exiting.` and exit code 3 — with
the log filling up with psycopg saying, plainly, that it *cannot use the ProactorEventLoop to
run in async mode*.

Two mistakes, and the second is the one worth remembering.

**Windows gives uvicorn a loop psycopg cannot use, and the policy fix does not reach it.** The
module already switched the process policy to `WindowsSelectorEventLoopPolicy` at import, which
was the right diagnosis and the wrong lever: `Server.run` hands `asyncio_run` an explicit
`loop_factory` from `config.get_loop_factory()`, and `asyncio_loop_factory` returns
`ProactorEventLoop` on win32 outright. uvicorn never consults the policy, so nothing riding its
loop can benefit from one. The worker now owns **its own thread and its own loop**, built by
`asyncio.run()`, which does read the policy. That is the difference between "in the process" and
"on the loop", and only the first was ever the decision.

**A worker that cannot start must not take the site down.** The exception propagated out of
`lifespan`, so the price of the daily pull failing was that nothing opened at all — the
dashboard, the scheduling page, the settings screen, all of it. This ADR argued the worker was
*additive* under rule 6, and an addition that can remove the whole primary path is not additive.
`start_worker()` now logs and swallows every failure, and `python -m app.meta.daily_pull` is
still there. That belongs in the cost list above and was missing from it.

**Why no test caught it:** nothing started the application through its real lifespan. The
worker test called `start_worker()` / `stop_worker()` directly, because driving the lifespan
under this file's pytest fixtures hangs — a limitation its own docstring recorded. Testing
around the failing path is how the failing path survived. The replacement test asserts the
invariant that actually protects the site: `start_worker()` never raises. It was proven red by
restoring the old fatal behaviour, then green.

`install_signal_handlers=False` is still required, for a smaller reason than before: the worker
is no longer on uvicorn's loop, but it is still not the main thread, and signal handlers can
only be installed there.
