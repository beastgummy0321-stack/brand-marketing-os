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


if __name__ == "__main__":
    unittest.main()
