-- app/ads/migrations/0007_retire_cycle_reminder.sql
-- 檔期提醒卡改走全站打斷佇列（app/core/interrupts.py，GitHub issue #32，決策 0026 第 4 點）。
-- 這張表已無任何程式碼寫入，直接退場，避免留下孤兒表。
DROP TABLE IF EXISTS cycle_reminder;
