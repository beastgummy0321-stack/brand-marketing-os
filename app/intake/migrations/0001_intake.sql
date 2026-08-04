-- app/intake/migrations/0001_intake.sql
-- Brand Intake（建檔精靈）自有的兩張表，逐欄照 docs/design/03-data-model.md §3A.2–§3A.4 建立，
-- 未自行增減任何欄位（§3A.6 第 3 點：要加欄位先改 03 §3A）。
-- 跨模組引用（brand_id / target_id / scope_product_id / *_llm_task_id）一律不建 DB 外鍵（03 §1、§8.4）。

CREATE TABLE IF NOT EXISTS intake_draft (
    id TEXT PRIMARY KEY,                    -- idr_*
    brand_id TEXT NOT NULL,                 -- 隔離鍵，跨模組引用 brand，不建外鍵
    status TEXT NOT NULL,                   -- draft / completed / abandoned
    current_step INTEGER NOT NULL,          -- 1–5
    current_question_no INTEGER NOT NULL,   -- 0–8（0＝尚未進入問答）
    description TEXT NOT NULL,              -- W1 品牌描述原文
    photos_json TEXT NOT NULL,              -- [{file_path, display_name, size_bytes}]
    research_urls_json TEXT NOT NULL,       -- W1 研究網址原文清單（最多 5 筆）
    scan_sources_json TEXT,                 -- [{url, ok, note}]
    scan_impressions_json TEXT,             -- [{aspect, title, body, basis}]
    scan_llm_task_id TEXT,                  -- REF→llm_task
    qa_json TEXT,                           -- W4 問答全紀錄
    handoff_depth TEXT,                     -- standard / deep（只有兩檔，R4）
    handoff_prompt TEXT,                    -- W5 交接包全文（存下來才追溯得到）
    handoff_generated_at TEXT,
    paste_raw TEXT,                         -- W8 貼回原文，一字不動
    paste_validation_json TEXT,             -- {ok, total_rows, errors:[{row_no, message}]}
    repair_llm_task_id TEXT,                -- REF→llm_task；非空＝格式修復額度已用掉（只允許一次）
    cost_limit REAL NOT NULL,               -- 本次建檔花費上限，預設 30.00
    llm_task_refs_json TEXT NOT NULL,       -- [{llm_task_id, purpose}]；不存金額副本
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 一個品牌同時只有一份進行中草稿（§3A.4 第 1 點）：在 DB 層擋，不靠 app 層自律。
CREATE UNIQUE INDEX IF NOT EXISTS idx_intake_draft_one_active
    ON intake_draft(brand_id) WHERE status = 'draft';

CREATE TABLE IF NOT EXISTS intake_item (
    id TEXT PRIMARY KEY,                    -- iit_*
    intake_draft_id TEXT NOT NULL REFERENCES intake_draft(id),  -- 同模組關聯，用 DB 外鍵
    brand_id TEXT NOT NULL,                 -- 隔離鍵（去正規化亦帶）
    row_no INTEGER NOT NULL,                -- 原表第幾列（1 起算）
    raw_row TEXT NOT NULL,                  -- 這一列的原文，一字不動
    kind TEXT NOT NULL,                     -- brand_fact / product_fact / rule / claim
    category TEXT NOT NULL,                 -- 值域依 kind 而定，見 03 §3A.3 對照表
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    scope_raw TEXT NOT NULL,                -- 「整個品牌」或產品名稱
    scope_product_id TEXT,                  -- REF→product
    evidence_source TEXT,                   -- AI 說的佐證來源（線索，非依據）
    client_evidence TEXT,                   -- 客戶提供的證實來源（法規／宣稱類確認時必填，R10）
    outcome TEXT NOT NULL,                  -- pending / confirmed / pending_saved / discarded
    target_table TEXT,                      -- 寫入正式表後回填
    target_id TEXT,                         -- 寫入正式表後回填（跨模組引用）
    processed_by TEXT,
    processed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intake_item_draft_row ON intake_item(intake_draft_id, row_no);
CREATE INDEX IF NOT EXISTS idx_intake_item_brand_outcome ON intake_item(brand_id, outcome);
