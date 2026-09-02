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

R3c (docs/issues/r3c-rls-switch/ticket.md, ADR 0052) flips the switch: `db.set_tenant_scope()`
now runs from `require_actor()` on every logged-in request, so every caller *is* scoped from
here on. `SetTenantScopeTest`, `PoolResetTest` and `TenantScopedRequestIsolationTest` below
cover that: the switch itself, the two silent-failure guards named in the ticket (a rollback
that catches the switch before its own commit lands, and a pooled connection that must not
leak one request's org into the next), and one real HTTP round trip proving org A cannot read
org B's data through an existing route.
"""

import unittest
from unittest import mock
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

import app.main as main
from app.core import db, settings
from app.core.db import Conn

from .identity_test_helpers import mint_hs256


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
        """Pins the branch that keeps an unscoped caller working: `app/identity/` never
        calls `require_actor()`/`set_tenant_scope()` (ADR 0052's identity section) and so
        never carries a claim, and the read must still succeed exactly as the direct
        `vault.decrypted_secrets` query it replaces did.

        R3c's `pool()` reset= callback (`app/core/db.py:_reset_pooled_connection`) now
        clears role and claim on every connection returned to the pool, so a connection
        arriving here is already guaranteed unscoped — this test no longer needs its own
        `RESET app.org_id` workaround before the read (R3c ticket item 5: that residue is
        now fixed at its source; keeping a second, redundant clear here would be two
        mechanisms doing one job)."""
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


class SetTenantScopeTest(unittest.TestCase):
    """R3c (ADR 0052): `db.set_tenant_scope()` is what `require_actor()` now calls on
    every logged-in request."""

    def test_set_tenant_scope_switches_role_and_sets_the_claim(self):
        conn = db.current()
        org_a = db.new_id("org")

        db.set_tenant_scope(conn, org_a)
        try:
            row = conn.execute(
                "SELECT current_user AS u, current_setting('app.org_id', true) AS c"
            ).fetchone()
            self.assertEqual(
                (row["u"], row["c"]),
                ("authenticated", org_a),
                "set_tenant_scope must switch role to authenticated and set the org claim",
            )
        finally:
            conn.execute("RESET ROLE")
            conn.execute("RESET app.org_id")
            conn.commit()  # pooled connection must not go back poisoned or mid-transaction

    def test_rollback_after_set_tenant_scope_still_holds_the_scope(self):
        """ADR 0052 clause 5, first measured fact: a `SET ROLE` issued inside a
        transaction that is then rolled back is undone. `set_tenant_scope()`'s own
        commit protects its *own* switch against any later, separate rollback (the
        clause's second measured fact) — but nothing stops a rollback from catching
        the switch *before* that commit lands (e.g. the commit is skipped or delayed
        for any reason), which is exactly the silent-failure hole `Conn.rollback()`'s
        re-apply exists to close.

        Reproduced directly rather than assumed: `Conn.commit` is intercepted for one
        `set_tenant_scope()` call so its `SET ROLE`/claim for org B are still part of
        an open transaction — stacked on top of an already-committed org A baseline —
        when `rollback()` runs. Without the re-apply, Postgres's own rollback reverts
        to the last *committed* value (org A); this proves `Conn.rollback()` instead
        re-asserts the org `set_tenant_scope()` actually recorded (org B), not
        whatever the raw rollback happened to leave behind.
        """
        conn = db.current()
        org_a = db.new_id("org")
        org_b = db.new_id("org")

        try:
            db.set_tenant_scope(conn, org_a)  # committed baseline

            with mock.patch.object(Conn, "commit", lambda self: None):
                db.set_tenant_scope(conn, org_b)  # SET ROLE/claim for org B, never committed

            conn.rollback()
            row = conn.execute(
                "SELECT current_user AS u, current_setting('app.org_id', true) AS c"
            ).fetchone()
            self.assertEqual(
                (row["u"], row["c"]),
                ("authenticated", org_b),
                "rollback must re-apply the scope set_tenant_scope last recorded (org B), "
                "not silently fall back to org A or drop the switch entirely",
            )
        finally:
            conn.execute("RESET ROLE")
            conn.execute("RESET app.org_id")
            conn.commit()  # pooled connection must not go back poisoned or mid-transaction


class PoolResetTest(unittest.TestCase):
    def test_pool_reset_clears_role_and_claim_on_reuse(self):
        """ADR 0052 clause 4 / R3c ticket item 3 and its contradiction check:
        `db.pool()` runs `min_size=1, max_size=10`, and a naive "borrow, scope,
        return, borrow again" on it does *not* reliably reuse the same physical
        connection — measured on this machine: the pool grows a second connection
        instead of waiting for the `reset=` callback's async return of the first one,
        so such a test would pass even with the callback removed (green for the wrong
        reason).

        A dedicated pool with `max_size=1` makes reuse deterministic by construction
        (there is only ever one physical connection to hand back) — measured: 5/5
        trials reused the same backend pid. It is built with the *actual* callback
        `db.pool()` is wired with (`db.pool()._reset`, not a hand-written duplicate),
        so removing `reset=` from `pool()`'s own construction still fails this test.
        """
        real_reset = db.pool()._reset
        test_pool = ConnectionPool(
            db.dsn(),
            min_size=1,
            max_size=1,
            reset=real_reset,
            open=True,
        )
        try:
            org_a = db.new_id("org")

            with test_pool.connection() as pg_conn:
                pid1 = pg_conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                pg_conn.execute("SET ROLE authenticated")
                pg_conn.execute("SELECT set_config('app.org_id', %s, false)", (org_a,))
                pg_conn.commit()

            with test_pool.connection() as pg_conn:
                pid2 = pg_conn.execute("SELECT pg_backend_pid()").fetchone()[0]
                row = pg_conn.execute(
                    "SELECT current_user, current_setting('app.org_id', true)"
                ).fetchone()
        finally:
            test_pool.close()

        self.assertEqual(
            pid1, pid2, "test only proves anything if the same physical connection is reused"
        )
        self.assertEqual(
            row,
            ("postgres", ""),
            "a connection returned to the pool must not hand the next borrower the "
            "previous request's role or org claim",
        )


class TenantScopedRequestIsolationTest(unittest.TestCase):
    """R3c end-to-end: `require_actor()` now calls `set_tenant_scope()` on every one of
    the 133 authenticated routes, not just the raw-SQL probes above. Proves it through
    one real HTTP round trip on an existing route (`GET /api/dashboard/brands/{id}/month`,
    `app/dashboard/routes.py`) rather than inventing a new one, per the ticket."""

    def test_request_authenticated_as_org_a_cannot_read_org_bs_brand(self):
        conn = db.current()

        org_a = db.new_id("org")
        org_b = db.new_id("org")
        brand_a = db.new_id("brd")
        brand_b = db.new_id("brd")
        user_a = uuid4()

        # As postgres (bypasses RLS): two orgs, each with a brand, and a user who is a
        # member of org A only.
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_a, "R3c tracer org A"),
        )
        conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'company')",
            (org_b, "R3c tracer org B"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_a, org_a, "R3c tracer brand A"),
        )
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, %s, 'active')",
            (brand_b, org_b, "R3c tracer brand B"),
        )
        conn.execute(
            "INSERT INTO app_user (id, email) VALUES (%s, %s)",
            (str(user_a), f"r3c-tracer-{user_a.hex[:8]}@example.com"),
        )
        conn.execute(
            "INSERT INTO membership (org_id, user_id, role) VALUES (%s, %s, 'owner')",
            (org_a, str(user_a)),
        )
        # The HTTP request below borrows a *different* connection from the same pool
        # (app/main.py's _db_connection_middleware) — READ COMMITTED only sees this
        # seed once it is committed.
        conn.commit()

        token = mint_hs256(sub=str(user_a))
        client = TestClient(main.app)
        resp = client.get(
            f"/api/dashboard/brands/{brand_b}/month",
            headers={"Authorization": f"Bearer {token}", "X-Org-Id": org_a},
        )
        self.assertEqual(
            resp.status_code,
            404,
            "a request authenticated as org A must not read org B's brand data",
        )

        # The 404 above is NOT evidence that RLS works. It comes from `require_brand`
        # (`app/shared/web.py:226`), which compares `org_id` in Python and would return
        # the same 404 with RLS switched off entirely — the reviewer of this ticket
        # demonstrated exactly that. RLS is the *second* lock (ADR 0052, "why this is a
        # second lock, not the front door"), so it has to be asserted where the first
        # lock is not standing in front of it: raw SQL on a scoped connection.
        scoped = db.current()
        db.set_tenant_scope(scoped, org_a)
        try:
            rows = scoped.execute(
                "SELECT id FROM brand WHERE id = %s", (brand_b,)
            ).fetchall()
            self.assertEqual(
                [r["id"] for r in rows],
                [],
                "scoped to org A, org B's brand row must not be visible at all — this is "
                "the assertion that goes red if the policy or the role switch stops working",
            )
        finally:
            scoped.execute("RESET ROLE")
            scoped.execute("RESET app.org_id")
            scoped._tenant_org_id = None
            scoped.commit()


if __name__ == "__main__":
    unittest.main()
