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

`register()` also mounts two routes for the 37-month backfill (ticket past-ads/02, ADR 0067
§1.8): `POST /api/meta/brands/{brand_id}/backfill` enqueues `background.meta_backfill` for the
brand's organisation (`{"started": bool, "running": true}`; another organisation's brand → 404;
no bound account → 409 `no_bound_account`) and `GET /api/meta/brands/{brand_id}/backfill` reads
its progress (`{"running": bool, "earliest_spend_date", "latest_spend_date", "ad_rows"}` from
`daily_pull.backfill_status`). One backfill per organisation, not per brand — `daily_pull.backfill()`
itself is org+account scoped.

Read functions `app.schedule` is allowed to call, listed by their tenant boundary rather than
their signature, because the boundary is the part of the shape that matters:

- Filter on `org_id` in SQL before they reach the platform: `get_token`, `list_accounts`,
  `bound_account_ids_for_brand`, `spend_summary`, `daily_entity_spend` (T3e, widened at T5 —
  the same `org_id`/`ad_account_ids`/`level` boundary as `spend_summary`, one row per day per
  entity instead of one aggregate per entity; carries `impressions`/`clicks`/`roas`/`currency`
  alongside `spend` now, still no cross-day honesty logic — that stays Python-side in
  `app/schedule/performance.py`, ADR 0057 §1), `last_pull_at`, and `campaign_ids_by_exact_name`
  (which re-checks the caller's `ad_account_ids` against `meta_ad_account WHERE org_id = …`
  before asking Meta anything).
- **`ad_set_ids_by_exact_name` and `ad_ids_by_exact_name` refuse a parent id that is on record
  as another organisation's** (ticket 06, 2026-09-05). Before fetching the token and before any
  Meta call they read `channel_entity_map` for `external_id = <the parent id> AND org_id != <this
  org>`; a hit raises `web.ApiError(403, "campaign_not_owned" | "adset_not_owned", …)`. The table
  belongs to `schedule`; reading it from here follows the same precedent as `channel_credential`
  (ADR 0056 §4). `campaign_ids_by_exact_name` keeps its own, stricter check against
  `meta_ad_account WHERE org_id = …`, because at that level an owning table exists.
  **Known residual, deliberate: the check is fail-closed on conflict, fail-open on unknown.** An
  id no organisation has ever bound still reaches Meta on this org's token. Closing that would
  need either a table mapping every Meta id to an org (none exists) or a per-node Graph read the
  ticket ruled out; and `AdSetMatchUnreachableTest` / `AdMatchUnreachableTest` require an
  unbound id to reach Meta. `bind_tree` writes each binding row before recursing into that
  node's children, so the open branch is unreachable from the only caller that exists today.
  `docs/issues/deploy/issue-meta-unknown-parent-id-fail-open.md` carries it.
- **`budgets_for_bound_ids` filters by a positive list, not a negative one** (ticket
  plan-quality/05, 2026-09-08). Before fetching the token or calling Meta it reads
  `channel_entity_map` for `external_id = ANY(<ids>) AND org_id = <this org>`; only ids that
  come back are ever sent to Meta — an id nobody has bound, or bound by another organisation,
  is silently dropped, no error. Stricter than the two entries above (which only refuse a
  known conflict); reading `channel_entity_map` from here is the same precedent (ADR 0056 §4).
- **`fetch_ad_creatives` and `backfill_status` join this list** (ticket past-ads/02, 2026-09-08;
  ticket 03 will call both). `fetch_ad_creatives(token, ad_ids)` — no `org_id`, it takes ids the
  caller already resolved from its own tenant-scoped tables, same shape as `fetch_budgets`.
  `backfill_status(conn, org_id, ad_account_ids)` filters `meta_entity_spend` on `org_id` and
  `ad_account_id = ANY(ad_account_ids)` before reading, same boundary as `spend_summary`. Both
  sit in `daily_pull.py`/`graph.py`, not `repository.py`, only because `repository.py` was
  766/800 lines (96% of the cap, 2026-09-08 `wc -l`) when this ticket landed.

Tables this module owns: `meta_ad_account`, `brand_meta_ad_account`, `meta_entity_spend`.
Account tables stay one per channel — there is no generic account table, by decision
(ADR 0055 §8). `channel_credential` (T4 — this module's earlier one-row-per-org credential
table is gone) belongs to `schedule` (ADR 0050), not this module — the code that reads and
writes it stays in `app/meta/` regardless, because there is still only one channel
(ADR 0056 §4).

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

- ADR 0063 — the daily-pull worker is its own process (`python -m app.worker`) on every
  environment.
- ADR 0043 — one bucket, and the org id is the first folder (Vault/storage shape this module
  follows for its token).
- ADR 0050 — the ad-loop data model of record: this module's table changes and their tickets.
- ADR 0052 — a logged-in request runs as `authenticated` with an `app.org_id` claim.
- ADR 0055 — a node is identified by a path key and a channel; what stays Meta-specific and why.
- ADR 0056 — a channel catalogue is a file; its per-org state is a table.
- ADR 0057 — ad-level spend meets the coordinate through the depth-3 binding, which freezes the
  tree that produced it.
- ADR 0067 — an imported ad enters coordinates as a row its owner tags, never one a model
  infers; numbers come in by program (backfill, `fetch_ad_creatives`), reasons come from the
  owner (ticket 03).

## Measured (facts about the real account; re-measure before a ticket leans on one)

Moved here from `BOARD.md` on 2026-09-04 (full text: `BOARD.md` @ `6574191`).

- **`repository.py` was 766/800 lines (96% of the cap) on 2026-09-08**, `wc -l` — this is why
  ticket past-ads/02's new reads (`fetch_ad_creatives`, `backfill_status`) live in `graph.py`/
  `daily_pull.py` instead, per the ticket's own instruction not to touch `repository.py`.

- **The three levels of spend agree exactly.** `uv run python -m app.meta.daily_pull --since 2026-08-01`
  brought in 349 rows (ad 254 / 13 ads, adset 60 / 2 sets, campaign 35 / 1 campaign), each level
  summing to 63,464 TWD, day by day, impressions and clicks alike. Measured twice (2026-09-03 with
  166 rows, 2026-09-04 with 349). No tolerance needed. Rows with a `roas`: ad 93/254 (37%).
- **Exact-name binding is verified three levels deep on the real account** (2026-09-04, commit
  `5dfe8d8`): the full-width `｜` separator is fine; `PAUSED` / `IN_PROCESS` entities bind (the match
  asks whether it exists, not whether it runs — `graph.py:187-193`); a partial success stays — the
  campaign binds first, adset and ad on the next press, and the failed press does not clear bound
  rows. **Meta easily grows two identically named ad sets** (the creation flow leaves an empty one);
  that was the first real trap hit.
- `channel_entity_map`'s three rows are real name-matched bindings now; the hand-inserted row is gone.
  Never "verify" binding with a hand-inserted row again.
- `graph.fetch_page`'s `timeout=10.0` has never been measured. When it is really short, the official
  next step is a smaller date window, not a longer timeout.
- worker `concurrency` is procrastinate 3.9.0's default 1 (`app/background` sets nothing): N jobs
  still run one at a time. Running N agents at once is spending N budgets at once — measure one
  real run's duration before changing it.
- `daily_pull.py:89` pulls `[today-7, today]` (reason at `:54`); the 7d_click attribution window has
  no hole (checked 2026-09-02).
