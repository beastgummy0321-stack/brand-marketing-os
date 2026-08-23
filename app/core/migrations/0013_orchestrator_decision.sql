-- 調度台每一次決策的留痕（ADR 0024 第 3 條，含 2026-08-23 更正）。
-- 事實欄寫入後禁止 UPDATE；只有 outcome／attempt_count／error_text 可更新。
CREATE TABLE IF NOT EXISTS decision (
    id TEXT PRIMARY KEY,                    -- dcs_*
    module TEXT NOT NULL,                   -- 要哪個模組做，對應 MODULES 的 key
    brand_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,                  -- 哪條規則生出這個 Action
    action_json TEXT NOT NULL,              -- 整包 Action 原文，同意後原封不動執行
    risk_level TEXT NOT NULL,               -- save/spend/asset
    autonomy_mode REAL NOT NULL,            -- 當下的自動度（1.0 保守／2.0 放手）
    dedupe_key TEXT NOT NULL,               -- 同一件事不重複做
    outcome TEXT NOT NULL,                  -- auto_done/carded/failed
    attempt_count INTEGER NOT NULL DEFAULT 1,
    error_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_brand ON decision(brand_id);
CREATE INDEX IF NOT EXISTS idx_decision_dedupe ON decision(brand_id, dedupe_key);
