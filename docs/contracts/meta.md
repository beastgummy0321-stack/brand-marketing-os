# Contract — meta (the Meta ad platform adapter)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-03 at T3 station ①, because a route C ticket touches this module and a module
is registered before it is changed.

## Entry path

`app/meta/__init__.py` for registration. `graph.py`, `repository.py`, `routes.py` and
`daily_pull.py` are private to the package **with one written exception**: `app.schedule` reads
`app.meta.repository` and `app.meta.graph` directly (`app/schedule/routes.py:60`,
`app/schedule/period.py:17-18`), which the schedule contract lists as an allowed dependency.
That exception is read-only use of query functions; no other module has it, and nothing outside
this package writes this module's tables.

## Exported shapes

```
register(app: FastAPI) -> None      # mounts /api/meta/*
register_task() -> None             # idempotently registers the daily spend-pull
                                    # procrastinate task against the current
                                    # app.background.app()
```

Callers: `app/main.py`'s register loop (both), and `app/tests/test_meta_daily_spend.py`, which
calls `register_task()` again after building its own test `background.app()`.

Read functions `app.schedule` is allowed to call, listed by their tenant boundary rather than
their signature, because the boundary is the part of the shape that matters:

- Filter on `org_id` in SQL before they reach the platform: `get_token`, `list_accounts`,
  `bound_account_ids_for_brand`, `spend_summary`, `last_pull_at`, and
  `campaign_ids_by_exact_name` (which re-checks the caller's `ad_account_ids` against
  `meta_ad_account WHERE org_id = …` before asking Meta anything).
- **`ad_set_ids_by_exact_name` does not**, and this is written down rather than smoothed over.
  It uses `org_id` only to fetch the token, and passes the caller's `campaign_id` straight to
  Meta. What keeps it inside one tenant today is the call site, not the function: its only
  caller (`app/schedule/binding.py`) can only ever hand it a campaign id that either
  `campaign_ids_by_exact_name` just returned from this org's own ad accounts, or that
  `bindings_by_node_key` read back under `org_id = … AND brand_id = …`. Found at T3c review;
  there is no reachable request that breaks it, and there is also no second line of defence.
  `BOARD.md` carries the debt.

Tables this module owns: `meta_credential`, `meta_ad_account`, `brand_meta_ad_account`,
`meta_entity_spend`. Account tables stay one per channel — there is no generic account table,
by decision (ADR 0055 §8).

## Error shapes

- Route errors: `web.ApiError(status, code, message)` — a stable `code` plus a user-facing
  Chinese `message`.
- Graph failures: `graph.GraphError`, raised by `graph.fetch_page` and its callers. A read
  function that cannot reach Meta either raises `web.ApiError(502, "meta_unreachable", …)`
  (`repository.campaign_ids_by_exact_name:244`) or is swallowed by the pull loop
  (`daily_pull`'s `except GraphError: continue`) — never both in one path.
- The token never leaves this module. `get_token` decrypts from Vault for this module's own
  reads; `get_credential` returns the tail only.

## Must not import or touch

- `app.main`, `app.schedule`, `app.dashboard` — nothing that imports this module.
- Any other module's tables; `app_setting`; `procrastinate_*` internals.
- The Graph API's `reach` field and any breakdown parameter on insights — documented at
  `graph.py:_INSIGHT_METRIC_FIELDS`, because adding one silently shortens readable history from
  37 months to 13 and the missing data looks exactly like "we were not running then".

## Decisions in force

- ADR 0039 — the daily-pull worker rides inside the web process (owed back before cloud).
- ADR 0043 — one bucket, and the org id is the first folder (Vault/storage shape this module
  follows for its token).
- ADR 0050 — the ad-loop data model of record: this module's table changes and their tickets.
- ADR 0052 — a logged-in request runs as `authenticated` with an `app.org_id` claim.
- ADR 0055 — a node is identified by a path key and a channel; what stays Meta-specific and why.
