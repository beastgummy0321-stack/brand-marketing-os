-- storage-slice ticket 02: official_asset.file_path -> storage_key.
-- 官方素材從本機磁碟搬進 Supabase Storage（app/storage/），欄位改名反映新形狀：
-- 存的不再是本機絕對路徑，是 Storage 物件 key（<org_id>/brands/<brand_id>/assets/<asset_id>/<filename>）。
-- 既有資料不搬（CLAUDE.md 資料狀態：系統未發布，data/ 全為測試資料，可直接刪除重建）。
ALTER TABLE official_asset RENAME COLUMN file_path TO storage_key;
