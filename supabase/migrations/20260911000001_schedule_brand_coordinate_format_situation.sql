-- app/schedule owns brand_coordinate (ARCHITECTURE.md §3).
-- The `situation` text for a format coordinate is printed verbatim into the 【輸出】 line of a
-- user-copied image prompt (ARCHITECTURE.md §5.7); the seeds for single_image/flexible carried
-- engineering provenance notes instead of user-facing text. `ensure_coordinates_seeded()` never
-- re-seeds a dimension that already exists for a brand, so brands seeded before this fix keep the
-- old strings until back-filled here.
UPDATE brand_coordinate
   SET attributes_json = jsonb_set(attributes_json, '{situation}', to_jsonb('4:5，1080×1350'::text))
 WHERE dimension = 'format' AND key = 'single_image';
UPDATE brand_coordinate
   SET attributes_json = jsonb_set(attributes_json, '{situation}', to_jsonb('1～10 張同座標圖'::text))
 WHERE dimension = 'format' AND key = 'flexible';
