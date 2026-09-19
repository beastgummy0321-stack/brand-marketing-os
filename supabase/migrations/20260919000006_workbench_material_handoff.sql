-- A prepared upstream task has not requested a model call yet.
ALTER TABLE workbench_brief DROP CONSTRAINT workbench_brief_status_check;
ALTER TABLE workbench_brief ADD CONSTRAINT workbench_brief_status_check
 CHECK(status IN ('idle','queued','running','done','failed','closed'));
