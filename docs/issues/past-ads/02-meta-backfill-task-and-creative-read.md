# 02 — meta: the 37-month backfill as a queue task, and reading a few ads' creative

Route C (module `meta`, external API, a new background task). Rulings: ADR 0067 §1.8 and §1.9.
Goal picture: `spec.md`. Reads nothing from and writes nothing to `imported_ad` (ticket 03 does).
**No LLM call anywhere in this ticket.**

`app/meta/repository.py` is at 766 lines, 96% of the 800 cap (`wc -l`, 2026-09-08). **This ticket does
not edit it.** New reads live in `daily_pull.py` and `graph.py`. If something can only be done in
`repository.py`, stop and report `blocked-upstream` (workflow.md, "A boundary escalation is not a menu").

## What

### 1. `app/meta/daily_pull.py` — the backfill becomes a task

- `_BACKFILL_TASK_NAME = "background.meta_backfill"`; `run_backfill(org_id: str) -> None` is the task body
  (`org_id` first — `TaskSignatureOrgIdGateTest` scans `background.`-prefixed tasks). It computes
  `today = coresettings.today_for_org(conn, org_id=org_id)`, `since = _earliest_pullable(today)`, and calls the
  **existing** `backfill(org_id, since, today)` unchanged. Nothing else: no new pull loop, no second upsert path.
- `register_task()` also registers this task, idempotently, in the same `if name not in a.tasks` shape as the
  two it already registers.
- `backfill_lock(org_id) -> str` returns `f"meta_backfill:{org_id}"` — one string, defined once, used by the
  route (enqueue and `is_active`) and by nothing else. The lock is per organisation because `backfill()` is
  per organisation (its own docstring: 組織＋廣告帳戶層).
- `backfill_status(conn, org_id, ad_account_ids) -> dict` — one SQL read
  `SELECT MIN(spend_date), MAX(spend_date), COUNT(*) FROM meta_entity_spend WHERE org_id = %s AND ad_account_id = ANY(%s) AND level = 'ad'`,
  returning `{"earliest_spend_date": date | None, "latest_spend_date": date | None, "ad_rows": int}`. It sits
  here and not in `repository.py` only because of the cap paragraph above; say so in its docstring.

### 2. `app/meta/graph.py` — `fetch_ad_creatives(token, ad_ids) -> dict[str, dict | None]`

Shaped after `fetch_budgets` (one `GET {GRAPH_BASE_URL}/{ad_id}` per id, no paging), with
`fields=name,created_time,effective_status,creative{body,title,image_url,thumbnail_url,object_story_spec}`.
Sources, verified 2026-09-08: Ad node `creative` field —
developers.facebook.com/docs/marketing-api/reference/adgroup/; AdCreative `body` ("The body of the ad. Not
supported for video post creatives"), `title`, `image_url`, `thumbnail_url`, `object_story_spec` —
developers.facebook.com/docs/marketing-api/reference/ad-creative/; `object_story_spec.link_data` ("The spec
for a link page post or carousel ad") — developers.facebook.com/docs/marketing-api/reference/ad-creative-object-story-spec/;
`link_data.message` ("The main body of the post."), `name` ("Name of the link."), `picture` ("URL of a
picture to use in the post.") — developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data/.
Nested field expansion is Graph API field expansion (developers.facebook.com/docs/graph-api/using-graph-api).
Put the URLs in the function's comment, as `fetch_budgets` and `list_entity_insights` do.

Per id, the value is either `None` — Meta answered that id with an `{"error": …}` body (a deleted or
unreadable ad; ADR 0067 §1.9: "Meta 現在回不出這則的素材" is a state, so the id stays in the dict with
`None`, it is never dropped) — or:

```json
{
  "name": "BP｜夏季｜輪播A",
  "created_time": "2026-05-03T08:12:00+0000",
  "effective_status": "PAUSED",
  "body": "…first non-empty of creative.body, creative.object_story_spec.link_data.message, else null…",
  "title": "…first non-empty of creative.title, creative.object_story_spec.link_data.name, else null…",
  "image_url": "…first non-empty of creative.image_url, creative.object_story_spec.link_data.picture, creative.thumbnail_url, else null…"
}
```

The fallback order is the ticket's ruling (a page-post ad carries its text in `link_data`, not in `body`,
per the `body` description above); every value is taken verbatim, never trimmed, never translated.
Transport failure (`httpx.HTTPError`, unparsable JSON) raises `GraphError` for the whole call, exactly as
`fetch_budgets`. A `video_data`-only creative yields `body`/`title` `None` and whatever `thumbnail_url` gave.

### 3. `app/meta/routes.py` — two routes, both under the existing router

- `POST /api/meta/brands/{brand_id}/backfill` → `web.require_actor`, `web.require_brand(brand_id, actor)`
  (another organisation's brand → 404, same as `brand_spend`). No bound account for this brand →
  `web.ApiError(409, "no_bound_account", "這個品牌還沒綁定 Meta 廣告帳戶。")`. Otherwise
  `background.enqueue(_BACKFILL_TASK_NAME, org_id=actor.org_id, lock=backfill_lock(actor.org_id))` and reply
  `{"started": <enqueue's bool>, "running": true}`. Writes one `audit_log` row (`entity_type="meta_backfill"`,
  `action="start"`) through `write_audit`, as `connect_token` does for its own action.
- `GET /api/meta/brands/{brand_id}/backfill` → same auth; reply
  `{"running": background.is_active(lock), "earliest_spend_date": …, "latest_spend_date": …, "ad_rows": …}`
  from `backfill_status()` over `repo.bound_account_ids_for_brand(...)`. No bound account → the same 409.

Pydantic response models for both, next to the existing ones. The handler parses, calls, wraps — no branch
beyond the 409 (container contract §7).

### 4. `docs/contracts/meta.md`

Exported shapes: the two routes; `fetch_ad_creatives` and `backfill_status` join the "read functions
`app.schedule` is allowed to call" list (ticket 03 will call both). Decisions in force: ADR 0067. Measured:
`repository.py` 766/800 and the reason the new reads live elsewhere.

### 5. `frontend/src/lib/metaApi.ts`

`startMetaBackfill(brandId)` and `fetchMetaBackfillStatus(brandId)` with the two response types above —
the client for ticket 04, exported here so ticket 04's diff stays inside `frontend/src/components/`. No
component uses them yet.

## How we know it's done

Tests go in `app/tests/test_meta_daily_spend.py` (its `_MetaDailySpendTestBase` swaps `graph.fetch_page`,
builds this module's own `background.app()` and re-registers the tasks — reuse it, do not build a second base).

1. **The task is registered and runs through the real queue.** After `register_task()`,
   `"background.meta_backfill" in background.app().tasks`; deferring it for an org with one bound account and
   a fake `fetch_page` that records every request → the job's status is `succeeded`, and the **first**
   insights request's `time_range.since` equals `daily_pull._earliest_pullable(today)` and the last one's
   `until` equals today (org timezone). Shape: `QueueWiringTest`.
2. **One organisation, one running backfill.** With a job in `todo`, a second `POST …/backfill` replies
   `{"started": false, "running": true}` and the queue holds exactly one job with that lock
   (`is_active(backfill_lock(org))` is true; count rows in `procrastinate_jobs` by `queueing_lock` as
   `QueueWiringTest` does by id).
3. **Tenant boundary.** `POST` and `GET` on another organisation's `brand_id` → 404; a brand with no bound
   account → 409 `no_bound_account`; org A's backfill writes no row for org B (extend `OrgIsolationTest`
   with the backfill task, same assertion).
4. **`backfill_status` reads only the given accounts.** Two accounts in one org, rows on both; status over
   one account id returns that account's min/max/count only.
5. **`fetch_ad_creatives` keeps unreadable ids.** Fake `fetch_page`: id A → a body with
   `creative.body`/`creative.image_url`; id B → a page-post creative with only `object_story_spec.link_data`
   (`message`, `name`, `picture`); id C → `{"error": {"message": "Unsupported get request", "code": 100}}`.
   Result: A carries `body`/`image_url` from the top level, B carries them from `link_data`, C is `None`,
   and all three keys are present. A transport error on any id raises `GraphError`.
6. **`repository.py` untouched**: `git diff --stat -- app/meta/repository.py` prints nothing.
7. **Machine gate**: `unset BRAND_OS_LLM_PROVIDER`; `uv run ruff check app` · `uv run pyright` ·
   `uv run pytest app/tests/test_meta_daily_spend.py app/tests/test_background.py app/tests/test_architecture_boundaries.py -q` ·
   `cd frontend && npm run build` (there is no `typecheck` script; `build` is `tsc -b && vite build`) · `cd frontend && npm run e2e` (own 8720 backend,
   `supabase start` first, shut it down after).
8. **Ratchets**: `KNOWN_MODULE_SIZES["app/meta"]` (1701) and `TEST_LINES_CEILING` rise by measured
   amounts with a reason in the file's chronological style.

## Shared files touched

Searched 2026-09-08 across the whole repo, unscoped by directory and file type (excluding
`node_modules`/`.git`/`.venv`/`.scratch`/`.worktrees`/`dist`/`graphify-out`/`__pycache__`/`.pytest_cache`;
hits in ADR 0067 and this folder excluded):

```
grep -rn run_backfill .                    → (no hits)
grep -rn backfill_status .                 → (no hits)
grep -rn fetch_ad_creatives .              → (no hits)
grep -rn "brands/{brand_id}/backfill" .    → (no hits)
grep -rn no_bound_account .                → app/tests/test_meta_daily_spend.py:688 (a test name, not the code string)
grep -rn meta_backfill .                   → (no live hits; .pytest_cache holds two ids of a deleted test file)
```

Files this ticket edits:

```
app/meta/daily_pull.py          (task body, lock, backfill_status, register_task)
app/meta/graph.py               (fetch_ad_creatives)
app/meta/routes.py              (two routes + response models)
frontend/src/lib/metaApi.ts     (two client functions)
docs/contracts/meta.md
app/tests/test_meta_daily_spend.py
app/tests/test_architecture_boundaries.py:1316,1668   (TEST_LINES_CEILING, KNOWN_MODULE_SIZES["app/meta"])
```

## Contradiction check

- **Done-check 1 (the task pulls 37 months) vs done-check 2 (one running backfill per org).** A brand-level
  button starts an org-level job: two brands of one org bound to two different accounts both press → the
  second press is refused with `running: true` although *its* account has not started. That is the ruling
  (`backfill()` pulls every bound account of the org in one job, so the second brand's account is inside
  the first job), and check 4 lets each brand's status read only its own accounts. Input that shows it: two
  brands, two accounts, press twice.
- **Done-check 5 (`None` for an errored id) vs "transport error raises for the whole call".** Meta's
  `{"error": …}` body on a 400 and an `httpx.HTTPError` are different events in `fetch_page`
  (`_raise_if_error` vs the `except httpx.HTTPError`); the implementer must confirm which exception a 400
  with a JSON error body actually raises in `fetch_page` before choosing where to catch — and name the
  reading in the report.
- **Cheapest wrong implementation that leaves every check green:** the route calls `backfill()` inline
  instead of enqueuing — checks 1–5 pass if the test counts rows. Check 2's "exactly one job with that lock
  in `procrastinate_jobs`" is what fails it; keep that assertion literal.
