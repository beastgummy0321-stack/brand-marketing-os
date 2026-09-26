-- F31-I09 (item 13): strategy_hypothesis has had no writer since ticket 04 (its only writer
-- went with the deleted ad module) and no reader. Checked before dropping:
--   grep -rn "REFERENCES strategy_hypothesis" supabase/migrations/  -> none
DROP TABLE strategy_hypothesis;
