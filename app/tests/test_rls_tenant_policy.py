"""app/tests/test_rls_tenant_policy.py — R1 RLS tracer, extended by R3a to every table.

`supabase/migrations/20260828000001_core_rls.sql` (ADR 0027 decision 9) turned RLS on for
every `public` table with zero policies. `20260902000001_core_rls_brand_policy.sql` (R1)
wrote the first one: `brand`, granted only to role `authenticated`, keyed on the
`app.org_id` GUC. `20260902000002_core_rls_all_tenant_policies.sql` (R3a,
docs/issues/r3a-rls-policies/ticket.md, ADR 0052) writes the same shape for the other 44
`org_id` tables via a loop, plus `organisation` and `app_user`, which have no `org_id` and
get a different rule each.

Every test here proves a policy live, with a real `SET ROLE authenticated` on a role that
does not bypass RLS (`postgres` does, so seed inserts are done as `postgres` — the policy
would never engage otherwise). None of this touches `require_actor()`, the connection pool,
or any route; wiring the role switch into live requests is R3c's job.

`20260902000003_core_vault_org_scoped_access.sql` (R3b, docs/issues/r3b-vault-org-door/
ticket.md, ADR 0052) adds the one door into Supabase Vault: three `SECURITY DEFINER`
functions granted to `authenticated`, each checking the secret id belongs to the caller's
own org — but only when a claim is present, since every caller today still runs unscoped.
`VaultOrgScopedAccessTest` below proves both halves of that.
"""

import unittest
from uuid import uuid4

import psycopg

from app.core import db, settings


class RlsTenantPolicyTest(unittest.TestCase):
    def test_authenticated_sees_only_its_org_claim(self):
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")
        brand_a = db.new_id("brd")
        brand_b = db.new_id("brd")

        # As postgres (bypasses RLS): seed two orgs, one brand row under each.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R1 tracer org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R1 tracer org B"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_a, org_a, "R1 tracer brand A"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_b, org_b, "R1 tracer brand B"),
        )

        conn.execute("SET ROLE authenticated")
        try:
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            seen = {row["id"] for row in conn.execute("SELECT id FROM brand")}
            self.assertEqual(seen, {brand_a}, "org A's claim must see exactly org A's brand")

            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_b,))
            seen = {row["id"] for row in conn.execute("SELECT id FROM brand")}
            self.assertEqual(seen, {brand_b}, "org B's claim must see exactly org B's brand")

            conn.execute("RESET app.org_id")
            seen = {row["id"] for row in conn.execute("SELECT id FROM brand")}
            self.assertEqual(seen, set(), "an unset claim must see zero rows of either org")
        finally:
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned


class RlsPolicyRatchetTest(unittest.TestCase):
    """R2: every `org_id` table must carry at least one policy scoped to `authenticated`.

    No frozen list, no exemption set — the R3a migration fixes all 45 in the same commit,
    so this ships with nothing excused. A future table without a policy is a defect.
    """

    def test_every_org_table_has_an_authenticated_policy(self):
        conn = db.current()

        org_tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT c.table_name FROM information_schema.columns c"
                " JOIN information_schema.tables t"
                "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
                "   AND t.table_type = 'BASE TABLE'"
                " WHERE c.table_schema = current_schema() AND c.column_name = 'org_id'"
            )
        }
        policy_rows = conn.execute(
            "SELECT tablename, roles FROM pg_policies WHERE schemaname = current_schema()"
        )
        covered = {row["tablename"] for row in policy_rows if "authenticated" in row["roles"]}

        missing = sorted(org_tables - covered)
        self.assertEqual(missing, [], f"org_id tables without an authenticated policy: {missing}")


class OrganisationRlsIsolationTest(unittest.TestCase):
    def test_authenticated_sees_only_its_own_organisation_row(self):
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")

        # As postgres (bypasses RLS): seed two orgs.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3a tracer org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R3a tracer org B"),
        )

        conn.execute("SET ROLE authenticated")
        try:
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            seen = {row["id"] for row in conn.execute("SELECT id FROM organisation")}
            self.assertEqual(
                seen & {org_a, org_b},
                {org_a},
                "org A's claim must see exactly org A's organisation row and none of org B's",
            )
        finally:
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned


class AppUserRlsIsolationTest(unittest.TestCase):
    def test_authenticated_sees_only_users_with_membership_in_its_org(self):
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")
        user_a = str(uuid4())
        user_b = str(uuid4())

        # As postgres (bypasses RLS): two orgs, one user each, one membership each.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3a tracer org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R3a tracer org B"),
        )
        conn.execute(
            "INSERT INTO app_user (id, email) VALUES (%s, %s)",
            (user_a, "r3a-tracer-a@example.com"),
        )
        conn.execute(
            "INSERT INTO app_user (id, email) VALUES (%s, %s)",
            (user_b, "r3a-tracer-b@example.com"),
        )
        conn.execute(
            "INSERT INTO membership (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_a, user_a),
        )
        conn.execute(
            "INSERT INTO membership (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_b, user_b),
        )

        conn.execute("SET ROLE authenticated")
        try:
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            seen = {str(row["id"]) for row in conn.execute("SELECT id FROM app_user")}
            self.assertEqual(
                seen & {user_a, user_b},
                {user_a},
                "org A's claim must see only the user holding a membership in org A",
            )
        finally:
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned


class VaultOrgScopedAccessTest(unittest.TestCase):
    """R3b: `core_vault_read_secret` only ever hands back a secret belonging to the
    caller's own org — and, until R3c flips the switch, an unset claim is a no-op so today's
    unscoped callers see no behaviour change."""

    def test_read_secret_is_scoped_to_the_claimed_org(self):
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")

        # As postgres (bypasses RLS): seed two orgs, each saving its own AI key through the
        # app's own save path (settings.save_api_key -> core_vault_save_secret), not by
        # writing vault.secrets directly.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3b tracer org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R3b tracer org B"),
        )
        settings.save_api_key(conn, "sk-r3b-tracer-a", org_id=org_a)
        settings.save_api_key(conn, "sk-r3b-tracer-b", org_id=org_b)
        secret_a = settings.get_setting(conn, settings.API_KEY_SECRET_ID_SETTING, org_id=org_a)
        secret_b = settings.get_setting(conn, settings.API_KEY_SECRET_ID_SETTING, org_id=org_b)

        conn.execute("SET ROLE authenticated")
        try:
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            row = conn.execute(
                "SELECT core_vault_read_secret(%s) AS v", (secret_a,)
            ).fetchone()
            self.assertEqual(
                row["v"], "sk-r3b-tracer-a", "org A's claim must read org A's own secret"
            )

            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT core_vault_read_secret(%s) AS v", (secret_b,))
        finally:
            # The raise above leaves the transaction aborted; rollback clears it and, since
            # SET ROLE / set_config(..., false) are both transactional (ADR 0052 clause 5),
            # also reverts role and claim before the connection goes back to the pool.
            conn.rollback()
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned

    def test_read_secret_with_no_claim_is_unchanged_no_op_behaviour(self):
        """Pins the branch that keeps this ticket a no-op: every caller today runs with no
        `app.org_id` claim at all (R3c hasn't flipped the switch), and the read must still
        succeed exactly as the direct `vault.decrypted_secrets` query it replaces did."""
        conn = db.current()

        org_a = db.new_id("org")
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3b tracer org A, no claim"),
        )
        settings.save_api_key(conn, "sk-r3b-tracer-noclaim", org_id=org_a)
        secret_a = settings.get_setting(conn, settings.API_KEY_SECRET_ID_SETTING, org_id=org_a)

        conn.execute("SET ROLE authenticated")
        try:
            # The pooled connection is shared across this file's tests and nothing before
            # this one is required to clear app.org_id (only its own RESET ROLE, matching
            # this file's existing convention) — reset it explicitly so "no claim" is
            # actually true, not just "not set by this test".
            conn.execute("RESET app.org_id")
            row = conn.execute(
                "SELECT core_vault_read_secret(%s) AS v", (secret_a,)
            ).fetchone()
            self.assertEqual(
                row["v"], "sk-r3b-tracer-noclaim", "an unset claim must not block the read"
            )
        finally:
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned

    def test_read_secret_ownership_check_survives_a_shadow_temp_table(self):
        """R3b round 2 (docs/issues/r3b-vault-org-door/ticket.md ## Blocked): an unpinned
        `search_path` on a `SECURITY DEFINER` function is a privilege escalation, because
        Postgres searches `pg_temp` first unless `pg_temp` is named explicitly in the path.
        An authenticated caller could shadow `app_setting` with a session-local temp table,
        seed it claiming ownership of another org's secret, and have the ownership check
        inside the function read the fake row instead of the real table. Reproduced live
        against `public` before this fix (see the ticket's ## Blocked section)."""
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")

        # As postgres (bypasses RLS): seed two orgs, each saving its own AI key through the
        # app's own save path, not by writing vault.secrets directly.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3b shadow-attack org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R3b shadow-attack org B"),
        )
        settings.save_api_key(conn, "sk-r3b-shadow-a", org_id=org_a)
        settings.save_api_key(conn, "sk-r3b-shadow-b", org_id=org_b)
        secret_b = settings.get_setting(conn, settings.API_KEY_SECRET_ID_SETTING, org_id=org_b)

        conn.execute("SET ROLE authenticated")
        try:
            # Claim org A, then shadow app_setting with a temp table claiming org A owns
            # org B's secret. A search_path that does not name pg_temp resolves the
            # function's unqualified `app_setting` to this temp table first.
            conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
            conn.execute("CREATE TEMP TABLE app_setting (org_id text, key text, value text)")
            conn.execute(
                "INSERT INTO app_setting (org_id, key, value) VALUES (%s, %s, %s)",
                (org_a, settings.API_KEY_SECRET_ID_SETTING, secret_b),
            )

            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT core_vault_read_secret(%s) AS v", (secret_b,))
        finally:
            # The raise above leaves the transaction aborted; rollback clears it (and, per
            # ADR 0052 clause 5, reverts role/claim too) — this also undoes the CREATE TEMP
            # TABLE, since DDL is transactional. The explicit DROP is a defensive no-op for
            # that expected case and a real cleanup for any other: the temp table dies with
            # the session, but the pooled connection outlives this test.
            conn.rollback()
            conn.execute("DROP TABLE IF EXISTS pg_temp.app_setting")
            conn.execute("RESET ROLE")  # pooled connection must not go back poisoned


if __name__ == "__main__":
    unittest.main()
