-- app/brand_intelligence/migrations/0003_customer_voice.sql（GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）
-- 顧客原話語料庫：獨立資料表，不塞進既有 brand_fact／product_fact 兩欄位——
-- 原文全文、AI 抽取結果、出處、來源型別是四種不同性質的資料，硬塞同一組欄位會互相擠壞。
--
-- 設計取捨：
-- 1. extraction_json 存 AI 抽取出的痛點／用語清單（JTBD 三層分類，見 customer_voice.py），
--    沿用本專案 *_json 欄位慣例（比照 brand_report.sections_json）；抽取結果可以是空陣列
--    （AI 判斷這段原話沒有值得引用的重點也是誠實結果，principles 第 16 條）。
-- 2. source_channel／source_detail 分兩欄：channel 是選單（蝦皮、Dcard...），detail 是
--    使用者填的細節（哪一則留言、連結），列表頁與抽取 prompt 都需要「出處」，拆開才好分別顯示。
-- 3. source_type 只收 manual／crawler：本批只做人工貼入，crawler 為決策 0024 第 2 條
--    預留的自動化接口欄位，程式與 UI 目前只會寫入 manual。
-- 4. status 只有 active／archived（比照 brand／product 的封存欄位），封存與刪除是兩件
--    獨立的事：封存＝改這個欄位，刪除＝直接硬刪（沿用 repository._delete_entity 模式，
--    決策 0023 第 8 條「新資料實體必附封存＋刪除」，delete 不要求先封存）。
-- 5. llm_task_id 刻意不加真外鍵：llm_task 屬於別的模組，跨模組不設真 FK（03 §1）。

CREATE TABLE IF NOT EXISTS customer_voice (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    raw_text TEXT NOT NULL,
    source_channel TEXT NOT NULL,
    source_detail TEXT,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL,
    extraction_json TEXT NOT NULL,
    llm_task_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_voice_brand_id ON customer_voice(brand_id);

-- 說明：id 前綴用 "cvc"（db.new_id("cvc")，customer voice corpus）。
