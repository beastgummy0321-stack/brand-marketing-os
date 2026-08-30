-- supabase/migrations/20260830000002_core_storage_assets_bucket.sql
-- Module: core
-- Ticket: .scratch/storage-slice/issues/01-storage-module-and-bucket.md
-- ADR 0043: one private bucket named `assets`, org_id is the first key segment.
--
-- Filename must start with `core_` (not `storage_`) — app/tests/test_migration_ownership.py
-- MODULES has no `storage` entry; this migration creates no table of its own, it seeds one
-- row into Supabase Storage's own `storage.buckets` table.
--
-- Guarded, not a bare INSERT, because of two things proved against the live stack (SPEC D1):
--   - `supabase db reset` replays user migrations BEFORE the storage container restarts, so
--     `storage.buckets` does not exist yet on a bare install and reset aborts with
--     `relation "storage.buckets" does not exist`.
--   - app/tests/conftest.py replays every migration once per test module (75+ modules);
--     `storage.buckets` is global, not per-schema, so an unguarded insert dies on
--     `duplicate key value violates unique constraint "buckets_pkey"` on module #2.
-- `on conflict (id) do nothing` handles the second; `to_regclass(...) is not null` handles
-- the first (also true on any environment where the storage extension isn't installed at all).
--
-- Local dev/CI create the same bucket a second way: [storage.buckets.assets] in
-- supabase/config.toml, which is what actually seeds it for `supabase start`. This migration
-- is the cloud-project path. Both are load-bearing; neither is defensive padding.
do $$ begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public) values ('assets', 'assets', false)
    on conflict (id) do nothing;
  end if;
end $$;
