-- F31-I09 (item 13): drop two core tables nothing reads or writes any more.
-- decision: its only writer went with the deleted ad module; brand_dismissed_calendar_category:
-- no reader or writer since the core baseline. Checked before dropping:
--   grep -rn "REFERENCES decision" supabase/migrations/  -> only decision.revert_of (itself)
--   grep -rn "REFERENCES brand_dismissed_calendar_category" supabase/migrations/  -> none
-- and no view or function in the live schema depends on either table.
DROP TABLE decision;
DROP TABLE brand_dismissed_calendar_category;
