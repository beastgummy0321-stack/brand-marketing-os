"""app/tests/test_rls_tenant_policy.py — R1 RLS tracer: prove the policy shape on one table.

`supabase/migrations/20260828000001_core_rls.sql` (ADR 0027 decision 9) turned RLS on for
every `public` table with zero policies. `20260902000001_core_rls_brand_policy.sql` writes
the first one: `brand`, granted only to role `authenticated`, keyed on the `app.org_id` GUC.

This test proves that policy live, with a real `SET ROLE authenticated` on a role that does
not bypass RLS (`postgres` does, so inserts here are done as `postgres` — the policy would
never engage otherwise). It does not touch `require_actor()`, the connection pool, or any
route; wiring the role switch into live requests is R3's job (docs/issues/r1-rls-tracer/ticket.md).
"""

import unittest

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


if __name__ == "__main__":
    unittest.main()
