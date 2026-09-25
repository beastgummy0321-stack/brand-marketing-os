-- F31-I09 (item 13): campaign_period_budget_version has no reader or writer in app/.
-- Checked before dropping:
--   grep -rn "REFERENCES campaign_period_budget_version" supabase/migrations/  -> only its own
--   reverted_from_id self-reference
DROP TABLE campaign_period_budget_version;
