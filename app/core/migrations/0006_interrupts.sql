-- app/core/migrations/0006_interrupts.sql
-- 全站打斷佇列（決策 0025／0026）：所有「需要人看」的訊息只有一個出口，各模組只能認領
-- category、不得自報 severity——嚴重度單一權威定義見 app/core/interrupts.py CATEGORIES。
-- brand_id／campaign_cycle_id 比照 audit_log／llm_task 慣例，跨模組欄位不建 DB 外鍵
-- （campaign_cycle_id 帶上是方便 app/ads/repository.py CYCLE_CASCADE_TABLES 直接用同一套
-- 「DELETE WHERE campaign_cycle_id = ?」迴圈連帶刪除，非 ads 模組來源的列這欄留 NULL）。

CREATE TABLE IF NOT EXISTS interrupt (
    id TEXT PRIMARY KEY,                    -- itr_*
    brand_id TEXT,                          -- NULL＝跨品牌系統級
    campaign_cycle_id TEXT,                 -- 選填：來源掛在某檔期時填，供連帶刪除
    dedupe_key TEXT NOT NULL,               -- 去重鍵：同鍵二次 enqueue 只留一筆（見 interrupts.enqueue）
    category TEXT NOT NULL,                 -- 模組認領的類別代碼，嚴重度由此反查
    kind TEXT,                              -- 類別內的子類型（選填，供該模組自己判讀用）
    severity TEXT NOT NULL,                 -- enqueue 當下由 category 對應寫入，事後不可改
    message TEXT NOT NULL,                  -- 一卡一句（DESIGN.md §20 規則 4：≤30 全形字）
    action_url TEXT,                        -- 「詳情」導向（§20 規則 3：全站唯一展開/導向元件）
    visible_from TEXT,                      -- 排程但先不打斷；NULL＝建立當下就可見
    status TEXT NOT NULL DEFAULT 'open',    -- open/resolved/archived（resolved=人工處理，archived=逾期自動降級封存）
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_interrupt_dedupe_key ON interrupt(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_interrupt_brand_status ON interrupt(brand_id, status);
CREATE INDEX IF NOT EXISTS idx_interrupt_cycle ON interrupt(campaign_cycle_id);
