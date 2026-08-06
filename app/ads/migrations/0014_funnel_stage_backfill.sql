-- app/ads/migrations/0014_funnel_stage_backfill.sql
-- 漏斗階段回填（票 04-wire-funnel-stage）：funnel_stage 欄位早就存在（0001_tables.sql），
-- 但開期一路寫 None，從沒人讀過。改用 app/ads/repository.py create_cycle() 接上
-- app/ads/plan.py OBJECTIVE_TO_FUNNEL_STAGE 對照表之後，這裡把既有檔期（開期時沒被
-- 這套邏輯覆蓋到的舊資料）一次回填，不留空值。
--
-- 對照關係抄自 app/ads/plan.py OBJECTIVE_TO_FUNNEL_STAGE（唯一事實來源）；
-- 這裡是一次性資料回填，不是常駐邏輯，往後新開期一律由程式那份對照表決定。
UPDATE campaign_cycle SET funnel_stage = CASE objective
    WHEN 'awareness' THEN 'exposure'
    WHEN 'traffic' THEN 'consideration'
    WHEN 'engagement' THEN 'consideration'
    WHEN 'leads' THEN 'conversion'
    WHEN 'sales' THEN 'conversion'
    ELSE funnel_stage
END
WHERE funnel_stage IS NULL;
