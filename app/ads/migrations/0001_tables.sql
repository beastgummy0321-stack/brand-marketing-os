-- app/ads/migrations/0001_tables.sql
-- 廣告分支（路線圖分支 1）全部資料表。
--
-- 來源：docs/design/03-data-model.md §4（Phase 1–4 主要實體）、§5（Phase 6 成效學習層），
-- 加上 docs/decisions/0022 的差異（一期多產品、一帳號多品牌的歸屬認領、滑桿三欄位、
-- 素材指紋、規則卡、統一 Finding、檔期提醒）。
--
-- 模組切分：03 §8 把廣告閉環拆成 Campaign Planning／Creative Studio／Publishing Handoff／
-- Performance Analytics／Experimentation 五個概念模組。實作上合併為單一 `ads` 模組，理由：
-- 鐵則 7 的單位是「能獨立使用的東西」，而這五段沒有一段能單獨使用（沒有計畫就沒有素材，
-- 沒有素材就沒有交接包）——廣告閉環才是那個單位。概念分區以本檔的分節註解保留；
-- 日後真要拆模組，把跨段外鍵降級為 TEXT ref 即可（拆比合容易）。
--
-- 慣例（03 §1）：id 帶類型前綴、時間存 ISO-8601 UTC 字串、同模組內用真外鍵、
-- 跨模組（brand/product/rule/claim/strategy_hypothesis/official_asset）只用 TEXT id 不建外鍵。
-- 所有品牌範圍表帶 brand_id（去正規化亦帶），存取層一律注入 WHERE brand_id = ?（§7）。

-- ============================================================
-- A. 計畫層（Campaign Planning）
-- ============================================================

-- Meta 廣告帳號。刻意不帶 brand_id：一個帳號可服務多個品牌（決策 0022 第 6 點），
-- 品牌歸屬由 external_ad_mapping／discovered_campaign 逐個 Campaign 認定，不由帳號推導。
CREATE TABLE IF NOT EXISTS ad_account (
    id TEXT PRIMARY KEY,                    -- adc_*
    platform TEXT NOT NULL,                 -- meta（D6：只實作 Meta，欄位保留）
    external_account_id TEXT NOT NULL,      -- Meta act_XXXX
    name TEXT,
    currency TEXT,
    status TEXT NOT NULL,                   -- active/disconnected
    last_synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ad_account_external
    ON ad_account(platform, external_account_id);

CREATE TABLE IF NOT EXISTS campaign_cycle (
    id TEXT PRIMARY KEY,                    -- ccy_*
    brand_id TEXT NOT NULL,                 -- 跨模組引用（無 DB 外鍵），仍是隔離鍵
    ad_account_id TEXT REFERENCES ad_account(id),
    product_scope_json TEXT NOT NULL,       -- 'brand' 或 product_id 陣列（明細見 campaign_cycle_product）
    objective TEXT NOT NULL,
    funnel_stage TEXT,
    budget REAL,                            -- 本期總預算（程式由滑桿反推或使用者直接填）
    currency TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    target_market TEXT,
    channels_json TEXT NOT NULL,
    placements_json TEXT,
    offer_id TEXT,                          -- FK 於 offer 建立後補（見檔尾註）
    landing_page TEXT,
    status TEXT NOT NULL,                   -- PLANNING/REVIEW/PRODUCTION/LIVE/EVALUATING/CLOSED（05 狀態機）
    close_reason TEXT,                      -- COMPLETED/CANCELLED
    blocked INTEGER,
    needs_information INTEGER,
    archived INTEGER NOT NULL DEFAULT 0,
    plan_version INTEGER NOT NULL DEFAULT 0,
    -- 決策 0022 第 10、14、23 點（新手心理曲線／紙上模擬）
    phase TEXT NOT NULL DEFAULT 'normal',   -- simulation（紙上模擬）/calibration（第一期校準）/normal
    pain_slider_value REAL,                 -- 「賠光也不心痛」滑桿原始值；由此反推預算與期長
    derived_plan_json TEXT,                 -- 滑桿反推結果（日預算、期長、停損、暫停門檻、校準區間）
    diff_snapshot_json TEXT,                -- 與上期的差異快照，供第二期起的「差異視圖」
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaign_cycle_brand_id ON campaign_cycle(brand_id);
CREATE INDEX IF NOT EXISTS idx_campaign_cycle_status ON campaign_cycle(brand_id, status);

-- 一期含多個產品（決策 0022 第 5 點）＋ 產品層預算分配（第 9 點）。
-- allocation_basis='even' 且 economics_missing=1 時，介面需標「精準度打折」並給一鍵去補。
CREATE TABLE IF NOT EXISTS campaign_cycle_product (
    id TEXT PRIMARY KEY,                    -- ccp_*
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    product_id TEXT NOT NULL,               -- 跨模組引用 product
    allocated_budget REAL,
    allocation_ratio REAL,                  -- 佔本期總預算比例（程式算，使用者可改）
    -- economics（有自己的毛利）/estimated（用其他產品的平均毛利代入）/even（全都沒毛利資料）/
    -- manual（使用者手動改過）。產出邏輯見 app/ads/budget.py split_budget()。
    allocation_basis TEXT NOT NULL,
    economics_missing INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ccp_cycle_product
    ON campaign_cycle_product(campaign_cycle_id, product_id);
CREATE INDEX IF NOT EXISTS idx_ccp_brand_id ON campaign_cycle_product(brand_id);

CREATE TABLE IF NOT EXISTS marketing_goal (
    id TEXT PRIMARY KEY,                    -- gol_*
    brand_id TEXT NOT NULL,
    product_id TEXT,
    objective_summary TEXT NOT NULL,
    status TEXT NOT NULL,                   -- active/achieved/dropped
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marketing_goal_brand_id ON marketing_goal(brand_id);

CREATE TABLE IF NOT EXISTS success_criterion (
    id TEXT PRIMARY KEY,                    -- scr_*
    goal_id TEXT NOT NULL REFERENCES marketing_goal(id),
    brand_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    target_value REAL NOT NULL,
    unit TEXT,
    evaluation_period TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_success_criterion_goal_id ON success_criterion(goal_id);
CREATE INDEX IF NOT EXISTS idx_success_criterion_brand_id ON success_criterion(brand_id);

CREATE TABLE IF NOT EXISTS campaign_cycle_goal (
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    goal_id TEXT NOT NULL REFERENCES marketing_goal(id),
    brand_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    PRIMARY KEY (campaign_cycle_id, goal_id)
);
CREATE INDEX IF NOT EXISTS idx_ccg_brand_id ON campaign_cycle_goal(brand_id);

CREATE TABLE IF NOT EXISTS campaign_cycle_hypothesis (
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    strategy_hypothesis_id TEXT NOT NULL,   -- 跨模組引用 strategy_hypothesis
    brand_id TEXT NOT NULL,
    role TEXT NOT NULL,                     -- audience/message
    PRIMARY KEY (campaign_cycle_id, strategy_hypothesis_id)
);
CREATE INDEX IF NOT EXISTS idx_cch_brand_id ON campaign_cycle_hypothesis(brand_id);

CREATE TABLE IF NOT EXISTS offer (
    id TEXT PRIMARY KEY,                    -- ofr_*
    brand_id TEXT NOT NULL,
    product_scope_json TEXT NOT NULL,
    name TEXT NOT NULL,
    offer_type TEXT NOT NULL,               -- discount/bundle/gift…
    terms TEXT NOT NULL,
    price_value REAL,
    currency TEXT,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,                 -- 過期不進 Context 事實區
    status TEXT NOT NULL,                   -- draft/active/expired
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offer_brand_id ON offer(brand_id);

CREATE TABLE IF NOT EXISTS experiment_cell (
    id TEXT PRIMARY KEY,                    -- exc_*
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,                        -- 決策 0022 第 8 點：判讀要能按產品分組
    audience TEXT,
    awareness_stage TEXT,
    pain_point TEXT,
    benefit TEXT,
    creative_angle TEXT,
    format TEXT,
    cta TEXT,
    audience_hypothesis_id TEXT,            -- 跨模組引用 strategy_hypothesis
    message_hypothesis_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiment_cell_cycle_id ON experiment_cell(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_experiment_cell_brand_id ON experiment_cell(brand_id);

-- append-only：存取層禁止 UPDATE/DELETE（03 §8.5）
CREATE TABLE IF NOT EXISTS campaign_plan (
    id TEXT PRIMARY KEY,                    -- cpl_*
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    brand_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT NOT NULL,                   -- draft/approved/superseded
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_plan_version
    ON campaign_plan(campaign_cycle_id, plan_version);
CREATE INDEX IF NOT EXISTS idx_campaign_plan_brand_id ON campaign_plan(brand_id);

-- ============================================================
-- B. 素材層（Creative Studio）
-- ============================================================

CREATE TABLE IF NOT EXISTS creative_brief (
    id TEXT PRIMARY KEY,                    -- cbf_*
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    brand_id TEXT NOT NULL,
    brief_type TEXT NOT NULL,               -- image/video/copy
    purpose TEXT NOT NULL,
    constraints TEXT,
    expected_output TEXT,
    status TEXT NOT NULL,                   -- draft/dispatched
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_brief_cycle_id ON creative_brief(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_creative_brief_brand_id ON creative_brief(brand_id);

-- 統一變體表（03 §4.2 設計取捨）：image_prompt/hook/script/copy 共用，
-- 型別專屬欄位放 attributes_json，由 app 依 variant_type 驗證。
CREATE TABLE IF NOT EXISTS creative_variant (
    id TEXT PRIMARY KEY,                    -- cvr_*
    variant_type TEXT NOT NULL,             -- image_prompt/hook/script/copy
    creative_brief_id TEXT NOT NULL REFERENCES creative_brief(id),
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    brand_id TEXT NOT NULL,
    product_id TEXT,                        -- 一期多產品：這則素材為哪個產品而生
    product_scope_json TEXT,
    audience_hypothesis_id TEXT,
    cta TEXT,
    claim_id TEXT,                          -- 跨模組引用 claim（法務掃描依據之一）
    product_facts_used_json TEXT,
    attributes_json TEXT NOT NULL,
    -- 決策 0022 第 25 點：素材結構化指紋（角度／語氣／格式／賣點四軸，封閉枚舉）。
    -- 拒絕記憶靠它累積，程式管約束、LLM 只翻人話（決策 0016 硬性原則 4）。
    fingerprint_json TEXT,
    rationale TEXT,
    recommendation_rank INTEGER,            -- AI 推薦強度排序，供反對制介面預設排列
    status TEXT NOT NULL,                   -- DRAFT/REVIEW/…（05 狀態機）
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_creative_variant_cycle_id ON creative_variant(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_creative_variant_brand_id ON creative_variant(brand_id);
CREATE INDEX IF NOT EXISTS idx_creative_variant_brief_id ON creative_variant(creative_brief_id);

CREATE TABLE IF NOT EXISTS final_asset (
    id TEXT PRIMARY KEY,                    -- fas_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    source_variant_id TEXT NOT NULL REFERENCES creative_variant(id),
    asset_type TEXT NOT NULL,               -- image/video
    file_path TEXT NOT NULL,
    manual_edits_note TEXT,
    status TEXT NOT NULL,                   -- DRAFT/REVIEW/APPROVED/LIVE/RETIRED
    blocked INTEGER,
    needs_information INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_final_asset_brand_id ON final_asset(brand_id);
CREATE INDEX IF NOT EXISTS idx_final_asset_cycle_id ON final_asset(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_final_asset_variant_id ON final_asset(source_variant_id);

-- 採用／拒絕決定。反對制（決策 0022 第 12 點）下預設全採用，只有剔除才產生 rejected 列。
-- fingerprint_json 是決定當下的指紋快照——變體日後可能改動或清掉，拒絕記憶不能靠 join 回去拿。
CREATE TABLE IF NOT EXISTS adoption_decision (
    id TEXT PRIMARY KEY,                    -- adp_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    target_type TEXT NOT NULL,              -- variant/final_asset
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL,                 -- adopted/rejected/edited_approved/not_applicable
    reason_code TEXT,                       -- 點選式理由（封閉枚舉，票 6 定表）
    reason_text TEXT,                       -- 選填自訂原因；保存但不自動變品牌規則
    fingerprint_json TEXT,                  -- 決定當下的素材指紋快照
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adoption_decision_brand_id ON adoption_decision(brand_id);
CREATE INDEX IF NOT EXISTS idx_adoption_decision_target ON adoption_decision(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_adoption_decision_cycle_id ON adoption_decision(campaign_cycle_id);

-- 規則卡（決策 0022 第 13 點）：同一指紋標籤累積被拒達門檻 → 產一張候選規則卡，
-- 掛在下一期「計畫確認」關卡內、預設已同意；使用者接受才升級為品牌智庫的 rule。
-- 不獨立成第四道關卡。
CREATE TABLE IF NOT EXISTS creative_rule_card (
    id TEXT PRIMARY KEY,                    -- rcd_*
    brand_id TEXT NOT NULL,
    product_id TEXT,
    fingerprint_axis TEXT NOT NULL,         -- angle/tone/format/selling_point
    fingerprint_value TEXT NOT NULL,
    proposed_rule_text TEXT NOT NULL,       -- 人話：「不要再出現__」
    evidence_json TEXT NOT NULL,            -- 佐證：被拒次數、來源 adoption_decision id 陣列
    reject_count INTEGER NOT NULL,
    status TEXT NOT NULL,                   -- pending/accepted/declined/expired
    promoted_rule_id TEXT,                  -- 接受後對應的品牌智庫 rule id（跨模組引用）
    surfaced_cycle_id TEXT REFERENCES campaign_cycle(id),  -- 在哪一期的計畫確認頁出現
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_card_brand_id ON creative_rule_card(brand_id);
CREATE INDEX IF NOT EXISTS idx_rule_card_status ON creative_rule_card(brand_id, status);

-- ============================================================
-- C. 交接與授權層（Publishing Handoff）
-- ============================================================

CREATE TABLE IF NOT EXISTS publishing_package (
    id TEXT PRIMARY KEY,                    -- pkg_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    product_id TEXT,
    final_asset_id TEXT REFERENCES final_asset(id),
    hook_id TEXT REFERENCES creative_variant(id),
    script_id TEXT REFERENCES creative_variant(id),
    copy_variant_id TEXT REFERENCES creative_variant(id),
    campaign_name TEXT NOT NULL,
    adset_name TEXT NOT NULL,
    ad_name TEXT NOT NULL,
    destination_url TEXT NOT NULL,
    utm_json TEXT NOT NULL,
    placement TEXT,
    objective TEXT,
    daily_budget REAL,                      -- 交接包要寫給人照著設定的數字（程式算，非 LLM）
    note TEXT,
    status TEXT NOT NULL,                   -- draft/ready
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publishing_package_brand_id ON publishing_package(brand_id);
CREATE INDEX IF NOT EXISTS idx_publishing_package_cycle_id ON publishing_package(campaign_cycle_id);

-- 具名授權：authorized_by NOT NULL 是安全邊界的結構性保證（鐵則 4）——
-- 缺具名操作人就建不出這一列，因此任何投放啟動都不可能由排程或核准自動推導。
CREATE TABLE IF NOT EXISTS activation_authorization (
    id TEXT PRIMARY KEY,                    -- ath_*
    brand_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,               -- publication/campaign_activation
    scope_ref TEXT NOT NULL,
    authorized_by TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activation_auth_brand_id ON activation_authorization(brand_id);

-- Meta 物件對應。claim_status 是決策 0022 第 7 點的品牌隔離保證：
-- 系統依命名猜的歸屬一律停在 suggested，使用者確認後才 confirmed，只有 confirmed 才計入品牌。
CREATE TABLE IF NOT EXISTS external_ad_mapping (
    id TEXT PRIMARY KEY,                    -- xam_*
    brand_id TEXT NOT NULL,
    publishing_package_id TEXT REFERENCES publishing_package(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    ad_account_id TEXT REFERENCES ad_account(id),
    platform TEXT NOT NULL,                 -- meta
    meta_account_id TEXT,
    meta_campaign_id TEXT,
    meta_adset_id TEXT,
    meta_ad_id TEXT,
    meta_creative_id TEXT,
    internal_asset_id TEXT REFERENCES final_asset(id),
    claim_status TEXT NOT NULL DEFAULT 'confirmed',  -- suggested/confirmed（人工回填者直接 confirmed）
    confirmed_by TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xam_brand_id ON external_ad_mapping(brand_id);
CREATE INDEX IF NOT EXISTS idx_xam_cycle_id ON external_ad_mapping(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_xam_meta_campaign ON external_ad_mapping(meta_campaign_id);

CREATE TABLE IF NOT EXISTS campaign_activation (
    id TEXT PRIMARY KEY,                    -- act_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    authorization_id TEXT NOT NULL REFERENCES activation_authorization(id),
    activated_by TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaign_activation_brand_id ON campaign_activation(brand_id);
CREATE INDEX IF NOT EXISTS idx_campaign_activation_cycle_id ON campaign_activation(campaign_cycle_id);

-- ============================================================
-- D. 成效層（Performance Analytics）
-- ============================================================

-- 同步時在廣告帳號上發現、但還沒認領歸屬的 Meta Campaign。
-- 刻意「不」帶 NOT NULL brand_id：未認領的東西不屬於任何品牌（決策 0022 第 7 點）。
-- 認領後才寫進 external_ad_mapping；在此之前它的成效不進任何品牌的判讀。
CREATE TABLE IF NOT EXISTS discovered_campaign (
    id TEXT PRIMARY KEY,                    -- dsc_*
    ad_account_id TEXT NOT NULL REFERENCES ad_account(id),
    platform TEXT NOT NULL,
    meta_campaign_id TEXT NOT NULL,
    campaign_name TEXT,
    objective TEXT,
    effective_status TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    suggested_brand_id TEXT,                -- 依命名規則猜的歸屬，僅供預選，不生效
    suggested_reason TEXT,                  -- 人話：為什麼猜這個品牌
    claim_status TEXT NOT NULL,             -- unclaimed/suggested/claimed/ignored
    claimed_brand_id TEXT,                  -- 使用者確認的歸屬
    claimed_by TEXT,
    claimed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_discovered_campaign_external
    ON discovered_campaign(ad_account_id, meta_campaign_id);
CREATE INDEX IF NOT EXISTS idx_discovered_campaign_status ON discovered_campaign(claim_status);

-- append-only：只累積不覆寫（03 §8.5）。
-- 正規化欄位（impressions…revenue）是決策 0016 硬性原則 2 的落點：CSV／手動／API 三個來源
-- 都先轉成這幾個欄位，下游（derived_metric、performance_reading）只認這一種格式，
-- raw_json 僅留原始資料備查，不供判讀直接讀取。
CREATE TABLE IF NOT EXISTS performance_snapshot (
    id TEXT PRIMARY KEY,                    -- psn_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    product_id TEXT,
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    platform TEXT NOT NULL,
    account_id TEXT,
    meta_campaign_id TEXT,
    meta_adset_id TEXT,
    meta_ad_id TEXT,
    date_range_start TEXT NOT NULL,
    date_range_end TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    snapshot_taken_at TEXT NOT NULL,
    currency TEXT NOT NULL,
    -- 統一正規化欄位
    impressions INTEGER,
    clicks INTEGER,
    spend REAL,
    conversions REAL,
    revenue REAL,
    raw_json TEXT,
    reconciled INTEGER NOT NULL DEFAULT 0,  -- 0＝本日未對帳（明確標示缺漏，不沿用舊值）
    source TEXT NOT NULL,                   -- csv/manual/meta_api/simulated
    import_batch_id TEXT,
    -- 合理性海關（決策 0022 其餘入選點子）：CTR>100%、負花費、未來日期等進隔離區，不進判讀
    quarantined INTEGER NOT NULL DEFAULT 0,
    quarantine_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_psn_brand_id ON performance_snapshot(brand_id);
CREATE INDEX IF NOT EXISTS idx_psn_cycle_id ON performance_snapshot(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_psn_as_of ON performance_snapshot(brand_id, as_of_date);

CREATE TABLE IF NOT EXISTS derived_metric (
    id TEXT PRIMARY KEY,                    -- dmt_*
    brand_id TEXT NOT NULL,
    performance_snapshot_id TEXT NOT NULL REFERENCES performance_snapshot(id),
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    product_id TEXT,
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    metric TEXT NOT NULL,                   -- ctr/cpa/roas…
    value REAL NOT NULL,
    unit TEXT,
    calc_basis TEXT,
    computed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dmt_brand_id ON derived_metric(brand_id);
CREATE INDEX IF NOT EXISTS idx_dmt_snapshot_id ON derived_metric(performance_snapshot_id);

-- ============================================================
-- E. 判讀與學習層（Experimentation）
-- ============================================================

-- product_id 是決策 0022 第 8 點：判讀最小單位＝產品層，檔期層只給一句總結
-- （product_id 為 NULL 的那一列即檔期層總結）。
CREATE TABLE IF NOT EXISTS performance_reading (
    id TEXT PRIMARY KEY,                    -- prd_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    product_id TEXT,
    experiment_cell_id TEXT REFERENCES experiment_cell(id),
    external_ad_mapping_id TEXT REFERENCES external_ad_mapping(id),
    status TEXT NOT NULL,                   -- insufficient_data/learning/maintain/scale_candidate/
                                            -- creative_iteration/audience_iteration/offer_iteration/
                                            -- landing_page_investigation/pause_candidate/completed/archived
    rule_result_json TEXT NOT NULL,         -- 程式的確定性計算與資料充足性判斷（判讀由規則定，非 LLM）
    confidence_level TEXT,                  -- 本期判讀可信度（受 finding 的 confidence_penalty 影響）
    llm_explanation TEXT,                   -- LLM 只負責翻成人話
    llm_task_id TEXT,                       -- 跨模組引用 core.llm_task
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prd_brand_id ON performance_reading(brand_id);
CREATE INDEX IF NOT EXISTS idx_prd_cycle_id ON performance_reading(campaign_cycle_id);

CREATE TABLE IF NOT EXISTS recommendation (
    id TEXT PRIMARY KEY,                    -- rec_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    product_id TEXT,
    performance_reading_id TEXT REFERENCES performance_reading(id),
    recommendation_type TEXT NOT NULL,      -- scale/maintain/iterate/pause/next_cycle
    content_json TEXT NOT NULL,
    status TEXT NOT NULL,                   -- DRAFT/GENERATED/REVIEWED/ACCEPTED/REJECTED/APPLIED/…
    blocked INTEGER,
    needs_information INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_brand_id ON recommendation(brand_id);
CREATE INDEX IF NOT EXISTS idx_rec_cycle_id ON recommendation(campaign_cycle_id);

-- append-only。只新增、可追溯、絕不改寫事實層（鐵則 3）。
CREATE TABLE IF NOT EXISTS learning_ledger (
    id TEXT PRIMARY KEY,                    -- lrn_*
    brand_id TEXT NOT NULL,
    product_id TEXT,
    platform TEXT,
    learning_text TEXT NOT NULL,
    applicability_scope TEXT NOT NULL,
    source_cycle_id TEXT REFERENCES campaign_cycle(id),
    source_reading_id TEXT REFERENCES performance_reading(id),
    source_hypothesis_id TEXT,              -- 跨模組引用 strategy_hypothesis
    sample_size TEXT,
    confidence TEXT,
    needs_revalidation INTEGER NOT NULL DEFAULT 0,
    expired INTEGER NOT NULL DEFAULT 0,
    learned_at TEXT NOT NULL,
    created_by TEXT NOT NULL,               -- Supported→Learning 必須由人確認
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lrn_brand_id ON learning_ledger(brand_id);
CREATE INDEX IF NOT EXISTS idx_lrn_source_cycle ON learning_ledger(source_cycle_id);

-- ============================================================
-- F. 橫切：Finding 與提醒
-- ============================================================

-- 統一 Finding 表。ADHD 設計輸入本來就要求「降級版自答的答案結構與 API diff 產出同一種
-- Finding」；法務掃描命中、對帳不符、增幅上限、回音室偵測結構相同（對象＋嚴重度＋人話＋
-- 可信度扣分），故合一張表，用 finding_type 區分來源。
-- 一律不擋路：只標示、只扣可信度，決策權留給人（決策 0013）。
CREATE TABLE IF NOT EXISTS finding (
    id TEXT PRIMARY KEY,                    -- fnd_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT REFERENCES campaign_cycle(id),
    finding_type TEXT NOT NULL,             -- compliance（法務掃描）/reconciliation（對帳）/
                                            -- external_change（外部改動）/budget_cap（增幅上限）/
                                            -- echo_chamber（素材太像）/data_sanity（成效海關）
    target_type TEXT,                       -- variant/final_asset/package/cycle/snapshot
    target_id TEXT,
    severity TEXT NOT NULL,                 -- info/warn（無 block：提示不擋人）
    code TEXT NOT NULL,                     -- 機器可讀代碼，供測試與統計
    message TEXT NOT NULL,                  -- 人話訊息（鐵則 12：不得出現內部代號）
    evidence_json TEXT,                     -- 佐證：命中哪條 rule/claim、計畫值 vs 實際值…
    confidence_penalty REAL NOT NULL DEFAULT 0,  -- 對本期判讀可信度的扣分
    source TEXT NOT NULL,                   -- api_diff/self_answer（三題降級版）/rule_scan/pure_function
    resolved INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_finding_brand_id ON finding(brand_id);
CREATE INDEX IF NOT EXISTS idx_finding_cycle_id ON finding(campaign_cycle_id);
CREATE INDEX IF NOT EXISTS idx_finding_target ON finding(target_type, target_id);

-- 檔期提醒卡（決策 0022 第 11 點）：第 3 天「可看但別動」、第 7 天／到期「回填成效」。
-- 到期日由 campaign_cycle 的滑桿反推結果算出，本表只負責記「已浮出／已讀」狀態。
CREATE TABLE IF NOT EXISTS cycle_reminder (
    id TEXT PRIMARY KEY,                    -- rmd_*
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL REFERENCES campaign_cycle(id),
    kind TEXT NOT NULL,                     -- day3_look_dont_touch/day7_report/cycle_end
    due_date TEXT NOT NULL,
    dismissed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cycle_reminder_kind
    ON cycle_reminder(campaign_cycle_id, kind);
CREATE INDEX IF NOT EXISTS idx_cycle_reminder_due ON cycle_reminder(brand_id, due_date);

-- 註：campaign_cycle.offer_id 指向 offer(id)，但 campaign_cycle 必須先於 offer 建立
-- （offer 無反向依賴，是建表順序問題）。SQLite 無法事後 ADD CONSTRAINT，且 03 §1 只要求
-- 同模組內「使用真外鍵」而非全部欄位皆外鍵——此處以應用層保證，不為單一欄位重建整張表。
