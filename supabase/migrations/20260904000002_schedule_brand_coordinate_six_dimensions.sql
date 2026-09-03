-- supabase/migrations/20260904000002_schedule_brand_coordinate_six_dimensions.sql
-- Module: schedule (ADR 0049 -- schedule owns brand_coordinate). Ticket: T8a
-- (docs/issues/t8a-six-dimension-vocabulary/ticket.md). Data model of record: ADR 0050.
--
-- Constitution rule 5: the seven-dimension fingerprint. `brand_coordinate.dimension`'s CHECK
-- has carried all seven values since 20260901000002_schedule_creative_coordinates.sql; that
-- file already back-filled the 35 `angle` seeds. This migration back-fills the 33 seeds
-- across the other six dimensions (audience 5, pain 6, hook 5, proof 7, offer 7, format 3)
-- for every brand that already exists, same shape as that file's own back-fill: brands
-- created after this migration are seeded lazily by
-- app/schedule/repository.py::ensure_coordinates_seeded() (same 33 rows, kept in sync by
-- hand -- SQL migrations cannot reference application code, per that file's own comment).
--
-- Transcribed literally from the ticket's six vocabulary tables (hook's `situation` column
-- is app/methodology/copywriting.md:35-43's formula, character for character; format's
-- `situation` values are app/methodology/meta-format-specs.md:16,34,49). `key` is permanent:
-- app/schedule/performance.py groups performance by it forever.

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'audience',
       v.key, v.label, '漏斗關係', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('cold_unaware', '陌生・不知有問題', '連自己有這個困擾都還沒意識到'),
    ('cold_problem_aware', '陌生・知道問題', '知道自己痛，不知道有解法'),
    ('warm_engaged', '互動過・沒買', '看過、點過、加過購物車'),
    ('customer_repeat', '已購・回購', '買過，這則是要他再買'),
    ('lapsed', '流失・喚回', '買過但久沒回來')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'pain',
       v.key, v.label, '痛苦類型', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('cost', '太貴', '花太多錢，或覺得不值這個價'),
    ('effort', '太麻煩', '花太多時間、步驟太多、要學'),
    ('uncertainty', '怕買錯', '不知道有沒有效、不知道適不適合自己'),
    ('availability', '買不到', '缺貨、通路不便、取得困難'),
    ('experience', '用起來不舒服', '現有方案能用但體驗差'),
    ('identity', '不像我', '面子、不符合我想成為的樣子')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'hook',
       v.key, v.label, '標題公式', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('pain_question', '痛點提問', '還在為{痛點}{受影響的行為}？'),
    ('outcome_led', '結果導向', '達成{渴望}不必{代價}'),
    ('never_again', '永不再犯', '再也不用{討厭的事}'),
    ('contrast_flip', '反差對比', '你以為是{貴／麻煩}？其實{便宜／簡單}'),
    ('proof_led', '證明導向', '{數字}{人}用{產品}達到{結果}')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'proof',
       v.key, v.label, '證據來源', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('customer_review', '顧客評論原話', '評論卡、見證疊層、前後對比——原文照搬，不改寫'),
    ('expert_endorsement', '專家背書', '真實醫師／營養師／教練現身'),
    ('lab_report', '檢驗報告／認證', '檢驗數據、專利、獎項'),
    ('sales_numbers', '銷售數據', '銷量、好評率、回購率——絕不捏造'),
    ('media_coverage', '媒體報導', '只能用真的報導過你的媒體'),
    ('founder_voice', '創辦人第一手', '創辦初衷、起源故事——捏造會整個垮掉'),
    ('none', '無證明', '純訴求，這一則不帶任何外部證據')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'offer',
       v.key, v.label, '誘因類型', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('none', '無優惠', '只講價值，不給誘因'),
    ('discount', '折扣特價', '錨定效應、尾數定價'),
    ('bundle', '組合加贈', '心理帳戶、免費效應'),
    ('free_shipping', '免運', '免費效應——拉首購比等額折扣有感'),
    ('trial_sample', '試用體驗', '互惠原則、承諾與一致性'),
    ('guarantee', '保證退換', '後悔規避'),
    ('limited_time', '限時限量', '稀缺與急迫——只在真的限時限量時用，捏造見禁用手法')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'format',
       v.key, v.label, 'Meta 版位', jsonb_build_object('situation', v.situation)
FROM brand
CROSS JOIN (VALUES
    ('single_image', '單圖', '4:5，1080×1350（查證日 2026-08-07）'),
    ('carousel', '輪播', '多卡，每卡連結由組裝時帶入'),
    ('video', '影片', '每主題媒體上限 1（主題＝腳本）')
) AS v(key, label, situation)
ON CONFLICT (brand_id, dimension, key) DO NOTHING;
