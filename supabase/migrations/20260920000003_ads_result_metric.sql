-- supabase/migrations/20260920000003_ads_result_metric.sql
-- Module: ads (F16-I03). Meta Insights `actions` carries every action type the platform
-- tracked that day, but until now `ads_external_daily` only ever kept the purchase synonym
-- (`purchases`/`revenue`) — a campaign whose own objective is engagement, traffic, leads, etc.
-- had no column to hold its own "result" count, so it could not be judged at all, and an
-- incidental purchase on it had no separate slot from the campaign's actual result.
--
-- `result_kind` (text, nullable): a platform-neutral label for what this campaign's own
-- objective counts as a result — "purchase", "engagement", "link_click", "lead", etc. The
-- objective -> label mapping is Meta-specific and lives in `app/ads/adapters/meta_read.py`,
-- not here and not in shared core.
-- `result_count` (numeric, nullable): how many of that result happened that day. NULL means
-- unknown/untracked — never a guessed zero, same rule as the existing `purchases`/`revenue`
-- columns on this table.
--
-- Existing `purchases`/`revenue` columns and the table's uniqueness key are unchanged; this
-- migration adds two nullable columns only. It does NOT back-fill any existing row — every
-- row written before this migration keeps `result_kind`/`result_count` as NULL until its
-- campaign is re-synced under the new adapter mapping. That is honest: this migration has no
-- way to know what a pre-existing row's campaign's own objective was already resolved into.

ALTER TABLE ads_external_daily
    ADD COLUMN result_kind text,
    ADD COLUMN result_count numeric;
