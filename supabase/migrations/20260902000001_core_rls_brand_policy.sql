-- core: R1 RLS tracer slice (docs/issues/r1-rls-tracer/ticket.md).
-- 20260828000001_core_rls.sql turned RLS on for every public table with zero policies
-- (ADR 0027 decision 9). This is the first policy: one table (brand), one role
-- (authenticated, not anon, not PUBLIC), keyed on the `app.org_id` GUC. It proves the
-- shape before R3 writes it 45 more times and wires the GUC into live requests.
--
-- Not done here (out of ceiling): FORCE ROW LEVEL SECURITY (authenticated is not the table
-- owner, so the policy already applies to it without forcing — forcing changes postgres's
-- own behaviour, which is R3's decision), and touching require_actor() or the connection pool.

-- Grants authenticated needs for the policy to be reachable at all. Supabase's default
-- privileges already grant these on the real `public` schema, but the per-module test
-- schemas (t_<module>_<pid>, app/tests/conftest.py) get none, and this file is replayed into
-- both — so grant against current_schema() rather than a hard-coded `public`.
DO $$
BEGIN
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO authenticated', current_schema());
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I.brand TO authenticated', current_schema());
END
$$;

-- Re-runnable: conftest.py may replay this file into a schema where it already ran.
DROP POLICY IF EXISTS brand_org_isolation ON brand;

CREATE POLICY brand_org_isolation ON brand
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
