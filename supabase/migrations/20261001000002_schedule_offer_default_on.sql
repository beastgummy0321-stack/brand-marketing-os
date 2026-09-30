-- Module: schedule. Ticket: F42-I01 (feature F42, decision "offer availability").
--
-- Offers become derived data: a promo offer is usable only when a confirmed store policy
-- supports it (app.brand_intelligence.repository.available_offer_keys). The coordinate
-- toggle stays a brand veto (enabled ∩ available), so offers are seeded enabled again.
-- Undoes 20260929000003_schedule_offer_default_off.sql once (all brands: test data, the
-- system is unpublished). New brands get the same state from `ensure_coordinates_seeded`.
UPDATE brand_coordinate
   SET disabled_at = NULL
 WHERE dimension = 'offer'
   AND disabled_at IS NOT NULL;
