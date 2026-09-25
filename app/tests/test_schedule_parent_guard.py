"""app/tests/test_schedule_parent_guard.py — F31-I13: the Meta parent-id guard refuses an id
another org bound in `channel_entity_map`, on a tenant-scoped (request-shaped) connection.

Every API request and scoped job runs `db.set_tenant_scope` (role `authenticated`, org-isolation
RLS), so a plain SELECT on `channel_entity_map` never sees another org's row. The guard
(`app.meta.repository._refuse_if_parent_owned_by_another_org`) asks the schedule module's
SECURITY DEFINER boolean lookup `schedule_channel_entity_owned_elsewhere` instead. The ads-center
half of the guard is `test_ads_parent_guard.py`; the unscoped case is
`test_meta_daily_spend.AdSetParentCrossOrgRefusedTest`.
"""

import unittest
from unittest import mock
from uuid import uuid4

import app.shared.web as web
from app.core import db
from app.meta import graph
from app.meta import repository as meta_repo

TOKEN = "EAAtest-fake-meta-token-schedule-parent-guard"


def _make_org(suffix: str) -> str:
    org_id = f"org_sched_guard_{suffix}_{uuid4().hex[:8]}"
    web.conn.execute(
        "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')",
        (org_id, org_id),
    )
    return org_id


class ScopedChannelEntityParentGuardTest(unittest.TestCase):
    def setUp(self):
        self.org_a = _make_org("a")
        self.org_b = _make_org("b")
        meta_repo.save_token(web.conn, self.org_a, TOKEN)
        # Rows commit and outlive each test: a fresh id per test keeps them apart.
        self.mapped_id = f"camp-map-b-{uuid4().hex[:8]}"
        brand_b = f"brd_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO brand (id, org_id, name, status) VALUES (%s, %s, 'B 的品牌', 'active')",
            (brand_b, self.org_b),
        )
        channel_id = db.new_id("adch")
        web.conn.execute(
            "INSERT INTO ad_channel (id, org_id, channel_key, enabled)"
            " VALUES (%s, %s, 'meta', true)",
            (channel_id, self.org_b),
        )
        web.conn.execute(
            "INSERT INTO channel_entity_map (id, org_id, brand_id, channel_id, node_key,"
            " node_name_at_bind, external_id, external_status)"
            " VALUES (%s, %s, %s, %s, '1', 'B 的節點', %s, 'ACTIVE')",
            (db.new_id("cem"), self.org_b, brand_b, channel_id, self.mapped_id),
        )
        web.conn.commit()

    def _scoped(self, org_id, call):
        with db.connection() as conn:
            db.set_tenant_scope(conn, org_id)
            try:
                # Precondition: RLS really hides other orgs' rows here, so a refusal below is
                # the SECURITY DEFINER lookup at work, not an unscoped connection.
                hidden = conn.execute(
                    "SELECT count(*) AS n FROM channel_entity_map"
                    " WHERE external_id = %s AND org_id <> %s",
                    (self.mapped_id, org_id),
                ).fetchone()
                self.assertEqual(hidden["n"], 0, "RLS must hide other orgs' rows here")
                return call(conn)
            finally:
                conn.rollback()
                conn.execute("RESET ROLE")
                conn.execute("RESET app.org_id")
                conn._tenant_org_id = None
                conn.commit()  # pooled connection must not go back scoped

    def test_other_orgs_binding_refused_on_scoped_connection(self):
        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                self._scoped(self.org_a, lambda conn: meta_repo.ad_set_ids_by_exact_name(
                    conn, self.org_a, self.mapped_id, "隨便什麼名字",
                ))
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "campaign_not_owned")

    def test_own_binding_passes_on_scoped_connection(self):
        meta_repo.save_token(web.conn, self.org_b, TOKEN)
        web.conn.commit()
        with mock.patch.object(graph, "list_ad_sets", return_value=[]) as fake_list_ad_sets:
            self._scoped(self.org_b, lambda conn: meta_repo.ad_set_ids_by_exact_name(
                conn, self.org_b, self.mapped_id, "隨便什麼名字",
            ))
        self.assertEqual(fake_list_ad_sets.call_count, 1)


if __name__ == "__main__":
    unittest.main()
