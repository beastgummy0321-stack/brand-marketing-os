-- 節日相關性業種標籤（ADR 0014 第一節）：brand.industry 供節日日曆判定是否要提醒
-- （app/dashboard/campaign_calendar.py industry_relevant()）。沿用 0005_brand_switches.sql
-- 的做法：ALTER TABLE + enum 限制值（見 app/brand_intelligence/repository.py
-- INDUSTRIES，唯一值域來源）。預設 NULL——既有品牌未設定時，一律視為業種不明，
-- 只對節日標 "all" 的檔期提醒，不倒填猜測值。
ALTER TABLE brand ADD COLUMN industry TEXT;
