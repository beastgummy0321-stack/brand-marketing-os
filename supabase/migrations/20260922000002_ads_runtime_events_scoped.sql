-- supabase/migrations/20260922000002_ads_runtime_events_scoped.sql
-- Module: ads (F27-I24, correcting F27-I00's `20260922000001_ads_runtime_events.sql`, applied --
-- never edited in place). Pre-dispatch correction 3 (nullable org_id/brand_id for a global
-- `beat`) turned out wrong once measured against the real gates: `test_org_isolation_all_tables
-- .py` requires NOT NULL org_id + FK on every table with no allow-list beyond `organisation` /
-- `app_user`, and `test_brand_isolation_all_tables.py` requires NOT NULL brand_id on every table
-- not explicitly listed in `BRAND_AGNOSTIC_EXCEPTIONS` (with a written reason per entry) --
-- `ads_runtime_event` was in neither list, so both gates went red the moment the first migration
-- landed. Correction 12 supersedes correction 3: `ads_runtime_event` becomes fully tenant-scoped.
-- A `beat` is now written once per (org_id, brand_id) that has at least one non-closed
-- `ads_campaign`, not once globally -- `app/ads/jobs.py::_dispatch_runtime_beat` and
-- `app/ads/runtime_events.py::record()`/`list_since()` are updated in the same issue to match.
--
-- Any row already carrying a NULL org_id/brand_id is a global-shaped beat from the superseded
-- design (this table was only ever written by the still-unmerged F27-I00 code path, never by
-- anything a real tenant depends on) -- deleted here rather than back-filled, since there is no
-- single tenant a global beat could correctly belong to.
DELETE FROM ads_runtime_event WHERE org_id IS NULL OR brand_id IS NULL;

ALTER TABLE ads_runtime_event ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE ads_runtime_event ALTER COLUMN brand_id SET NOT NULL;

DROP POLICY IF EXISTS ads_runtime_event_org_isolation ON ads_runtime_event;
CREATE POLICY ads_runtime_event_org_isolation ON ads_runtime_event FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
