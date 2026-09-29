-- supabase/migrations/20260929000011_ads_asset_placement_per_ad.sql
-- Module: ads (F40-I02, drill-7 #6). One brand original may back several planned ads, each with
-- its own copy: a placement is now unique per (campaign, asset, ad) instead of per
-- (campaign, asset). `ad_id` is the planned ad whose slot the file was uploaded into
-- (`app/ads/slots.py::upload` passes it); a library attach through
-- `POST …/campaigns/{c}/placements` (`user_assets_repository.attach`, the default) writes NULL,
-- and every row from before this migration keeps NULL. Under Postgres NULL semantics two rows
-- with `ad_id IS NULL` never collide on the unique index, so library attaches stay distinct
-- from slot uploads and from each other; the reader `attach` looks the current row up with
-- `ad_id IS NOT DISTINCT FROM %s` so the same ad with different copy is still a conflict.
-- ON DELETE SET NULL: a deleted planned ad leaves its placement history readable as a library row.

ALTER TABLE ads_asset_placement ADD COLUMN ad_id text REFERENCES ads_ad(id) ON DELETE SET NULL;
DROP INDEX ads_asset_placement_current;
CREATE UNIQUE INDEX ads_asset_placement_current
  ON ads_asset_placement(org_id,brand_id,campaign_id,asset_id,ad_id) WHERE is_current;
