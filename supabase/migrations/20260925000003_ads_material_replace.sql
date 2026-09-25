-- F29-I06 (Contract H): a material request can name the ad it replaces and can be cancelled.
-- A cancelled task stays readable (history, workbench pack origin link); it only leaves the list.
ALTER TABLE ads_material_task
  ADD COLUMN replaces_entity_id text,
  ADD COLUMN cancelled_at timestamptz,
  ADD COLUMN cancelled_by text;

-- One open "replace this ad" request per ad entity; a cancelled one frees the slot.
CREATE UNIQUE INDEX ads_material_task_open_replace
  ON ads_material_task(org_id,brand_id,campaign_id,replaces_entity_id)
  WHERE replaces_entity_id IS NOT NULL AND cancelled_at IS NULL;
