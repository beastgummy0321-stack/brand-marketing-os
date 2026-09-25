-- ads: F31-I13 -- "does another org hold this platform id in the ads center?", answered on a
-- tenant-scoped connection.
--
-- `app.ads.external_owner.owned_by_another_org` (registered into the Meta parent-id guard) used
-- a plain SELECT over `ads_campaign` / `ads_delivery_group` / `ads_ad` (`external_id`) and
-- `ads_external_entity` (`platform = 'meta'`, `native_id`). All four carry org-isolation RLS, and
-- every API request and scoped job runs `db.set_tenant_scope` (role `authenticated`), so other
-- orgs' rows were invisible and the guard never refused outside unscoped test connections
-- (measured by F31-I03, 2026-09-26).
--
-- Any recorded id counts, whatever its `local_state`: a detached or retired row still names an
-- object living in that org's ad account. Returns only a boolean -- never rows, ids or org ids.
--
-- `SECURITY DEFINER` with a pinned search_path, built from `current_schema()` with `pg_temp`
-- named LAST -- same shape and reasons as 20260902000003_core_vault_org_scoped_access.sql.
-- EXECUTE: revoked from PUBLIC and anon, granted to `authenticated`.

DO $do$
DECLARE
    sch text := current_schema();
BEGIN
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.ads_external_id_owned_elsewhere(
            p_external_id text, p_org_id text
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        -- pg_temp named last: a temp table must never shadow the real ones (see header).
        SET search_path = %1$I, pg_temp
        AS $body$
            SELECT EXISTS (
                SELECT 1 FROM ads_campaign
                 WHERE external_id = p_external_id AND org_id <> p_org_id
                UNION ALL
                SELECT 1 FROM ads_delivery_group
                 WHERE external_id = p_external_id AND org_id <> p_org_id
                UNION ALL
                SELECT 1 FROM ads_ad
                 WHERE external_id = p_external_id AND org_id <> p_org_id
                UNION ALL
                SELECT 1 FROM ads_external_entity
                 WHERE platform = 'meta' AND native_id = p_external_id AND org_id <> p_org_id
            );
        $body$;
    $fn$, sch);
    EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION %I.ads_external_id_owned_elsewhere(text, text)'
        ' FROM PUBLIC, anon', sch);
    EXECUTE format(
        'GRANT EXECUTE ON FUNCTION %I.ads_external_id_owned_elsewhere(text, text)'
        ' TO authenticated', sch);
END
$do$;
