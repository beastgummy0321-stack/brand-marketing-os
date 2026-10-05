-- supabase/migrations/20261005000102_core_rule_card_margin_percent.sql
-- Module: core (rule cards). F50-I04 (feature F50 Contract I, decision 9): the `gross_margin`
-- card's `gross_margin_rate` is a percent stored 0–100 (70 = 70%) like every 「%」 field
-- (`Bounds(0, 100)` in app/core/rule_cards.py). A brand override saved on the old 0–1 scale is
-- moved to the percent it meant (test data only, CLAUDE.md 資料狀態).

UPDATE rule_card_value SET value = value * 100
WHERE card_key = 'gross_margin' AND field_key = 'gross_margin_rate' AND value <= 1;
