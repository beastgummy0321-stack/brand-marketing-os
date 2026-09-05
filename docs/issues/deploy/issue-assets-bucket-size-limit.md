# `assets` bucket 補 `file_size_limit`

Status: before-cloud——2026-09-05 從 `docs/tech-debt.md` §七認領進上雲目標（使用者裁決：上雲前全清）。
路線：route C（schema，一個 migration 檔）。

**`assets` bucket 沒設 `file_size_limit`**（`supabase/migrations/20260830000002_core_storage_assets_bucket.sql`）：
上傳端已擋兩道 50MB（`app/brand_web/routes_library.py:57`／`:79`／`:273`），這是第二道防線不是沒有防線。
補一行要開新 migration 檔，照憲法第 9 條先提計畫等批准，不算順手。
