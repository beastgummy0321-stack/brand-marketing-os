-- Drill-4 ruling RC-C, built in F38: promo offers are a brand's choice, not a default.
-- Switch every brand's promo offer coordinates off once (all brands: test data, the system is
-- unpublished). Only `offer/none` stays enabled; brands re-enable real offers in the
-- coordinate screen. New brands get the same state from `ensure_coordinates_seeded`.
UPDATE brand_coordinate
   SET disabled_at = now()
 WHERE dimension = 'offer'
   AND key <> 'none'
   AND disabled_at IS NULL;
