-- app/ads/migrations/0016_theme_component_performance.sql
-- 主題元件層最新成效（票 12-attribution-adjust D 段）。
--
-- 精簡版：不開新表存歷史快照，直接在既有 creative_theme_component（0015_creative_theme.sql）
-- 加幾個欄位存「最新一次同步」的成效——規格書與使用者故事只要求同一主題內文案誰贏誰輸的
-- 當下相對排名，不需要時間序列。每次同步覆蓋舊值即可（app/ads/theme_attribution.py）。
--
-- 全部欄位 nullable：ALTER TABLE ADD COLUMN 對既有列一律補 NULL，向下相容既有資料。
ALTER TABLE creative_theme_component ADD COLUMN meta_asset_id TEXT;
ALTER TABLE creative_theme_component ADD COLUMN performance_impressions INTEGER;
ALTER TABLE creative_theme_component ADD COLUMN performance_clicks INTEGER;
ALTER TABLE creative_theme_component ADD COLUMN performance_conversions INTEGER;
ALTER TABLE creative_theme_component ADD COLUMN performance_synced_at TEXT;
