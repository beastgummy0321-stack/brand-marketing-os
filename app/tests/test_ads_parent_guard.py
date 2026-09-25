"""app/tests/test_ads_parent_guard.py — F31-I03 item 5: the Meta name-match parent guard also
refuses an id another org holds in the ads center.

`app.meta.repository._refuse_if_parent_owned_by_another_org` used to read only the schedule
module's `channel_entity_map`. The ads center keeps its bindings on its own rows, so an id org B
bound there reached Meta on org A's token. The fixtures write org B's rows directly (not through
`adapters/manual.bind`, which F31-I08 deletes). Ids nobody holds still reach Meta — that branch
is `test_meta_daily_spend.AdSetMatchUnreachableTest`, unchanged.
"""

import unittest
from unittest import mock
from uuid import uuid4

import app.ads  # noqa: F401 — the package import registers the ads owner check
import app.shared.web as web
from app.brand_intelligence import repository as brands
from app.core import db
from app.meta import graph
from app.meta import repository as meta_repo

TOKEN = "EAAtest-fake-meta-token-parent-guard"


def _make_org(suffix: str) -> str:
    org_id = f"org_parent_guard_{suffix}_{uuid4().hex[:8]}"
    web.conn.execute(
        "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')",
        (org_id, org_id),
    )
    return org_id


class AdsCenterParentGuardTest(unittest.TestCase):
    def setUp(self):
        self.org_a = _make_org("a")
        self.org_b = _make_org("b")
        meta_repo.save_token(web.conn, self.org_a, TOKEN)
        # Rows commit and outlive each test: a fresh id per test keeps one test's org B from
        # owning the next test's id.
        tail = uuid4().hex[:8]
        self.camp_id, self.adset_id = f"camp-ads-b-{tail}", f"adset-ads-b-{tail}"
        self.brand_b = brands.create_brand(
            web.conn, org_id=self.org_b, name="B 的品牌", client_name=None, actor="test",
        )["id"]
        self.campaign_b = db.new_id("adc")
        web.conn.execute(
            "INSERT INTO ads_campaign (id, org_id, brand_id, name, goal_text, objective,"
            " success_metric, external_id, local_state)"
            " VALUES (%s, %s, %s, 'B 的活動', '測試', 'purchase', 'cpa', %s, 'bound')",
            (self.campaign_b, self.org_b, self.brand_b, self.camp_id),
        )
        self.group_b = db.new_id("adg")
        web.conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key,"
            " name, role, daily_budget, external_id, local_state)"
            " VALUES (%s, %s, %s, %s, 'meta', 'B 的組', 'new', 100, %s, 'bound')",
            (self.group_b, self.org_b, self.brand_b, self.campaign_b, self.adset_id),
        )
        web.conn.commit()

    def test_ads_bound_campaign_of_another_org_refused_before_meta(self):
        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                meta_repo.ad_set_ids_by_exact_name(
                    web.conn, self.org_a, self.camp_id, "隨便什麼名字",
                )
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "campaign_not_owned")

    def test_ads_bound_group_of_another_org_refused_before_meta(self):
        with mock.patch.object(graph, "list_ads") as fake_list_ads:
            with self.assertRaises(web.ApiError) as caught:
                meta_repo.ad_ids_by_exact_name(
                    web.conn, self.org_a, self.adset_id, "隨便什麼名字",
                )
            self.assertEqual(fake_list_ads.call_count, 0)
        self.assertEqual(caught.exception.code, "adset_not_owned")

    def test_listed_external_entity_of_another_org_refused(self):
        web.conn.execute(
            "INSERT INTO ads_external_entity (id, org_id, brand_id, campaign_id, platform,"
            " source_account, native_kind, native_id)"
            " VALUES (%s, %s, %s, %s, 'meta', 'act_b', 'campaign', %s)",
            (db.new_id("aex"), self.org_b, self.brand_b, self.campaign_b, f"{self.camp_id}-listed"),
        )
        web.conn.commit()
        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                meta_repo.ad_set_ids_by_exact_name(
                    web.conn, self.org_a, f"{self.camp_id}-listed", "隨便什麼名字",
                )
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.code, "campaign_not_owned")

    def test_own_ads_binding_is_not_refused(self):
        with mock.patch.object(graph, "list_ad_sets", return_value=[]) as fake_list_ad_sets:
            result = meta_repo.ad_set_ids_by_exact_name(
                web.conn, self.org_b, self.camp_id, "隨便什麼名字",
            )
        # org_b has no token, so it stops at "no list to match" — the guard let it through.
        self.assertEqual(result, [])
        self.assertEqual(fake_list_ad_sets.call_count, 0)
        meta_repo.save_token(web.conn, self.org_b, TOKEN)
        web.conn.commit()
        with mock.patch.object(graph, "list_ad_sets", return_value=[]) as fake_list_ad_sets:
            meta_repo.ad_set_ids_by_exact_name(
                web.conn, self.org_b, self.camp_id, "隨便什麼名字",
            )
        self.assertEqual(fake_list_ad_sets.call_count, 1)


class TenantScopedParentGuardTest(AdsCenterParentGuardTest):
    """F31-I13: the guard on a request-shaped connection. Every API request (and every scoped
    job) runs `db.set_tenant_scope`, which switches to role `authenticated` with org-isolation
    RLS in effect, so other orgs' `ads_*` and `channel_entity_map` rows are invisible to a
    plain SELECT. The guard must still see that org B holds the id (through the modules'
    SECURITY DEFINER boolean lookups) and refuse before any Graph call.

    Inherits the ads-center fixture (org B's `ads_campaign` + `ads_delivery_group`) but not its
    tests: `test_*` below replace them for this class only."""

    test_ads_bound_campaign_of_another_org_refused_before_meta = None
    test_ads_bound_group_of_another_org_refused_before_meta = None
    test_listed_external_entity_of_another_org_refused = None
    test_own_ads_binding_is_not_refused = None

    def setUp(self):
        super().setUp()
        tail = uuid4().hex[:8]
        self.mapped_id = f"camp-map-b-{tail}"
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
            (db.new_id("cem"), self.org_b, self.brand_b, channel_id, self.mapped_id),
        )
        web.conn.commit()

    def _scoped(self, org_id, call):
        with db.connection() as conn:
            db.set_tenant_scope(conn, org_id)
            try:
                # Precondition: RLS really hides other orgs' rows here, so a refusal below is
                # the SECURITY DEFINER lookup at work, not an unscoped connection.
                hidden = conn.execute(
                    "SELECT (SELECT count(*) FROM ads_campaign"
                    "         WHERE external_id = %(camp)s AND org_id <> %(org)s)"
                    " + (SELECT count(*) FROM channel_entity_map"
                    "     WHERE external_id = %(mapped)s AND org_id <> %(org)s) AS n",
                    {"camp": self.camp_id, "mapped": self.mapped_id, "org": org_id},
                ).fetchone()
                self.assertEqual(hidden["n"], 0, "RLS must hide other orgs' rows here")
                return call(conn)
            finally:
                conn.rollback()
                conn.execute("RESET ROLE")
                conn.execute("RESET app.org_id")
                conn._tenant_org_id = None
                conn.commit()  # pooled connection must not go back scoped

    def test_ads_campaign_of_another_org_refused_on_scoped_connection(self):
        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                self._scoped(self.org_a, lambda conn: meta_repo.ad_set_ids_by_exact_name(
                    conn, self.org_a, self.camp_id, "隨便什麼名字",
                ))
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "campaign_not_owned")

    def test_channel_entity_map_id_of_another_org_refused_on_scoped_connection(self):
        with mock.patch.object(graph, "list_ad_sets") as fake_list_ad_sets:
            with self.assertRaises(web.ApiError) as caught:
                self._scoped(self.org_a, lambda conn: meta_repo.ad_set_ids_by_exact_name(
                    conn, self.org_a, self.mapped_id, "隨便什麼名字",
                ))
            self.assertEqual(fake_list_ad_sets.call_count, 0)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(caught.exception.code, "campaign_not_owned")

    def test_own_ids_pass_on_scoped_connection(self):
        meta_repo.save_token(web.conn, self.org_b, TOKEN)
        web.conn.commit()
        for parent_id in (self.camp_id, self.mapped_id):
            with mock.patch.object(graph, "list_ad_sets", return_value=[]) as fake_list_ad_sets:
                self._scoped(
                    self.org_b,
                    lambda conn, pid=parent_id: meta_repo.ad_set_ids_by_exact_name(
                        conn, self.org_b, pid, "隨便什麼名字",
                    ),
                )
            self.assertEqual(fake_list_ad_sets.call_count, 1, parent_id)

    def test_lookups_are_not_callable_by_anon(self):
        with db.connection() as conn:
            try:
                rows = conn.execute(
                    "SELECT p.proname,"
                    " has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_exec,"
                    " has_function_privilege('authenticated', p.oid, 'EXECUTE') AS auth_exec,"
                    " p.prosecdef, p.proconfig, pg_get_function_result(p.oid) AS result"
                    " FROM pg_proc p WHERE p.pronamespace = current_schema()::regnamespace"
                    " AND p.proname IN ('schedule_channel_entity_owned_elsewhere',"
                    "                   'ads_external_id_owned_elsewhere')"
                    " ORDER BY p.proname"
                ).fetchall()
            finally:
                conn.rollback()
        self.assertEqual(
            [r["proname"] for r in rows],
            ["ads_external_id_owned_elsewhere", "schedule_channel_entity_owned_elsewhere"],
        )
        for r in rows:
            self.assertFalse(r["anon_exec"], r["proname"])
            self.assertTrue(r["auth_exec"], r["proname"])
            self.assertTrue(r["prosecdef"], r["proname"])
            self.assertEqual(r["result"], "boolean", r["proname"])
            path = next(c for c in r["proconfig"] if c.startswith("search_path="))
            self.assertTrue(path.endswith("pg_temp"), path)


if __name__ == "__main__":
    unittest.main()
