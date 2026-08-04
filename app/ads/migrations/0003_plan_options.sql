-- app/ads/migrations/0003_plan_options.sql
-- 票 4：計畫多方案（決策 0023 第 1 點）。
--
-- 這張表是「還沒被老闆選定」的暫存方案批次，不是事實層——每次重新生成整批替換
-- （DELETE 該檔期舊列再 INSERT 新列），老闆選定後轉存進既有 campaign_plan（append-only）
-- 就會把這裡的列清掉。跟 experiment_cell 同一種「暫存工作表」精神，不是可回溯的歷史，
-- 所以不比照 campaign_plan 走 append-only、也不需要獨立的封存／刪除介面
-- （AGENTS.md 規則 7／principles「新資料實體必附封存＋刪除」指的是老闆會長期管理的資產，
-- 這張表的內容存活時間只到「選定」或「重新生成」為止）。
CREATE TABLE IF NOT EXISTS campaign_plan_option (
    id TEXT PRIMARY KEY,                    -- cpo_*
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    option_index INTEGER NOT NULL,
    is_recommended INTEGER NOT NULL DEFAULT 0,
    option_json TEXT NOT NULL,              -- summary/difference/audience/angles/hypotheses/grounding
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaign_plan_option_cycle
    ON campaign_plan_option(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_campaign_plan_option_brand
    ON campaign_plan_option(brand_id);
