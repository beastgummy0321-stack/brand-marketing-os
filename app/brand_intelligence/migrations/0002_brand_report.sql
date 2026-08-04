-- app/brand_intelligence/migrations/0002_brand_report.sql（決策 0017：顧問分析報告）
-- 同一份品牌資料的第二種出口——逐條事實給機器引用，這張表存「給人讀」的整份報告。
-- 時效內容（市況、競爭觀察）只住這裡，不回寫事實表。
--
-- 設計取捨（最小複雜度，逐項理由）：
-- 1. 只有一張表、不拆 report_section 子表：五章是固定結構，一起生成、一起顯示、
--    一起作廢，沒有單章查詢或單章重生成的需求，拆表只多一次 JOIN。
-- 2. 五章存成單一 sections_json（沿用本專案 *_json 欄位慣例，例如 llm_task.structured_output_json）：
--    章節文字結構日後微調不必再開 migration 改欄位。
-- 3. 一品牌多份留歷史＝只 INSERT、永不 UPDATE；「最新一份」用
--    ORDER BY generated_at DESC, id DESC LIMIT 1 取，不設 is_latest 旗標
--    （旗標要同時維護兩處狀態，遲早寫壞）。
-- 4. 不設 status／expired 欄位：是否過期＝「今天減 generated_at 是否超過 90 天」，
--    那是顯示邏輯不是資料狀態，存進來只會過時。
-- 5. source_fact_count 記生成當下引用的已確認知識條數：報告開頭的「資料尚少」提示
--    必須是生成當下的快照，之後資料變多不該回頭改寫舊報告的說法。
-- 6. llm_task_id 刻意不加真外鍵：llm_task 屬於別的模組，跨模組不設真 FK（03 §1，
--    比照 strategy_hypothesis.source_cycle_id 的做法）。
-- 7. 不另設 created_at：這張表的列只會被建立一次，generated_at 就是建立時間。

CREATE TABLE IF NOT EXISTS brand_report (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    generated_at TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    model TEXT NOT NULL,
    llm_task_id TEXT,
    brand_version INTEGER NOT NULL,
    source_fact_count INTEGER NOT NULL DEFAULT 0,
    sections_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brand_report_brand_id ON brand_report(brand_id);

-- 說明：id 前綴用 "rpt"（db.new_id("rpt")）。generated_by＝操作人（稽核 actor 同一人）。
-- brand_version＝生成當下 brand.knowledge_version，日後要判斷「報告是不是比資料舊」時直接比對。
