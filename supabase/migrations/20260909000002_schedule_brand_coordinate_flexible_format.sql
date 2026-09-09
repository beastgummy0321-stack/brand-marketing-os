-- supabase/migrations/20260909000002_schedule_brand_coordinate_flexible_format.sql
-- Module: schedule (ADR 0049 -- schedule owns brand_coordinate). Ticket: workbench/06
-- (docs/issues/workbench/06-free-briefs-video-script-and-closing.md).
--
-- ADR 0068's "Numbers and their sources" table: the `format` coordinate dimension gains the
-- value 彈性格式 (flexible) -- 1-10 images at one coordinate, Meta's asset_feed_spec ceiling
-- (developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/asset-feed-spec/
-- options, verified 2026-09-09). `單圖 single_image` is not deleted (ADR 0068 decision, same
-- table). No table created, no column changed.
--
-- `ensure_coordinates_seeded()` (app/schedule/repository.py) probes per dimension and skips
-- `format` once any row of it already exists (it seeded 33 rows across six dimensions before
-- this ticket, ticket T8a) -- so a brand that already has `format` rows never gets this new value
-- from the lazy Python seed. This migration back-fills it once for every brand that already
-- exists, same shape as 20260904000002's own back-fill. Brands created after this migration get
-- it from `app/schedule/repository.py::_SEED_COORDINATES["format"]` (kept in sync by hand -- SQL
-- migrations cannot reference application code, per that file's own comment). `key`/`label` here
-- are transcribed character for character from that Python tuple -- a mismatch between the two
-- would leave the vocabulary with two spellings while every count-based done-check stays green.

INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label, category, attributes_json)
SELECT 'crd_' || replace(gen_random_uuid()::text, '-', ''), brand.org_id, brand.id, 'format',
       'flexible', '彈性格式', 'Meta 版位',
       jsonb_build_object('situation', '1～10 張同座標圖；asset_feed_spec images ≤10，2026-09-09 查證')
FROM brand
ON CONFLICT (brand_id, dimension, key) DO NOTHING;
