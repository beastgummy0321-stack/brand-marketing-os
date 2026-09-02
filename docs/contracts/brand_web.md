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

**One live breach, recorded rather than hidden**: `app/dashboard/routes_jobs_api.py:16-18`
imports `active_jobs` out of three route files directly, bypassing `register()`. That is the
in-memory job dict named in BOARD.md as debt; a ticket that touches those three files fixes the
import direction or leaves it exactly as it is — it does not add a fourth.

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
`app.storage`.

## Decisions in force

- ADR 0027 — multi-tenant cloud SaaS on Supabase; every table carries `org_id`.
- ADR 0036 — hardcoded domain knowledge is deleted.
- ADR 0043 — one bucket, and the `org_id` is the first folder.
- ADR 0052 — a logged-in request runs as role `authenticated` with an `app.org_id` claim.
- ADR 0053 — the product economics screen saves a version from today; the 「生效日」 input goes.
