# Contract — brand_web (the web layer of brand intelligence)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-02, ahead of the T2 slice, because a route C ticket touching a module registers
that module first. It records what `app/brand_web/` **is**, not what it should be.

## Entry path

`app/brand_web/__init__.py`, one function:

```
register(app: FastAPI) -> None   # mounts seven routers under /api/*
```

The seven route files (`routes.py`, `routes_brand_settings.py`, `routes_inbox.py`,
`routes_library.py`, `routes_library_write.py`, `routes_products.py`, `routes_report_api.py`)
plus their helpers (`routes_product_helpers.py`, `product_ai_calls.py`, `report_service.py`) are
private and imported by nothing outside the package.

The breach recorded here until 2026-09-05 is gone: `app/dashboard/routes_jobs_api.py` no longer
imports `active_jobs` out of this module's route files. Ticket 08 moved customer-voice extraction,
product research and brand report onto the queue, deleted their three dicts, and the aggregate
now reads job state itself. `app/intake`'s own dicts are the last ones left; ticket 09 removes
them. **Do not add a fourth direct import from another module into these route files.**

`register(app)` now also registers this module's three `background.*` tasks, idempotently — the
worker process needs them, and `register()` stays the module's only export.

## Exported shapes

`register(app)` and nothing else. Everything this module produces reaches the outside as HTTP
JSON under `/api/brands/...`, `/api/products/...`, `/api/inbox/...`, `/api/library/...`.

## Error shapes

Route errors are `web.ApiError(status, code, message)` — a stable `code` plus a user-facing
Chinese `message`, rendered by `app/shared/web.py`. Tenant boundary errors come from
`require_brand` before any field validation runs; a `ValueError` raised by
`brand_intelligence.repository` is caught at this layer and turned into a 400.

## Must not import or touch

- `app.main`, `app.schedule`, `app.meta`, `app.intake`, `app.dashboard`.
- Another module's tables. This module owns **no tables at all** — it is a web layer. Every
  write goes through `brand_intelligence.repository` or `app.core`; it never issues SQL against
  `product_economics`, `brand`, `official_asset` or `interrupt` itself.
- `procrastinate_*` internals. `app.background` is the only door.

Allowed dependencies: `app.brand_intelligence`, `app.core`, `app.llm`, `app.shared.web`,
`app.storage`, and — added 2026-09-05, ticket 08 — `app.background`, for `enqueue()` and
`is_active()`. `procrastinate_*` is still reached through that module and nowhere else.

## Decisions in force

- ADR 0027 — multi-tenant cloud SaaS on Supabase; every table carries `org_id`.
- ADR 0036 — hardcoded domain knowledge is deleted.
- ADR 0043 — one bucket, and the `org_id` is the first folder.
- ADR 0052 — a logged-in request runs as role `authenticated` with an `app.org_id` claim.
- ADR 0053 — the product economics screen saves a version from today; the 「生效日」 input goes.
- ADR 0042 — work the user waits for runs on the queue.
- ADR 0063 — the worker is its own process; these three jobs run there, not in the web process.
