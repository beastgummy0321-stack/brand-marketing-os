-- app/core/migrations/0002_app_setting.sql
-- app_setting：全站單一鍵值設定表（AI 金鑰、模型選擇、建檔精靈花費上限）。
-- 不分品牌：這些是整台機器的設定，不是品牌資料，所以沒有 brand_id（03 §7 隔離只管品牌資料）。
-- 值一律存 TEXT，數字／布林由存取層轉型（03 §1：SQLite 無原生型別，型別在 app 層把關）。

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
