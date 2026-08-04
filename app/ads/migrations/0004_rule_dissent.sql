-- app/ads/migrations/0004_rule_dissent.sql
-- 具名異議（票 5，決策 0023 第 14、15、18(b) 點；決策 0024 第 5 點）。
--
-- AI 讀完這期背景後，對「帳戶結構／預算配置」規則卡底案，或明顯薄弱的 Offer，提出具名異議：
-- 只能建議方向、必附理由，不能直接改動規則卡數字（決策 0016 硬性原則 4）。老闆的採納結果
-- （adopted/rejected）記在這裡，供之後驗證 AI 異議的準確度（決策 0023 第 25 點）——所以
-- 已經被老闆決定過的列要永久保留，不像 campaign_plan_option 那樣整批清空重來；只有還沒被
-- 決定過（pending）的舊列，才在重新生成方案時被換掉（見 app/ads/repository.py replace_pending_dissents）。
CREATE TABLE IF NOT EXISTS rule_dissent (
    id TEXT PRIMARY KEY,                    -- dsn_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    target_type TEXT NOT NULL,              -- account_structure/budget_allocation/offer
    suggestion TEXT NOT NULL,               -- 人話建議，只能講方向，不含數字
    reason TEXT NOT NULL,
    llm_task_id TEXT,                       -- 產生這筆異議的 LLM 任務，供追溯
    status TEXT NOT NULL DEFAULT 'pending', -- pending/adopted/rejected
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_dissent_cycle ON rule_dissent(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_rule_dissent_brand ON rule_dissent(brand_id);
