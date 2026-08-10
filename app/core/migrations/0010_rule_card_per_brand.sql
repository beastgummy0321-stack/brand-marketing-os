-- app/core/migrations/0010_rule_card_per_brand.sql
-- 規則卡改分品牌（設定中心票 01，.scratch/settings-hub/issues/01-per-brand-rule-cards-core.md）：
-- rule_card_value 從「整台系統一份」改成「每個品牌各自一份，未覆寫時繼承 app/core/rule_cards.py
-- CARDS 常數的預設值」。舊表的 17 筆種子列逐筆比對後跟 CARDS 的 default 完全一致（不是使用者
-- 真的調過的自訂值），直接捨棄重建，沒有真實使用者資料遺失。

DROP TABLE IF EXISTS rule_card_value;

CREATE TABLE rule_card_value (
    brand_id TEXT NOT NULL,
    card_key TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (brand_id, card_key, field_key)
);
CREATE INDEX IF NOT EXISTS idx_rule_card_value_brand ON rule_card_value(brand_id);
