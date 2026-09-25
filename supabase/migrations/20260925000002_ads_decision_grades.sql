-- supabase/migrations/20260925000002_ads_decision_grades.sql
-- Module: ads (F29-I01). Rejected-cleanup memory (docs/architecture/ads.md §6.33, F29 Contract B).
--
-- `decision_grades` = {"<entity_id>": {"grade", "cost_per_result", "cap", "at"}}: the cap grade
-- of each ad at the moment the user said no -- written by `change_control.decide(rejected)` for
-- every pause item of a `source: "cleanup"` set, and by `change_control.approve` for the set's
-- `plan_json.declined_ids` (the proposed ads the user unticked). NULL = no memory (every set
-- created before this column, and every set that never declined an ad).

ALTER TABLE ads_change_set ADD COLUMN decision_grades jsonb;
