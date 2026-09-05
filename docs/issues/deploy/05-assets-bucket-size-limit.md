# 05 — the `assets` bucket carries its own `file_size_limit`

Route C (schema/migration). Graduated from `issue-assets-bucket-size-limit.md` (2026-09-05).
**Needs the user's approval before dispatch** (constitution: migrations).

## What

`supabase/migrations/20260830000002_core_storage_assets_bucket.sql:25` seeds the bucket with
`insert into storage.buckets (id, name, public) values ('assets', 'assets', false)` — no
`file_size_limit`. On a hosted Supabase project that leaves the bucket falling back to the
project-wide limit, whatever the platform's default happens to be that month. Locally there is a
limit, but it comes from a different place: `supabase/config.toml:118`
`[storage] file_size_limit = "50MiB"`, which is global to the local stack and is not replayed on
the cloud project.

This is the third line of defence, not the first. The first two are in the app and already work:
`app/brand_web/routes_library.py:57` `_MAX_ASSET_BYTES = 50 * 1024 * 1024`, checked at `:273`
(HTTP route, before `await file.read()`) and `:79` (non-HTTP callers).

**The number is not chosen by this ticket.** 50 MiB = `52428800` bytes, sourced from
`supabase/config.toml:118`, which is also where `routes_library.py:52-57`'s comment says its own
constant came from. Do not round it to 50 000 000; the app constant is `50 * 1024 * 1024` and a
bucket limit one byte under it would reject a file the app just accepted.

Two files change, and both are load-bearing for a different environment (ADR 0043 and the
migration's own header say so):

1. **New migration file**, `supabase/migrations/<timestamp>_core_storage_assets_bucket_size_limit.sql`
   — the cloud path. Prefix must be `core_`, not `storage_`: `MODULES` in
   `app/tests/test_migration_ownership.py` has no `storage` entry. The applied file
   `20260830000002_*.sql` is **not** edited (constitution: applied migrations are never edited;
   corrections open a new file).
   It must survive the same two realities the original guards against, quoted from its header:
   `storage.buckets` may not exist yet on a bare install (`supabase db reset` replays user
   migrations before the storage container starts), and `app/tests/conftest.py` replays every
   migration once per test module against a global table. So: wrap in the same
   `if to_regclass('storage.buckets') is not null then` guard, and write it as an idempotent
   `update storage.buckets set file_size_limit = 52428800 where id = 'assets'` — an UPDATE is
   naturally re-runnable, which an INSERT was not.
2. **`supabase/config.toml`** — add `file_size_limit = "50MiB"` under `[storage.buckets.assets]`
   (line 129) so local matches cloud, and fix the now-false comment at line 128
   (`# No file_size_limit / allowed_mime_types here — callers already validate in Chinese`).
   Leave `allowed_mime_types` alone: the app validates extensions
   (`routes_library.py:_ASSET_CONTENT_TYPES`) and this ticket does not touch that.

Out of scope, deliberately: `allowed_mime_types`, any change to `_MAX_ASSET_BYTES`, any change to
the two app-layer checks, any other bucket.

## How we know it's done

1. `uv run ruff check app` — clean. `uv run pyright` — 0 errors.
2. `supabase db reset` completes with no error on a stack that was already running **and** the
   new migration is listed as applied. (This is the reality the original file's header says broke
   twice; a migration that only works on one of the two orders is not done.)
3. `psql "$DATABASE_URL" -c "select id, file_size_limit from storage.buckets where id = 'assets'"`
   returns `52428800`. Paste the output into the completion report.
4. Proven red once: change the literal to `1` , re-run reset, see check 3 return `1`; restore.
5. `uv run pytest app/tests/test_migration_ownership.py app/tests/test_official_assets.py app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q`
   — green. (The first proves the `core_` prefix; the last three are the schema-ticket set the
   project's rules require.)
6. `cd frontend && npm run e2e` — green.

No new test file. Check 3 is a command, not a test; `test_official_assets.py` already covers the
app-layer refusal message and this ticket does not change it.

## Shared files touched

Unscoped repo-wide search for `storage.buckets`, `file_size_limit`, `_MAX_ASSET_BYTES`
(excluding `.git/node_modules/dist/.scratch/backups/__pycache__`):

```
./app/brand_web/routes_library.py:53,57,79,273
./app/tests/test_official_assets.py:102
./docs/adr/0043-one-bucket-and-the-org-id-is-the-first-folder.md:72,75
./docs/adr/0050-the-ad-loop-data-model-is-one-table-list.md:46
./docs/issues/deploy/issue-assets-bucket-size-limit.md:1,6
./supabase/config.toml:118,121,123,128,129
./supabase/migrations/20260830000002_core_storage_assets_bucket.sql:8,12,13,15,20,24,25
```

Expected diff: `supabase/config.toml` plus the one new migration file, and nothing else.
`docs/adr/0050:46` states this gap in prose ("What is missing is only the bucket-side
`file_size_limit`") — it is a record of a measurement, not a rule, and is not edited by the
implementer; main chat handles the doc at close.

## Contradiction check

Done-check 3 (the bucket says 52428800) and done-check 2 (`supabase db reset` is clean) can
contradict each other: a migration that hard-fails when `storage.buckets` is absent satisfies
3 on a warm stack and breaks 2 on a cold one, and a migration that silently no-ops satisfies 2
and quietly fails 3. The input that shows it: run reset twice — once against a stack that has
never started storage, once against a warm stack — and require check 3 to pass after **both**.
