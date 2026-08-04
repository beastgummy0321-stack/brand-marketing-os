-- app/ads/migrations/0009_voucher_codes.sql
-- 期別配碼＋上線前校驗新表（GitHub issue #35，決策 0025 補遺第 2、7 點）：
-- 碼分身術主防線——每期發廣告碼／口播碼兩組，短效期、低使用上限、期期換碼不重用。
-- 兩張表都掛 campaign_cycle_id 真外鍵，且都是「這一期的規劃產物」（比照 publishing_package），
-- 期被刪就該一起消失，故進 app/ads/repository.py CYCLE_CASCADE_TABLES，
-- 不比照 learning_ledger 脫鉤（訂單／GA4 那種「跨期資料」才脫鉤，配碼不是）。

CREATE TABLE IF NOT EXISTS cycle_voucher_code (
    id TEXT PRIMARY KEY,                    -- vch_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    source_type TEXT NOT NULL,              -- 'ad' | 'word_of_mouth'（碼按流量來源分，非按切角分）
    code TEXT NOT NULL,
    discount_type TEXT NOT NULL,            -- 'percent' | 'fixed'
    discount_value REAL NOT NULL,
    usage_limit INTEGER NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- 一期一組廣告碼對全部切角：同一期同一來源只有一筆。
CREATE UNIQUE INDEX IF NOT EXISTS idx_voucher_code_cycle_source
    ON cycle_voucher_code(campaign_cycle_id, source_type);
-- 期期換碼不重用：同品牌全部檔期共用碼字唯一（比對訂單 voucher_code 時才不會撞期）。
CREATE UNIQUE INDEX IF NOT EXISTS idx_voucher_code_brand_code
    ON cycle_voucher_code(brand_id, code);

-- 上線前逐欄校驗紀錄：規劃碼（cycle_voucher_code）vs 後台實際設定（人工輸入，EasyStore
-- 無 API，見決策 0025 第 2 點）。passed=0 的最新一筆會鎖住該期的開跑動作
-- （app/ads/codes.py is_activation_locked），通過只留紀錄、不影響其他任何流程。
CREATE TABLE IF NOT EXISTS cycle_code_verification (
    id TEXT PRIMARY KEY,                    -- vcv_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    passed INTEGER NOT NULL,                -- 0/1
    mismatches_json TEXT,                   -- 不符欄位的人話清單，passed=1 時為 NULL
    checked_by TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_code_verification_cycle
    ON cycle_code_verification(campaign_cycle_id, checked_at DESC);
