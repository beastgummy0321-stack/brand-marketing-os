-- schedule: F31-I13 -- "does another org hold this platform id in channel_entity_map?", answered
-- on a tenant-scoped connection.
--
-- `app.meta.repository._refuse_if_parent_owned_by_another_org` refuses a Meta parent id
-- (campaign / ad set) that another org bound, before any name match reaches Graph. It used a
-- plain `SELECT ... FROM channel_entity_map WHERE org_id <> caller`. Every API request and scoped
-- job runs `db.set_tenant_scope` (role `authenticated`, org-isolation RLS), so other orgs' rows
-- were invisible and the guard never refused outside unscoped test connections (measured by
-- F31-I03, 2026-09-26).
--
-- This function is owned by the schedule module (it owns `channel_entity_map`) and answers one
-- yes/no question. It returns only a boolean -- never rows, ids or org ids -- so the RLS-bypassing
-- read cannot leak another org's data beyond "someone else holds this id".
--
-- `SECURITY DEFINER` needs a pinned search_path. Same shape as
-- 20260902000003_core_vault_org_scoped_access.sql: the schema is not known at authoring time
-- (`app/tests/conftest.py` replays every migration into its own schema), so the function is
-- built with `EXECUTE format(...)` from `current_schema()`, and `pg_temp` is named LAST so a
-- caller's temp table can never shadow `channel_entity_map` (see that file's header).
--
-- EXECUTE: revoked from PUBLIC and anon, granted to `authenticated` (the role every request and
-- scoped worker job switches to). Unscoped connections run as the owner and need no grant.

DO $do$
DECLARE
    sch text := current_schema();
BEGIN
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.schedule_channel_entity_owned_elsewhere(
            p_external_id text, p_org_id text
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        -- pg_temp named last: a temp table must never shadow the real one (see header).
        SET search_path = %1$I, pg_temp
        AS $body$
            SELECT EXISTS (
                SELECT 1 FROM channel_entity_map
                 WHERE external_id = p_external_id
                   AND org_id <> p_org_id
            );
        $body$;
    $fn$, sch);
    EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION %I.schedule_channel_entity_owned_elsewhere(text, text)'
        ' FROM PUBLIC, anon', sch);
    EXECUTE format(
        'GRANT EXECUTE ON FUNCTION %I.schedule_channel_entity_owned_elsewhere(text, text)'
        ' TO authenticated', sch);
END
$do$;
