-- app/schedule owns brand_coordinate (ARCHITECTURE.md §3).
-- F07-I03: Meta no longer offers a "flexible" ad format; a delivery plan that still picks
-- `flexible` is a bug. Disable the existing seed for every brand instead of deleting the row
-- (`disabled_at` is the module's existing screen switch — see `ads_repo.coordinate_vocabulary`).
UPDATE brand_coordinate
   SET disabled_at = now(), updated_at = now()
 WHERE dimension = 'format' AND key = 'flexible' AND disabled_at IS NULL;
