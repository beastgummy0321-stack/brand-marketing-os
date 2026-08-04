-- app/core/migrations/0003_rule_card.sql
-- 規則卡通用機制（issue #12）：門檻數值存這裡，附預設值種子。
-- 一張卡（card_key）由多個門檻欄位（field_key）組成；卡的標題／說明／預設值定義在
-- app/core/rule_cards.py 的 CARDS 常數（單一權威），這裡只存「目前值」的種子列。
-- 不分品牌：這些是平台層級的判定門檻（例如 Meta 素材疲勞頻率的通例），不是品牌資料。

CREATE TABLE IF NOT EXISTS rule_card_value (
    card_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (card_key, field_key)
);

-- 示範卡：素材疲勞頻率門檻。數值取自 docs/methodology/ads.md 第 5 節「疲勞頻率門檻」表。
INSERT INTO rule_card_value (card_key, field_key, value, updated_at) VALUES
    ('ad_creative_fatigue', 'cold_warning',        2.5, '2026-08-01T00:00:00+00:00'),
    ('ad_creative_fatigue', 'cold_danger',          4.0, '2026-08-01T00:00:00+00:00'),
    ('ad_creative_fatigue', 'retargeting_warning',  4.0, '2026-08-01T00:00:00+00:00'),
    ('ad_creative_fatigue', 'retargeting_danger',   6.0, '2026-08-01T00:00:00+00:00'),
    ('ad_creative_fatigue', 'niche_warning',        5.0, '2026-08-01T00:00:00+00:00'),
    ('ad_creative_fatigue', 'niche_danger',         8.0, '2026-08-01T00:00:00+00:00');
