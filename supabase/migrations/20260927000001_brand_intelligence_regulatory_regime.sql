-- supabase/migrations/20260927000001_brand_intelligence_regulatory_regime.sql
-- Module: brand_intelligence. Ticket: F34-I01 (feature F34, Contract R).
--
-- "Which advertising regime applies to this brand" is the user's own choice (ruling 1A), not
-- something inferred from an LLM-extracted `brand_fact`. First value: 'food_tw' (台灣食品:
-- 食安法 §28 wording reminders). NULL has one meaning -- 不適用／未設定 -- unlike
-- `advertising_history`, nothing needs to tell "unasked" apart from "answered none". Writer:
-- app/brand_intelligence/regulatory_regime.py; readers arrive in F34-I02／I03.
ALTER TABLE brand ADD COLUMN regulatory_regime TEXT
    CHECK (regulatory_regime IN ('food_tw'));
