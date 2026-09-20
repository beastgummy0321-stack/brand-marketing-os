-- supabase/migrations/20260920000004_ads_result_definition.sql
-- Module: ads (F16-I03 repair round). The previous migration
-- (20260920000003_ads_result_metric.sql, already applied — never edited in place) added a
-- coarse `result_kind` label and `result_count` number. That is not enough: two different Meta
-- action types (e.g. `post_engagement` and `page_engagement`, where the latter already contains
-- the former on Meta) can both carry the same `result_kind` label, and summing across them
-- produces a number that never existed on the platform. Nothing recorded which specific action
-- type, nor under which attribution setting, a day's `result_count` was actually read.
--
-- `result_action` (text, nullable): the specific platform action type that was counted for this
-- row's `result_count`, e.g. "post_engagement". Platform-neutral in name only — the value itself
-- is whatever the adapter's own action-type vocabulary is; shared code treats it as an opaque
-- string to compare for equality, never to interpret.
-- `result_attribution` (text, nullable): the attribution setting the count was read under. This
-- is supplied by the adapter directly as an opaque string; shared code must never derive it by
-- parsing the Meta-formatted `attribution_key` column.
--
-- Existing columns and the table's uniqueness key are unchanged; this migration adds two
-- nullable columns only. It does NOT back-fill any existing row — every row written before this
-- migration keeps `result_action`/`result_attribution` as NULL until its campaign is re-synced.

ALTER TABLE ads_external_daily
    ADD COLUMN result_action text,
    ADD COLUMN result_attribution text;
