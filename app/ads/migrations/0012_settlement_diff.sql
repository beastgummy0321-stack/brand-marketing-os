-- app/ads/migrations/0012_settlement_diff.sql
-- 三段判讀節奏＋補件重判＋翻盤警示（GitHub issue #38，決策 0025 判讀節奏第 5 點、
-- 審查補遺 C「結案後的變動…不靜默覆蓋」）。
--
-- 晚到檔案觸發的補件重判（app/ads/reading.py rerun_for_late_data）把「這一版跟上一版
-- 差在哪」的人話說明存在觸發出的那一版 settlement_version 上——UI 見到這欄有值就代表
-- 這版不是使用者主動按「重新判讀」，而是補件自動觸發的，直接顯示差異摘要，不靜默覆蓋。
-- 一般判讀（initial／manual_rerun）維持 NULL。
ALTER TABLE settlement_version ADD COLUMN diff_summary TEXT;
