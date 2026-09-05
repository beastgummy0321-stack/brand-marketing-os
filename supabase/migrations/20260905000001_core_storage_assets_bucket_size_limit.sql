-- supabase/migrations/20260905000001_core_storage_assets_bucket_size_limit.sql
-- Module: core
-- Ticket: docs/issues/deploy/05-assets-bucket-size-limit.md
-- ADR 0043: one private bucket named `assets`, org_id is the first key segment.
--
-- Filename must start with `core_` (not `storage_`) — app/tests/test_migration_ownership.py
-- MODULES has no `storage` entry; this migration creates no table of its own, it updates one
-- row in Supabase Storage's own `storage.buckets` table.
--
-- 20260830000002_core_storage_assets_bucket.sql seeded the `assets` bucket with no
-- `file_size_limit`. Locally that bucket instead comes from `[storage.buckets.assets]` in
-- supabase/config.toml (this migration's sibling change adds the limit there too), so the gap
-- only bites a hosted Supabase project, where it silently falls back to the platform-wide
-- default. 52428800 = 50 * 1024 * 1024, the same number `app/brand_web/routes_library.py`'s
-- `_MAX_ASSET_BYTES` already enforces at the app layer — this is the third line of defence,
-- not the first.
--
-- Guarded the same way as 20260830000002_*.sql, for the same two proven reasons:
--   - `supabase db reset` replays user migrations BEFORE the storage container restarts, so
--     `storage.buckets` does not exist yet on a bare install.
--   - app/tests/conftest.py replays every migration once per test module; an UPDATE is
--     naturally idempotent (unlike the original's INSERT, which needed `on conflict do nothing`),
--     so no extra guard is needed there.
do $$ begin
  if to_regclass('storage.buckets') is not null then
    update storage.buckets set file_size_limit = 52428800 where id = 'assets';
  end if;
end $$;
