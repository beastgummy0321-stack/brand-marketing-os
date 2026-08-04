-- app/core/migrations/0004_budget_structure_card.sql
-- 帳戶結構與預算配置門檻規則卡（票 5，決策 0023 第 14、15 點）。
-- 定義見 app/core/rule_cards.py CARDS["budget_structure"]（單一權威）；這裡只存種子值，
-- 數值來源：docs/methodology/ads.md 第 3 節。

INSERT INTO rule_card_value (card_key, field_key, value, updated_at) VALUES
    ('budget_structure', 'min_daily_per_group',      300.0, '2026-08-01T00:00:00+00:00'),
    ('budget_structure', 'medium_tier_floor',         600.0, '2026-08-01T00:00:00+00:00'),
    ('budget_structure', 'large_tier_floor',         1200.0, '2026-08-01T00:00:00+00:00'),
    ('budget_structure', 'medium_validation_ratio',     0.7, '2026-08-01T00:00:00+00:00'),
    ('budget_structure', 'large_scaling_ratio',         0.8, '2026-08-01T00:00:00+00:00');
