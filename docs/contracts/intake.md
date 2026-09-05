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

**Three reaches past `register()`, all measured, none of them new:**

- `app/dashboard/repository.py:19` — `from app.intake import state as intake_state`, used at
  `:116` for `intake_state.get_draft(...)`. Reaches a private file.
- `app/dashboard/routes_jobs_api.py:19` — `from app.intake.routes_api import active_jobs`.
  Reaches a private file. This is the last survivor of the breach `docs/contracts/brand_web.md`
  recorded; ticket 08 removed the three brand_web ones, ticket 09 removes this one.
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

Background job failures are **recorded, never swallowed and never left to escape**: each job
runner wraps its body in `try/except Exception`, writes `status="failed"` plus `error=str(exc)`
into its registry and calls `notify()` (`persona_generation.py:131-146`;
`routes_api.py:262-284`, `:290-307`, `:323-342`). `JobRegistry.start()`
(`app/brand_intelligence/background_job.py:47-62`) has no `try/except` of its own, so that safety
net exists only because each caller builds it — `routes_api.py:271` calls itself "the last line of
defence for a background thread; an exception must not vanish into thin air".

## Must not import or touch

- `app.main`, `app.dashboard`, `app.schedule`, `app.meta`, `app.brand_web` — nothing that
  imports this module.
- Another module's tables. This module owns exactly two: `intake_draft` and `intake_item`
  (`supabase/migrations/20260826000003_intake_baseline.sql:6,37`). Two known read-only breaches
  are already on the SQL-scan ledger: `ai.py:39` and `state.py:81` `SELECT … FROM brand` directly
  instead of going through `brand_intelligence.repository`. It also reads `llm_task`
  (`repository.py:186`), which `app.core` owns; that table has no single owner in practice and
  `app/schedule/state.py` and `app/brand_web` read it the same way.
- `procrastinate_*` internals. `app.background` is the only door — and today this module does not
  use it at all: a grep for `procrastinate` in `app/intake/` returns nothing, because its four
  background kinds still run on threads. Ticket 09 changes that.

Allowed dependencies, from real import statements rather than intent: `app.core` (`net`, `db`,
`settings`, `cleanup`, `audit`, `vocab`), `app.brand_intelligence` (`customer_voice`,
`repository`, `personas`, `background_job`), `app.llm` (`gateway`, `providers`,
`context_compiler`), `app.shared.web`, `app.storage`.

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
- **Two separate `JobRegistry` instances, and no written reason for two.** `_JOBS`
  (`routes_api.py:209`) carries `scan` / `question` / `paste_fix`; `JOBS`
  (`persona_generation.py:11`) carries persona generation. Both are `{brand_id: {status, stage,
  started_at, error, …}}`, purely in memory, empty after a restart, and their key spaces do not
  meet. `JobRegistry` also never evicts a finished job — its docstring
  (`app/brand_intelligence/background_job.py:21-24`) marks that a deliberate shortcut with a
  `ponytail:` note: single machine, one person, low generation rate, add a TTL when high-frequency
  use makes it real.

## Measured (facts this module's next ticket must not re-discover)

- `app/intake/*.py` is **3,545 lines**. The three largest files: `routes_api.py` **750**,
  `repository.py` **701**, `state.py` **517**. The project's per-file cap is 800, so
  `routes_api.py` sits at 94% of it with about 50 lines of headroom. A ticket that would push it
  over stops and reports rather than carving out the smallest function or registering the file as
  known-oversized (`workflow.md`, "A boundary escalation is not a menu").
- `__init__.py:8` claimed drafts live in a `state.py` dict called `DRAFTS` and vanish on restart.
  No such name exists any more: `state.py:1-7` says every read and write goes through
  `repository.py` into the `intake_draft` table and a restart resumes. The stale line was
  corrected when this page was written, 2026-09-05.
