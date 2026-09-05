"""Gate A (ticket 02-5, ADR 0027 decision 4; amended ticket 03-1): every table carries the
tenant boundary.

Every base table in this module's schema except the two in `EXEMPT_TABLES` must have a
NOT NULL `org_id` column with a foreign key to `organisation(id)`. No allow-list beyond
these two, documented exceptions — a new table without org_id is a defect, not an exception:

- `organisation` — it *is* the tenant boundary; a row doesn't belong to itself.
- `app_user` — a user spans organisations (a person can hold memberships in more than one
  org), so there is no single `org_id` to attach to this table (ticket 03-1 §1). The actual
  tenant boundary for users lives in `membership` (which does carry `org_id`, PK'd on
  `(org_id, user_id)`) and is enforced by `app.identity.authenticate()`'s org resolution,
  not by a column on `app_user` itself.
"""

import unittest

import psycopg

from app.core import db

EXEMPT_TABLES = frozenset({"organisation", "app_user"})


class OrgIsolationAllTablesTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _tables(self):
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        )
        return sorted(r["table_name"] for r in rows)

    def _org_id_column(self, table):
        row = self.conn.execute(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = %s AND column_name = 'org_id'",
            (table,),
        ).fetchone()
        return row

    def _fk_to_organisation(self, table):
        row = self.conn.execute(
            "SELECT 1 FROM information_schema.table_constraints tc"
            " JOIN information_schema.key_column_usage kcu"
            "   ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema"
            "   AND kcu.table_name = tc.table_name"
            " JOIN information_schema.constraint_column_usage ccu"
            "   ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema"
            " WHERE tc.table_schema = current_schema() AND tc.constraint_type = 'FOREIGN KEY'"
            "   AND tc.table_name = %s AND kcu.column_name = 'org_id'"
            "   AND ccu.table_name = 'organisation' AND ccu.column_name = 'id'",
            (table,),
        ).fetchone()
        return row is not None

    def test_every_table_has_not_null_org_id_with_fk(self):
        tables = self._tables()
        # 外殼切片（2026-08-28）：票 3 的 migration DROP 掉 44 張廣告表後，public schema
        # 剩 39 張，門檻從 50 下修到 30。這個數字守的是「baseline 沒套用、schema 是空的」，
        # 不是「表只能增加」。
        self.assertGreater(len(tables), 30, "schema looks empty; baseline not applied?")
        missing, nullable, no_fk = [], [], []
        for t in tables:
            if t in EXEMPT_TABLES:
                continue
            col = self._org_id_column(t)
            if col is None:
                missing.append(t)
                continue
            if col["is_nullable"] != "NO":
                nullable.append(t)
            if not self._fk_to_organisation(t):
                no_fk.append(t)
        self.assertEqual(missing, [], f"tables without org_id: {missing}")
        self.assertEqual(nullable, [], f"tables with nullable org_id: {nullable}")
        self.assertEqual(no_fk, [], f"tables whose org_id has no FK to organisation(id): {no_fk}")

    def test_exempt_set_is_exactly_the_two_documented_tables(self):
        """票 03-1 硬性規則：例外清單只准這兩張、不准悄悄加寬。清單本身要跟現況對得上——
        兩張都真的存在，且清單沒有第三張。"""
        self.assertEqual(EXEMPT_TABLES, frozenset({"organisation", "app_user"}))
        tables = set(self._tables())
        for t in EXEMPT_TABLES:
            self.assertIn(t, tables, f"{t} 在例外清單裡，但這個 schema 沒有這張表")


class CampaignPeriodCompositeFKTenantIsolationTest(unittest.TestCase):
    """Ticket 07 (docs/issues/deploy/07-campaign-period-composite-fk.md), done-check 4: the
    composite FK `(campaign_period_id, org_id) REFERENCES campaign_period(id, org_id)` is
    attacked, not merely declared. Covers both nullability classes named in the ticket, since
    they fail differently: `decision.campaign_period_id` is nullable, `period_node_membership
    .campaign_period_id` is NOT NULL.

    Proven red once by hand (2026-09-05): with `decision_campaign_period_id_org_id_fkey`
    dropped and the old single-column `FOREIGN KEY (campaign_period_id) REFERENCES
    campaign_period(id)` restored in its place, the cross-org insert in
    `test_decision_cross_org_period_reference_is_rejected` below succeeded instead of
    raising — i.e. this test failed. The composite constraint was then restored (matching the
    live migrations) and the test passed again.
    """

    def setUp(self):
        self.conn = db.current()

    def _make_org(self, suffix: str) -> str:
        org_id = f"org_fk_test_{suffix}"
        self.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        self.conn.commit()
        return org_id

    def _make_brand(self, org_id: str) -> str:
        brand_id = db.new_id("brd")
        self.conn.execute(
            "INSERT INTO brand (id, org_id, name, status, knowledge_version, created_at,"
            " updated_at) VALUES (%s, %s, %s, 'active', 1, now(), now())",
            (brand_id, org_id, f"brand for {org_id}"),
        )
        self.conn.commit()
        return brand_id

    def _make_period(self, org_id: str, brand_id: str) -> str:
        period_id = db.new_id("cpd")
        self.conn.execute(
            "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
            " status, currency) VALUES (%s, %s, %s, %s, '2026-01-01', '2026-01-31',"
            " 'planning', 'TWD')",
            (period_id, org_id, brand_id, f"period for {org_id}"),
        )
        self.conn.commit()
        return period_id

    def test_decision_cross_org_period_reference_is_rejected(self):
        """Nullable class: org A's decision row pointing at org B's period must be refused by
        the database; the same row pointing at org A's own period must still insert (the pair
        the ticket's literal example is measured against)."""
        org_a, org_b = self._make_org("dec_a"), self._make_org("dec_b")
        brand_a, brand_b = self._make_brand(org_a), self._make_brand(org_b)
        period_a = self._make_period(org_a, brand_a)
        period_b = self._make_period(org_b, brand_b)

        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute(
                "INSERT INTO decision (id, org_id, module, brand_id, rule_id, action_json,"
                " risk_level, autonomy_mode, dedupe_key, outcome, campaign_period_id)"
                " VALUES (%s, %s, 'schedule', %s, 'rule-1', '{}', 'low', 0, 'dedupe-cross',"
                " 'pending', %s)",
                (db.new_id("dec"), org_a, brand_a, period_b),
            )
        self.conn.rollback()

        self.conn.execute(
            "INSERT INTO decision (id, org_id, module, brand_id, rule_id, action_json,"
            " risk_level, autonomy_mode, dedupe_key, outcome, campaign_period_id)"
            " VALUES (%s, %s, 'schedule', %s, 'rule-1', '{}', 'low', 0, 'dedupe-same-org',"
            " 'pending', %s)",
            (db.new_id("dec"), org_a, brand_a, period_a),
        )
        self.conn.commit()

    def test_period_node_membership_cross_org_period_reference_is_rejected(self):
        """NOT NULL class: same attack against a column that cannot be nulled away instead
        (`period_node_membership.campaign_period_id`) — the failure mode the ticket names as
        the tempting-but-wrong fix (widen the constraint / null the column) cannot apply
        here."""
        org_a, org_b = self._make_org("pnm_a"), self._make_org("pnm_b")
        brand_a, brand_b = self._make_brand(org_a), self._make_brand(org_b)
        period_a = self._make_period(org_a, brand_a)
        period_b = self._make_period(org_b, brand_b)
        channel_a = db.new_id("adch")
        self.conn.execute(
            "INSERT INTO ad_channel (id, org_id, channel_key) VALUES (%s, %s, 'meta')",
            (channel_a, org_a),
        )
        self.conn.commit()

        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute(
                "INSERT INTO period_node_membership (id, org_id, brand_id,"
                " campaign_period_id, node_key, from_date, channel_id)"
                " VALUES (%s, %s, %s, %s, '1', '2026-01-01', %s)",
                (db.new_id("pnm"), org_a, brand_a, period_b, channel_a),
            )
        self.conn.rollback()

        self.conn.execute(
            "INSERT INTO period_node_membership (id, org_id, brand_id,"
            " campaign_period_id, node_key, from_date, channel_id)"
            " VALUES (%s, %s, %s, %s, '1', '2026-01-01', %s)",
            (db.new_id("pnm"), org_a, brand_a, period_a, channel_a),
        )
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
