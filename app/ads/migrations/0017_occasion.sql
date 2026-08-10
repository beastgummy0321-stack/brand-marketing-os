-- app/ads/migrations/0017_occasion.sql
-- 檔期情境自動標籤（票 01-occasion-auto-tagging，ADR 0011 第四節）。
--
-- occasion：節日名稱字串，或 NULL 代表常態檔期。開檔期時由 app/ads/repository.py
-- create_cycle() 呼叫 app/ads/occasion.py 自動比對既有節日日曆帶入。
--
-- 不回填既有列：NULL 本來就是「常態檔期」的正確終值，不是佔位符——舊檔期沒被判過
-- 不代表判了會是別的值，跟 funnel_stage（0014，舊資料有明確可推導的正確值）情況不同。
-- ALTER TABLE ADD COLUMN 對既有列一律補 NULL，向下相容既有資料。
ALTER TABLE campaign_cycle ADD COLUMN occasion TEXT;
