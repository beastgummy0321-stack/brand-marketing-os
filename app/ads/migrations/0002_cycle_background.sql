-- app/ads/migrations/0002_cycle_background.sql
-- 票 3：開期表單新增選填「這期有什麼背景？」欄位（活動、新品、時事），
-- 讓計畫生成出方案前先知道脈絡（決策 0023 第 2 點）。選填，可為 NULL。
ALTER TABLE campaign_cycle ADD COLUMN background TEXT;
