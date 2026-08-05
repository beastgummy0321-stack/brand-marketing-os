-- app/core/migrations/0009_pacing_card.sql
-- 檔期預算步調門檻規則卡（票 08-pacing-alert）：預算消耗進度 vs 檔期時間進度的偏差門檻。
-- 定義見 app/core/rule_cards.py CARDS["pacing"]（單一權威）；這裡只存種子值。

INSERT INTO rule_card_value (card_key, field_key, value, updated_at) VALUES
    ('pacing', 'deviation_threshold_ratio', 0.15, '2026-08-06T00:00:00+00:00');
