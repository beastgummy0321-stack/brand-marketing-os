-- F30-I10 Contract F: a file uploaded into one planned ad's slot waits here (the placement id,
-- following its revisions) until the placement is confirmed; only then is it assigned through
-- material_placement_id/_revision, which keep pointing at confirmed versions only.
-- No foreign key: a placement is keyed by (id, revision); the pointer follows the id.
ALTER TABLE ads_ad ADD COLUMN slot_placement_id text;
