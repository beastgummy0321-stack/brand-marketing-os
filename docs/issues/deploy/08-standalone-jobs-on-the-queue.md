# 08 — the three standalone background jobs move onto the queue

Route C (module boundary). First half of `issue-in-memory-background-jobs.md` (2026-09-05),
under ADR 0042. Ticket 09 finishes the other four.

User's decision, 2026-09-05: **all seven kinds move, and per-step progress is given up rather
than paid for with a schema change.** So this ticket adds no column and no table.

## What

Every background job in this repo is still "a module-level dict plus a `threading.Thread`". The
only thread creation in the codebase is `app/brand_intelligence/background_job.py:69`; there is no
`BackgroundTasks`, no `asyncio.create_task`, no `ThreadPoolExecutor`. Restarting the backend
empties the dict, and the screen quietly falls back to its idle default — the user is never told
the work died. On a cloud host that restart happens on every deploy, and with more than one
instance the polling request may not even reach the instance holding the dict.

**The issue file said five jobs; there are seven.** The two it missed are `paste_fix`
(`app/intake/routes_api.py:350`) and persona generation
(`app/brand_intelligence/persona_generation.py:11,155` + `routes_t2_api.py:145,176`); ADR 0042's
own count (`docs/adr/0042-work-the-user-waits-for-runs-on-the-queue.md:58-60`) was already short
on the day it was written. This ticket takes the three that stand alone; ticket 09 takes the
intake trio and persona.

| kind | starts at | status endpoint | screen |
|---|---|---|---|
| 品牌智庫抽原話 | `app/brand_web/routes_library.py:334` | `GET …/customer-voice/jobs/{key}` (`:420`) | `CustomerVoiceTab.tsx:49` |
| 產品調研 | `app/brand_web/routes_products.py:176` | `…/research-status` (`:304`) | `ProductDetailPage.tsx:96` |
| 顧問報告 | `app/brand_web/routes_report_api.py:22` | `GET /api/brands/{id}/report` (`:112`) | `BrandReportPage.tsx:50` |

**No new table is needed.** All three already write a `llm_task` row before doing anything —
every one of them goes through `app/llm/gateway.py:198` `run_task()`, which INSERTs at `:114-146`
into `llm_task` (`supabase/migrations/20260826000001_core_baseline.sql:45-73`). The row exists;
nobody reads it as a status source yet. That is the whole change: read the row instead of the
dict.

Copy the pattern that ADR 0042 already shipped, end to end — do not invent a second one:

- register: `app/schedule/jobs.py:332-341` (`register_tasks()` → `a.task(name=f"background.{task_type}")(func)`), called from `app/schedule/__init__.py:42-46`, picked up through `app/worker.py:58`'s `import app.main`;
- enqueue: `app/schedule/routes.py:257-263` — validate, then `background_enqueue(f"background.{TASK_TYPE}", org_id=…, lock=f"{TASK_TYPE}:{brand_id}", **kwargs)` → `app/background/__init__.py:152-162` (`configure_task(...).defer()`; a taken lock returns False → HTTP 409);
- read: `app/schedule/state.py:57-82` (`_latest_task_row` / `_display_task_row` — while a run is in flight the screen still shows the previous successful result, which is the behaviour to reproduce);
- poll: `app/schedule/routes.py:405-409` ← `SchedulePage.tsx:167,180-184` (polls every 2s only while running).

Two hard requirements from `app/worker.py:58` and ADR 0038: the handler's **first parameter must
be `org_id`** (gated by `TaskSignatureOrgIdGateTest` in `app/tests/test_background.py`, which
scans everything named `background.*`), and the handler opens its own
`app.core.db.connection()` — the worker inherits no request connection.

The three HTTP status endpoints keep their URLs and their response shape. The frontend files in
the table above are **not** edited by this ticket: if a screen has to change, the response shape
changed, and that is `blocked-upstream`.

Delete, in this ticket, the three `JobRegistry` dicts these three jobs used, and any helper left
with no caller. A dict that survives "for safety" is the bug this ticket exists to remove.

Literal example — the status payload each of the three endpoints returns must keep the keys and
types it has today; only where the value is read from changes:

```json
{"endpoint": "GET /api/brands/{brand_id}/report",
 "before": {"source": "process-local dict", "after a backend restart": "idle default, as if nothing ever ran"},
 "after":  {"source": "the llm_task row", "after a backend restart": "the same run, still reported"}}
```

Capture the real JSON body of each of the three endpoints on `main` before you start, and diff it
against yours at the end. Same keys, same types.

Out of scope: the four intake/persona kinds (ticket 09), `app/dashboard/routes_jobs_api.py`
(ticket 09), any column added to `llm_task`, any change to `app/llm/gateway.py`.

## How we know it's done

1. `uv run ruff check app` — clean. `uv run pyright` — 0 errors.
2. `grep -rn "threading.Thread" app/` shows the thread is still used only by the four kinds
   ticket 09 owns — the number of `JobRegistry` instances drops by three. Paste both greps.
3. **The restart test, which is the whole point.** For one of the three (顧問報告 is the
   simplest): enqueue it, kill and restart the backend while it runs, then call the status
   endpoint and assert it still reports the run — not the idle default. Add it to
   `app/tests/test_brand_report_api.py` as a test that clears the process's own state (the
   queue row must be the only source). Proven red once: point the status read back at a
   process-local dict, watch it report idle, restore.
4. `uv run pytest app/tests/test_library_api.py app/tests/test_products_api.py app/tests/test_product_scan.py app/tests/test_brand_report_api.py app/tests/test_brand_report.py app/tests/test_background.py app/tests/test_dashboard_jobs_boundary.py app/tests/test_architecture_boundaries.py -q` — green.
5. `python -m app.worker` starts and logs the three new `background.*` tasks as registered. Paste
   the lines.
6. `cd frontend && npm run e2e` — green, with `supabase start` up and the worker running.
7. `git diff --name-only` matches `## Shared files touched`; no file under `frontend/src` may
   appear.

## Shared files touched

Unscoped repo-wide search for the names that stop existing or change meaning — the three
`JobRegistry` instances, their status readers, and `threading.Thread`:

```
app/brand_intelligence/background_job.py:69,79-82
app/brand_web/routes_library.py:334,420
app/brand_web/routes_products.py:176,304
app/brand_web/routes_report_api.py:22,112
app/llm/gateway.py:114-146,198               (already writes llm_task — read only, not edited)
app/background/__init__.py:152-162           (enqueue — read only, the template)
app/schedule/jobs.py:332-341                 (registration — the template)
app/schedule/__init__.py:42-46
app/schedule/routes.py:257-263,405-409       (the template)
app/schedule/state.py:57-82                  (the template)
app/worker.py:58
app/dashboard/routes_jobs_api.py:26,35-36    (aggregates 4 of 7 today — ticket 09, not this one)
app/tests/test_library_api.py
app/tests/test_products_api.py
app/tests/test_product_scan.py
app/tests/test_brand_report_api.py
app/tests/test_brand_report.py
app/tests/test_dashboard_jobs_boundary.py:21-26
app/tests/test_background.py                 (TaskSignatureOrgIdGateTest)
supabase/migrations/20260826000001_core_baseline.sql:45-73   (llm_task — not edited)
frontend/src/features/…/CustomerVoiceTab.tsx:49              (must NOT change)
frontend/src/…/ProductDetailPage.tsx:96                      (must NOT change)
frontend/src/…/BrandReportPage.tsx:50                        (must NOT change)
docs/adr/0042-work-the-user-waits-for-runs-on-the-queue.md:58-60
docs/adr/0038 · docs/adr/0063 · docs/contracts/background.md
```

## Contradiction check

Done-check 3 (status survives a restart) and done-check 7 (no frontend file changes) can
contradict each other: the cheapest way to survive a restart is to change the status payload into
whatever `llm_task` happens to hold, which changes the shape the three screens parse — and the
e2e in check 6 may not go red, because these screens show a spinner and then text, not a value
the smoke asserts. The input that shows it: call each of the three status endpoints before, during
and after a run and compare the JSON keys against `main`. Same keys, same types, or it is
`blocked-upstream`. Where the queue genuinely cannot express a state the old dict expressed,
report it — do not approximate it.
