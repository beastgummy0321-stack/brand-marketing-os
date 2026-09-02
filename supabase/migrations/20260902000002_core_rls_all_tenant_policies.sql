-- core: R3a — a policy and CRUD grants on every table, still dormant
-- (docs/issues/r3a-rls-policies/ticket.md, ADR 0052).
--
-- 20260828000001_core_rls.sql turned RLS on for every public table with zero policies.
-- 20260902000001_core_rls_brand_policy.sql (R1) wrote the first policy, on one table
-- (brand), to prove the shape. This file writes it for the other 44 org_id tables via a
-- loop over current_schema() (this file is replayed into every t_<module>_<pid> test
-- schema by app/tests/conftest.py, so nothing here may hard-code "public"), plus the two
-- tables without org_id — organisation and app_user — written out by hand because their
-- rule is different. The loop also covers `brand` again, producing the identical policy
-- name (`brand_org_isolation`) so it is re-runnable over R1's migration rather than a
-- duplicate.
--
-- Not done here (ADR 0052 clause 6, measured): FORCE ROW LEVEL SECURITY. `postgres` carries
-- BYPASSRLS, and FORCE only removes the table owner's own exemption, so it would change
-- nothing. Not done here either: touching require_actor() or the connection pool — this
-- migration is dormant until R3b flips the switch (app still connects as postgres today).

DO $$
DECLARE
    tbl text;
BEGIN
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO authenticated', current_schema());

    FOR tbl IN
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = current_schema()
          AND t.table_type = 'BASE TABLE'
          AND c.column_name = 'org_id'
        ORDER BY c.table_name
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO authenticated', tbl);
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', tbl || '_org_isolation', tbl);
        EXECUTE format(
            'CREATE POLICY %I ON %I'
            ' FOR ALL TO authenticated'
            ' USING (org_id = current_setting(''app.org_id'', true))'
            ' WITH CHECK (org_id = current_setting(''app.org_id'', true))',
            tbl || '_org_isolation', tbl
        );
    END LOOP;
END
$$;

-- organisation has no org_id — it *is* the tenant boundary; a row doesn't belong to itself.
GRANT SELECT, INSERT, UPDATE, DELETE ON organisation TO authenticated;
DROP POLICY IF EXISTS organisation_org_isolation ON organisation;
CREATE POLICY organisation_org_isolation ON organisation
    FOR ALL TO authenticated
    USING (id = current_setting('app.org_id', true))
    WITH CHECK (id = current_setting('app.org_id', true));

-- app_user has no org_id — a user spans orgs, so the boundary lives in membership.
GRANT SELECT, INSERT, UPDATE, DELETE ON app_user TO authenticated;
DROP POLICY IF EXISTS app_user_org_isolation ON app_user;
CREATE POLICY app_user_org_isolation ON app_user
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM membership m
            WHERE m.user_id = app_user.id AND m.org_id = current_setting('app.org_id', true)
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM membership m
            WHERE m.user_id = app_user.id AND m.org_id = current_setting('app.org_id', true)
        )
    );
