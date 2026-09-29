-- supabase/migrations/20260929000010_ads_ad_scene.sql
-- Module: ads (F39-I03, outcome 3 of the drill-7 dig). Every planned ad carries one scene:
-- the concrete moment its copy happens in (who, where, doing what), one sentence of 6–60
-- characters chosen by the delivery-plan model and validated in `app/ads/plan.py`. Ads for
-- different audiences inside one campaign must carry different scenes. Nullable: hand-made ads
-- (`plan.create_ad`) and rows from before this migration have none. Reader: `assets._ad_set`
-- hands it to the workbench brief as `request.scene`, where the copy prompt makes the copy
-- happen in that scene. Not a key inside `coordinates_snapshot_json` (that json is the
-- vocabulary snapshot).

ALTER TABLE ads_ad ADD COLUMN scene text;
