-- supabase/migrations/20260913000002_ads_success_target_nullable.sql
-- Module: ads (F03-I18). 目標值可以是 null＝模型說不出有根據的數字；結案判 看不出。
-- No CHECK constraint: a target may be missing at any status, including a campaign that runs to
-- the end and closes with 看不出 — tying null to status='draft' would force the code to invent a
-- number at publish time, which is the thing this feature forbids.

ALTER TABLE ads_campaign ALTER COLUMN success_target DROP NOT NULL;
