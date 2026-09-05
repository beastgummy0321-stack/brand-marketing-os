# Contract — intake (the onboarding wizard)

Five things and nothing else (container contract §1). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-05, ahead of ticket 09, because a route C ticket touching a module registers that
module first. It records what `app/intake/` **is**, not what it should be; every line below was
measured, and where the module's own comments disagree with the code that is said here rather
than smoothed over.

## Entry path

`app/intake/__init__.py`, one function:

```
register(app: FastAPI) -> None   # mounts two routers
```

The eleven other files (`ai.py`, `card_test.py`, `paste_parse.py`, `persona_generation.py`,
`repository.py`, `routes.py`, `routes_api.py`, `routes_t2_api.py`, `script.py`, `state.py`,
`truth_card.py`) are private.

**Two reaches past `register()`, both measured, neither of them new:**

- `app/dashboard/repository.py:19` — `from app.intake import state as intake_state`, used at
  `:116` for `intake_state.get_draft(...)`. Reaches a private file. **This is now the only one of
  its kind left in the repo**: ticket 08 removed the three into `app/brand_web`, ticket 09 removed
  `app/dashboard/routes_jobs_api.py`'s `from app.intake.routes_api import active_jobs`, and the
  breach paragraph `docs/contracts/brand_web.md` used to carry is gone with them.
- `app/core/settings.py:315` — `from app.intake import script` **inside a function**, for
  `script.DEFAULT_BUDGET` only. A deferred import is invisible to
  `test_architecture_boundaries.py::_import_time_modules` by design, so this is a deliberate way
  around the static cycle check, not a hidden violation. It stays until someone moves
  `DEFAULT_BUDGET` somewhere both modules can see.

**Do not add a fourth.** A module that wants something out of intake asks for it through
`__init__.py`.

## Exported shapes

`register(app)` and nothing else. Everything this module produces reaches the outside as HTTP
JSON under the two routers it mounts.

## Error shapes

This module does **not** use `web.ApiError`; an unscoped grep for `ApiError` in `app/intake/`
returns nothing. It has two shapes of its own, and the rest of the backend has a third, so a
client meets three different error bodies depending on which endpoint it called:

- `_error(status_code, message) -> JSONResponse` returning `{"error": "<string>"}`
  (`routes_api.py:54-55`, `routes_t2_api.py:22-23`). No stable `code` field.
- `raise NotFoundKind(kind)` (`routes_api.py:201,567`, `routes.py:31`) — a
  `StarletteHTTPException(404, detail=kind)` rendered by FastAPI's default handler as
  `{"detail": kind}`.
- Everywhere else in this backend: `web.ApiError` → `{"error": {code, message, details}}`.

That divergence is recorded, not endorsed:
`docs/issues/deploy/issue-intake-error-shape-diverges.md`.

Background job failures are **recorded, never swallowed and never left to escape**: each
`background.intake_*` handler wraps its body in `try/except Exception`, marks the run failed and
calls `notify()`. Since ticket 09 the durable record is the `llm_task` row, not a process-local
dict, so a restart no longer erases a failure.

One narrow honesty gap, inherited from ticket 08's template rather than introduced here: if the
**post-processing** after a successful LLM call throws (saving the scan result, replacing
personas, applying a paste), the handler still returns normally, so the next status poll reads
`done` even though a failure notification was already sent.
`docs/issues/deploy/issue-post-processing-failure-reads-as-done.md` carries it for both modules.

## Must not import or touch

- `app.main`, `app.dashboard`, `app.schedule`, `app.meta`, `app.brand_web` — nothing that
  imports this module.
- Another module's tables. This module owns exactly two: `intake_draft` and `intake_item`
  (`supabase/migrations/20260826000003_intake_baseline.sql:6,37`). Two known read-only breaches
  are already on the SQL-scan ledger: `ai.py:39` and `state.py:81` `SELECT … FROM brand` directly
  instead of going through `brand_intelligence.repository`. It also reads `llm_task`
  (`repository.py:186`), which `app.core` owns; that table has no single owner in practice and
  `app/schedule/state.py` and `app/brand_web` read it the same way.
- `procrastinate_*` internals. `app.background` is the only door, and since ticket 09 this module
  uses it: all four background kinds (initial scan, next question, paste-fix, persona generation)
  are `background.intake_*` tasks registered by `register()`, enqueued with `enqueue()` and gated
  with `is_active()`. Nothing here touches a `procrastinate_*` table directly.

Allowed dependencies, from real import statements rather than intent: `app.core` (`net`, `db`,
`settings`, `cleanup`, `audit`, `vocab`), `app.brand_intelligence` (`customer_voice`,
`repository`, `personas`, `background_job` — now only `notify()`; the `JobRegistry` class went
with ticket 09), `app.llm` (`gateway`, `providers`, `context_compiler`), `app.shared.web`,
`app.storage`, `app.background`.

## Decisions in force

- ADR 0021 — personas get their own brand-layer table; photo product cards stay inside the intake
  draft JSON.
- ADR 0043 — one bucket, and the org id is the first path segment. Cited at `state.py:344` for
  the pending-photo key shape, and **missing from the ADR index for this module's paths** — the
  index returns only 0021 for `app/intake`. Recorded here so the next reader does not conclude it
  does not apply.

Module-local and reversible, decided here rather than in an ADR:

- **`PENDING_PHOTOS` (`state.py:358`) holds metadata only.** It maps an upload token to
  `[{"name", "size_mb", "storage_key"}]` for photos uploaded before a draft exists. The bytes are
  already in Supabase Storage under `<org_id>/intake/<token>/<filename>`, so a restart loses the
  list, never the files. Its own restart weakness is
  `docs/issues/deploy/issue-intake-pending-photos-dict.md`.
- **A draft that is abandoned mid-flight leaves orphan Storage objects.** `discard_pending_photos`
  (`state.py:392-395`) deliberately does not delete them; declared out of scope by ticket
  storage-03 and unchanged since.
- **The queueing lock is per kind, not per brand.** Ticket 09 replaced the two in-memory
  `JobRegistry` instances with `background.enqueue(..., lock=f"intake_{kind}:{brand_id}")`. The old
  registry keyed on `brand_id` alone, so starting a scan blocked a question for the same brand;
  the new lock does not. Measured at review: the wizard's own step preconditions
  (`routes_api.py:479-486`, `draft["scan_done"]` / `draft["qa_done"]`) mean no real request
  sequence starts two kinds at once for one draft, so nothing observable changed — but a future
  caller that ignores those preconditions would get concurrency the old shape refused.
- **Pressing the same kind twice is refused by `background.is_active(lock)`,** not by reading
  `llm_task`. Ticket 08 measured why: the `running` row is written just before the provider call,
  so a check against `llm_task` is blind in the window after the worker claims a job, and a paid
  call ran twice there. All four kinds are gated; a kind that minted a fresh key per press would
  not need one, and none of these four does.

## Measured (facts this module's next ticket must not re-discover)

- `app/intake/*.py` is **3,571 lines** after ticket 09 (3,545 before). `routes_api.py` went from
  **750** to **716**; `repository.py` 701 and `state.py` 517 are unchanged. The project's per-file
  cap is 800, so `routes_api.py` still sits at 90% of it. A ticket that would push it over stops
  and reports rather than carving out the smallest function or registering the file as
  known-oversized (`workflow.md`, "A boundary escalation is not a menu").
- **Ticket 09 was written under ratchet pressure and it shows in the shape.** Both
  `KNOWN_MODULE_SIZES["app/intake"]` and `TEST_LINES_CEILING` went red mid-implementation, and the
  implementer — correctly forbidden from raising either — compressed its own diff instead: three
  `_start_*` functions merged into one `_start(kind, …)`, three `_notify_*_done` into one, three
  status builders into `_job()`. The review checked each merge against the pre-image and found the
  per-kind stage text, notification wording, status keys and error paths preserved. Recorded
  because the next reader will find parameterised functions where per-kind ones used to be, and
  should know that shape came from a number, not from a design.
- `__init__.py:8` claimed drafts live in a `state.py` dict called `DRAFTS` and vanish on restart.
  No such name exists any more: `state.py:1-7` says every read and write goes through
  `repository.py` into the `intake_draft` table and a restart resumes. The stale line was
  corrected when this page was written, 2026-09-05.
