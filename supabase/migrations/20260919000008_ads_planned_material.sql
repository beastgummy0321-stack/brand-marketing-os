-- An explicit local assignment; never an external ad identity or publication claim.
ALTER TABLE ads_ad ADD COLUMN material_placement_id text;
ALTER TABLE ads_ad ADD COLUMN material_placement_revision integer;
ALTER TABLE ads_ad ADD CONSTRAINT ads_ad_material_pair CHECK (
 (material_placement_id IS NULL AND material_placement_revision IS NULL)
 OR (material_placement_id IS NOT NULL AND material_placement_revision IS NOT NULL
     AND material_placement_revision > 0)
);
ALTER TABLE ads_ad ADD CONSTRAINT ads_ad_material_scope FOREIGN KEY
 (org_id,brand_id,campaign_id,material_placement_id,material_placement_revision)
 REFERENCES ads_asset_placement(org_id,brand_id,campaign_id,id,revision);
