-- supabase/migrations/20260901000002_schedule_creative_coordinates.sql
-- Module: schedule (ADR 0049 -- schedule becomes a migration-owning module).
-- Ticket: T1b (docs/issues/T1b-brand-coordinate/ticket.md). Data model of record: ADR 0050.
--
-- Five tables: brand_coordinate (the seven-dimension vocabulary, constitution rule 5) and
-- the four creative-loop tables that freeze it again at generation time (constitution rule 7):
-- creative_slot (the position), creative_candidate (the Nth attempt), creative_candidate_item
-- (carousel cards, one row in v1), feedback (coordinate/candidate/period rejection, scope
-- CHECK carries all three values now, only the first two are written in v1).

CREATE TABLE brand_coordinate (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    dimension TEXT NOT NULL CHECK (dimension IN
        ('audience','pain','angle','hook','proof','offer','format')),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT,
    parent_id TEXT REFERENCES brand_coordinate(id),
    canonical_key TEXT,
    attributes_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brand_id, dimension, key)
);

CREATE TABLE creative_slot (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    ad_node_name TEXT NOT NULL,
    source_tree_task_id TEXT,
    audience_coordinate_id TEXT REFERENCES brand_coordinate(id),
    pain_coordinate_id     TEXT REFERENCES brand_coordinate(id),
    angle_coordinate_id    TEXT REFERENCES brand_coordinate(id),
    hook_coordinate_id     TEXT REFERENCES brand_coordinate(id),
    proof_coordinate_id    TEXT REFERENCES brand_coordinate(id),
    offer_coordinate_id    TEXT REFERENCES brand_coordinate(id),
    format_coordinate_id   TEXT REFERENCES brand_coordinate(id),
    status TEXT NOT NULL CHECK (status IN ('open','filled','exhausted','retired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE creative_candidate (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    slot_id TEXT NOT NULL REFERENCES creative_slot(id),
    generation_round integer NOT NULL DEFAULT 1,
    -- the seven dimensions frozen AGAIN here (ADR 0050): the stable key is what T5 groups by,
    -- the snapshot keeps label/attributes as they read at generation time. Constitution rule 7.
    audience_key TEXT, pain_key TEXT, angle_key TEXT, hook_key TEXT,
    proof_key TEXT, offer_key TEXT, format_key TEXT,
    coordinates_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    coordinates_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (coordinates_status IN ('tagged','pending','not_applicable')),
    visual_tone TEXT CHECK (visual_tone IN ('暗調強對比','暖調生活')),
    visual_concept TEXT,
    selected_at timestamptz,
    reject_reason TEXT,
    published_ad_external_id TEXT,
    provider TEXT,
    provider_job_id TEXT,
    provider_status TEXT,
    llm_task_id TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (slot_id, generation_round)
);

CREATE TABLE creative_candidate_item (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    candidate_id TEXT NOT NULL REFERENCES creative_candidate(id) ON DELETE CASCADE,
    position integer NOT NULL,
    fields_json jsonb NOT NULL,   -- [{"label": str, "value": [str, ...]}] -- array values day one
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, position)
);

CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    scope TEXT NOT NULL CHECK (scope IN ('coordinate','candidate','period')),
    coordinate_id TEXT REFERENCES brand_coordinate(id),
    candidate_id TEXT REFERENCES creative_candidate(id),
    campaign_period_id TEXT,   -- FK added by T2; campaign_period does not exist yet
    reason_code TEXT NOT NULL,
    note TEXT,
    created_by TEXT,
    lifted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (scope = 'coordinate' AND coordinate_id IS NOT NULL)
     OR (scope = 'candidate'  AND candidate_id  IS NOT NULL)
     OR (scope = 'period'     AND campaign_period_id IS NOT NULL)
    )
);

CREATE INDEX brand_coordinate_org_id_idx ON brand_coordinate(org_id);
CREATE INDEX idx_brand_coordinate_brand_id ON brand_coordinate(brand_id);
CREATE INDEX creative_slot_org_id_idx ON creative_slot(org_id);
CREATE INDEX idx_creative_slot_brand_id ON creative_slot(brand_id);
CREATE INDEX creative_candidate_org_id_idx ON creative_candidate(org_id);
CREATE INDEX idx_creative_candidate_brand_id ON creative_candidate(brand_id);
CREATE INDEX creative_candidate_item_org_id_idx ON creative_candidate_item(org_id);
CREATE INDEX idx_creative_candidate_item_brand_id ON creative_candidate_item(brand_id);
CREATE INDEX feedback_org_id_idx ON feedback(org_id);
CREATE INDEX idx_feedback_brand_id ON feedback(brand_id);

ALTER TABLE brand_coordinate ENABLE ROW LEVEL SECURITY;
ALTER TABLE creative_slot ENABLE ROW LEVEL SECURITY;
ALTER TABLE creative_candidate ENABLE ROW LEVEL SECURITY;
ALTER TABLE creative_candidate_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

-- Back-fill the 35 angle seeds for every brand that already exists. Transcribed literally
-- from app/methodology/creative-matrix.md:12-46. `key` is an ASCII snake_case slug minted
-- from the angle name and never changed again (T5 groups performance by it). New brands
-- created after this migration are seeded lazily by app/schedule/repository.py on first read
-- of that brand's coordinates (same 35 rows, kept in sync by hand -- SQL migrations cannot
-- reference application code).
INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'angle',
       v.key, v.label, v.category,
       jsonb_build_object('situation', v.situation, 'lever', v.lever,
                           'person_on_camera', v.person_on_camera, 'funnel_stage', v.funnel_stage)
FROM brand
CROSS JOIN (VALUES
    ('scarcity_marketing', '促銷', '稀缺性行銷', '真的限量的商品、快閃檔期、周年慶捆綁', '稀缺＋損失厭惡', '否', '末端'),
    ('limited_time_offer', '促銷', '限時福利', '真的有時限的優惠、清倉、滿額加贈', '急迫＋損失厭惡', '否', '末端'),
    ('product_explainer', '賣家視角', '產品講解', '新品上市、成分或功能需要教育市場', '具體性降低不確定感', '否', '後段'),
    ('product_evolution', '賣家視角', '產品進化論', '有真實迭代歷程、想展現「有在聽顧客」', 'IKEA 效應＋互惠', '可', '中段'),
    ('user_survey_interaction', '賣家視角', '用戶調查互動', '決定下一批品項或版本時（限有可迭代的商品或服務規格：口味、包裝、功能版本等）', '承諾一致性＋IKEA 效應', '可', '中段'),
    ('self_deprecating_rebuttal', '賣家視角', '自黑／回應質疑', '有真實負評或常見疑慮，願意公開拆解', '疵點效應', '是', '後段'),
    ('benefit_explainer', '買家視角', '功能收益講解', '有真實使用者願意現身說具體改善', '框架效應', '是', '後段'),
    ('pairing_recommendation', '買家視角', '搭配推薦展示', '想拓展使用情境、延伸單次消費金額（限有商品或服務組合可搭售時）', '可得性捷思', '可', '中段'),
    ('daily_use_sharing', '買家視角', '日常應用分享', '想提高「每天都會用到」的實用感', '可得性捷思', '可', '中段'),
    ('user_case_story', '買家視角', '用戶案例故事', '有真實顧客願意分享完整故事', '社會證明', '是', '末端'),
    ('empathy_driven', '感性', '共情驅動', '送禮情境、家庭關係、情感訴求', '情感喚起', '可', '前段'),
    ('identity_affiliation', '感性', '身分認同', '想精準鎖定特定族群（上班族、新手媽媽）', '統一原則', '可', '前段'),
    ('price_reversal', '感性', '價格反轉', '實際單價遠低於顧客第一印象', '錨定＋對比', '否', '前段'),
    ('social_flex', '感性', '社交炫耀', '外型或話題性夠強、容易被朋友問', '社會證明＋模仿慾望', '可', '中段'),
    ('values_and_beliefs', '感性', '價值觀理念', '品牌有明確理念（環保、極簡、在地）要長期經營', '統一原則', '否', '中段'),
    ('pain_point_barrage', '感性', '痛點轟炸', '有一個具體、高頻的痛苦瞬間可聚焦', '損失厭惡＋可得性捷思', '可', '最前段'),
    ('trending_topic_tiein', '感性', '熱點借勢', '節慶、時事、季節熱潮明確且在時效內', '從眾＋單純曝光', '可', '前段'),
    ('precision_dissuasion', '反向行銷', '精準勸退', '想篩出精準受眾、降低無效點擊', '逆反心理＋自我選擇', '可', '前段'),
    ('expert_endorsement', '權威', '專家背書', '有真實醫師／營養師／教練願意背書', '權威效應', '是', '後段'),
    ('credential_showcase', '權威', '資質認證展示', '有真實檢驗報告、專利、獎項', '權威效應', '否', '後段'),
    ('data_endorsement', '權威', '數據背書', '有真實銷量、好評率、回購率', '社會證明（數字化）', '否', '末端'),
    ('personal_track_record', '權威', '個人經歷背書', '有真實長年經驗者（非明星代言）願意現身', '權威＋相似性偏誤', '是', '後段'),
    ('immersive_asmr', '審美治癒', '沉浸式／ASMR', '開箱、使用過程本身有明顯聲音質感', '峰值體驗；感官沉浸', '否', '前段'),
    ('mood_cinematic', '審美治癒', '氛圍感大片', '想賣一種生活風格而不只是功能', '模仿慾望＋生活方式框架', '可', '中段'),
    ('hardcore_review', '理性', '硬核測評', '有可公開驗證的極限實驗或量化數據', '權威＋具體性證據', '可', '後段'),
    ('how_to_tutorial', '理性', '乾貨教程', '顧客常用錯方法、需要示範正確用法', '互惠＋權威', '可', '中段'),
    ('competitor_comparison', '理性', '競品對比', '有可佐證的功能差異，用畫面對比而非指名貶低', '對比＋錨定', '否', '前段'),
    ('trend_forecast', '理性', '趨勢預測分析', '想吸引早期採用者、理念認同者', '稀缺（早期身分）＋權威', '否', '中段'),
    ('deep_teardown', '視覺', '深度拆解', '產品結構、用料、工藝是賣點（限有實體商品；純服務或虛擬商品不適用）', '好奇缺口＋具體性', '否', '後段'),
    ('factory_traceability', '視覺', '工廠溯源', '有真實可拍攝的產地或產線（限有實體製造流程；代工貼牌無產線可拍、或服務型商品不適用）', '權威＋信任捷思', '可', '後段'),
    ('ugc_disguise', 'Meta 特化', 'UGC 偽裝', '想降低廣告感、提高自然互動、壓低 CPM', '相似性偏誤＋降低廣告防禦', '是', '前段'),
    ('scroll_stopping_visual', 'Meta 特化', '滑動阻斷視覺', 'Feed 冷開場，要提高第一張圖的停留率', '對比效應（視覺異常即停留）', '否', '最前段'),
    ('category_replacement', 'Meta 特化', '品類替換對峙', '顧客現有替代方案明確（自己熬湯、喝咖啡）', '對比＋錨定', '可', '前段'),
    ('moment_anchoring', 'Meta 特化', '時刻錨定', '想把產品綁進顧客一天中的具體時刻', '情境錨定', '可', '中段'),
    ('objection_qa_barrage', 'Meta 特化', '疑慮 Q&A 連發', '末端猶豫受眾、常見疑慮明確可條列', '損失規避', '可', '末端')
) AS v(key, category, label, situation, lever, person_on_camera, funnel_stage)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;
