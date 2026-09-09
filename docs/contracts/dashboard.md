# Contract — dashboard (駕駛艙: read-only, cross-module aggregation)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-09 at workbench ticket 05 station ①, because that route C ticket edits a row in
this module's jobs table and a module is registered before it is changed.

## Entry path

`app/dashboard/__init__.py` (`register(app)`). `routes.py`, `routes_jobs_api.py`, `repository.py`,
`guide_cards.py`, `health.py` are private and imported by nothing outside the package.

## Exported shapes

```
register(app: FastAPI) -> None      # mounts /api/dashboard/* and /api/jobs/active
```

Routes: `GET /api/dashboard/overview` (cross-brand overview), `GET /api/dashboard/brands/{brand_id}/month`
(one brand's month), `GET /api/jobs/active` (the top-right bell: running background jobs across the
organisation, aggregated from `llm_task` rows by `task_type` through the table at the top of
`routes_jobs_api.py` — one row per task type it knows: kind key + Chinese stage text). A task type
absent from that table is invisible to the bell; a module that adds a task type adds its row there
in the same ticket.

## Error shapes

`web.ApiError` / `web.NotFound` as everywhere; `require_actor` + `require_brand` on brand routes. No
writes — every handler is a read; a failure is the reader's 4xx, never a stored state.

## Must not import or touch

- `app.main`, `app.schedule` internals beyond the entry-point exports it already uses, `procrastinate_*`.
- Never writes any table (this module owns none; no migrations, no cleanup registration).

Allowed dependencies (read-only): `app.core` (interrupts, config), `app.shared.web`,
`app.brand_intelligence.repository`, `app.intake.state`, `app.meta.repository`,
`app.orders.repository`, `app.schedule` (entry-point exports only, e.g. `imported_ad_count`).

## Decisions in force

- ADR 0036 — no hardcoded domain knowledge; guide cards point at data the user vets.
- ADR 0062 — environment declared, not sniffed (`routes.py` reads `settings`).
- ADR 0067 — the past-ads guide card counts `imported_ad` through the schedule entry point.
- ADR 0068 — workbench generation tasks (`workbench_*`) appear in the bell as one row (ticket 05).

Module-local and reversible, decided here rather than in an ADR:

- The bell's stage text mirrors the source screen's own waiting text; it is never a second wording.
