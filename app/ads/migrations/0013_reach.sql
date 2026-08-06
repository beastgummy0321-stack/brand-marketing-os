-- app/ads/migrations/0013_reach.sql
-- 觸及（reach）：平台中立的漏斗上層主指標，曝光期檔期要看的主指標之一（票 03-add-reach-metric）。
-- 新增欄位、不用「曝光÷頻率」推導（使用者 2026-08-06 grill 第 13 題明確選擇）。
-- 可為 NULL、不設預設值：「沒收到觸及資料」跟「觸及是 0」必須分得出來（鐵則 16）。
ALTER TABLE performance_snapshot ADD COLUMN reach INTEGER;
