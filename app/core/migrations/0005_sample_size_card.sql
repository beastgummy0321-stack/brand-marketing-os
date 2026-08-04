-- app/core/migrations/0005_sample_size_card.sql
-- 樣本數門檻規則卡（票 8，決策 0023 第 19、20 點）：把「統計門檻」跟毛利反推的「錢的門檻」分開。
-- 定義見 app/core/rule_cards.py CARDS["sample_size"]（單一權威）；這裡只存種子值，
-- 數值來源：docs/methodology/ab-testing.md 第 3 節「樣本數速查表」20% 提升幅度欄。

INSERT INTO rule_card_value (card_key, field_key, value, updated_at) VALUES
    ('sample_size', 'baseline_1pct',   97000.0, '2026-08-01T00:00:00+00:00'),
    ('sample_size', 'baseline_3pct',   31000.0, '2026-08-01T00:00:00+00:00'),
    ('sample_size', 'baseline_5pct',   18000.0, '2026-08-01T00:00:00+00:00'),
    ('sample_size', 'baseline_10pct',   8700.0, '2026-08-01T00:00:00+00:00'),
    ('sample_size', 'baseline_20pct',   4000.0, '2026-08-01T00:00:00+00:00');
