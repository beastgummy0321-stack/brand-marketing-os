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
or any route; wiring the role switch into live requests is R3b's job.
"""

import unittest
from uuid import uuid4

from app.core import db


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


if __name__ == "__main__":
    unittest.main()
