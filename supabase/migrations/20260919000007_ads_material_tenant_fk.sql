-- Retain composite task ownership while making the direct tenant dependency explicit.
ALTER TABLE ads_material_revision
 ADD CONSTRAINT ads_material_revision_org_fk FOREIGN KEY(org_id) REFERENCES organisation(id);
ALTER TABLE ads_material_operation
 ADD CONSTRAINT ads_material_operation_org_fk FOREIGN KEY(org_id) REFERENCES organisation(id);
