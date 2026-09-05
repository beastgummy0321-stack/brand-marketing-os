# 09 — the intake trio and persona generation move onto the queue, and the bell sees all seven

Route C (module boundary). Second half of `issue-in-memory-background-jobs.md` (2026-09-05),
under ADR 0042. **Dispatch only after ticket 08 has shipped** — 08 proves the pattern on the
three simple kinds; this one applies it to the four awkward ones and deletes the last dict.

User's decision, 2026-09-05: **per-step progress is given up rather than paid for with a schema
change.** `llm_task` gains no `stage` column. The intake initial scan stops reporting
"正在看照片（第 N／M 張）" and reports only running / done / failed.

## What

Four kinds still run as a dict plus a thread:

| kind | starts at | status endpoint | screen |
|---|---|---|---|
| 建檔精靈初掃 (`kind=scan`) | `app/intake/routes_api.py:209,285` | `:370` | `useIntakeJob.ts:43` |
| 建檔精靈出題 (`kind=question`) | `app/intake/routes_api.py:307` | `:431` | `useIntakeJob.ts:43` |
| 貼上修格式 (`kind=paste_fix`) | `app/intake/routes_api.py:350` | `:629` | `useIntakeJob.ts:43` |
| 人物誌生成 | `app/brand_intelligence/persona_generation.py:11,155`, `routes_t2_api.py:145,176` | `routes_t2_api.py:149` | `PersonaSection.tsx:47` |

All four already write a `llm_task` row through `app/llm/gateway.py:198` `run_task()` (INSERT at
`:114-146`) — `app/intake/ai.py:45` and `persona_generation.py:95` are the entry points. No new
table, no new column. Copy the same template ticket 08 used
(`app/schedule/jobs.py:332-341` · `app/schedule/routes.py:257-263` · `app/background/__init__.py:152-162`
· `app/schedule/state.py:57-82`), and obey the same two hard rules: handler's first parameter is
`org_id` (`app/tests/test_background.py` `TaskSignatureOrgIdGateTest` scans `background.*`), and
the handler opens its own `app.core.db.connection()`.

Three things specific to this half:

1. **The initial scan's per-photo callback goes away.** `app/intake/routes_api.py:258-279` runs
   `on_photo_progress` and writes the dict repeatedly at `:264-269`. Delete the callback and the
   plumbing behind it; the screen shows a running state and then the result. This is the user's
   explicit decision, not a shortcut — if the callback turns out to be load-bearing for something
   other than the progress text, stop and report rather than keeping the dict alive.
2. **The bell is wrong today and this ticket fixes it.** `app/dashboard/routes_jobs_api.py:26`
   aggregates only four of the seven kinds (`:35-36`) — persona generation has never appeared in
   it, so a user watching the bell can believe nothing is running while a paid LLM call is in
   flight. After this ticket the aggregate reads the queue, so all seven are visible by
   construction. `ActiveJobsBell.tsx:32` polls every 8s and keeps that cadence; its stale comment
   at `:15-18` ("既有三個", while the code already handles four) is corrected in the same commit.
3. **Delete the remaining `JobRegistry` instances and the `threading.Thread` at
   `app/brand_intelligence/background_job.py:69`.** After this ticket
   `grep -rn "threading.Thread" app/` returns nothing under `app/` outside the test tree. A dict
   kept "just in case" is the bug.

Literal example — the one deliberate behaviour change, and the one bug fixed:

```json
{"intake scan status, before": {"state": "running", "stage": "正在看照片（第 3／12 張）"},
 "intake scan status, after":  {"state": "running", "stage": "處理中"},
 "GET /api/jobs/active, before": "four kinds; a running persona generation is invisible",
 "GET /api/jobs/active, after":  "all seven kinds, including persona generation"}
```

Every other status payload keeps the keys and types it has today.

Out of scope, and each gets its own issue file instead: `app/intake/state.py:359`
`PENDING_PHOTOS` (a second module-level dict — it holds token→metadata only, the bytes are
already in Storage at `:388`, so it is a different problem in the same file), and restoring
per-step progress later.

Response shapes and URLs do not change. `useIntakeJob.ts` and `PersonaSection.tsx` are **not**
edited except where the scan's progress text is displayed; `ActiveJobsBell.tsx` changes only its
comment. Any other frontend edit is `blocked-upstream`.

## How we know it's done

1. `uv run ruff check app` — clean. `uv run pyright` — 0 errors.
   `cd frontend && npm run typecheck && npm run build` — clean (the scan progress text is a
   frontend-visible removal).
2. `grep -rn "threading.Thread\|JobRegistry" app/ --include=*.py` returns nothing outside
   `app/tests/`. Paste the output.
3. **Restart test**, on the initial scan: start a scan, restart the backend mid-run, then poll
   `app/intake/routes_api.py:370` and assert the run is still reported — not the idle default.
   In `app/tests/test_intake_api.py`. Proven red once: read status from a process-local dict
   again, watch it report idle, restore.
4. **The bell shows all seven.** New assertion in `app/tests/test_dashboard_jobs_boundary.py`
   (which today clears only 3 of 5 registries at `:21-26` and never asserts the report kind at
   all): start a persona generation and assert it appears in `GET /api/jobs/active`. Proven red
   once against `main`, where it cannot appear.
5. `uv run pytest app/tests/test_intake_api.py app/tests/test_intake_api_paste.py app/tests/test_dashboard_jobs_boundary.py app/tests/test_background.py app/tests/test_architecture_boundaries.py -q` — green.
   Persona generation has **no test today** (an unscoped grep for `persona` hits only
   `test_library_write_api.py:249`, an unrelated field, and `test_action_url_targets.py`, which
   only checks URL shape), so check 4 is its first one.
6. `python -m app.worker` registers all seven `background.*` tasks. Paste the lines.
7. `cd frontend && npm run e2e` — green, `supabase start` up and the worker running.
8. `git diff --name-only` matches `## Shared files touched`.

## Shared files touched

```
app/intake/routes_api.py:209,258-279,264-269,285,307,350,370,431,629
app/intake/ai.py:45
app/intake/state.py:359,388                  (PENDING_PHOTOS — NOT touched, issue file instead)
app/brand_intelligence/persona_generation.py:11,95,155
app/brand_intelligence/routes_t2_api.py:145,149,176
app/brand_intelligence/background_job.py:69,79-82
app/dashboard/routes_jobs_api.py:26,35-36
app/llm/gateway.py:114-146,198               (not edited)
app/background/__init__.py:152-162 · app/schedule/jobs.py:332-341 · app/schedule/routes.py:257-263 · app/schedule/state.py:57-82 · app/worker.py:58   (the template, read only)
app/tests/test_intake_api.py · test_intake_api_paste.py · test_dashboard_jobs_boundary.py:21-26 · test_background.py
frontend/src/…/useIntakeJob.ts:43            (only where the scan progress text is shown)
frontend/src/…/ActiveJobsBell.tsx:15-18,32   (comment only)
frontend/src/…/PersonaSection.tsx:47         (must NOT change)
supabase/migrations/20260826000001_core_baseline.sql:45-73   (llm_task — not edited)
docs/adr/0042 · docs/adr/0038 · docs/adr/0063 · docs/contracts/background.md
```

## Contradiction check

Done-check 2 (no `JobRegistry`, no `threading.Thread` left) and done-check 3 (the scan's status
survives a restart) can contradict each other: an implementer who cannot make the queued scan
report cleanly can satisfy 2 by deleting the dict and satisfy 3 by making the status endpoint
return "running" whenever a `llm_task` row exists in any state — which reports a run that
finished an hour ago as still running, forever. The input that shows it: let a scan finish, then
poll the endpoint. It must report done, and a scan that failed must report failed, not running.
Add that as the second half of check 3.
