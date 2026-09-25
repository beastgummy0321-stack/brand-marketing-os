"""app/tests/test_cleanup_coverage.py — the brand-delete coverage alarm `app/core/cleanup.py`
has always cited (F31-I09, item 13).

Root cause this guards: every module declares the tables it clears on brand delete
(`cleanup.register(..., brand_tables=...)`), but nothing compared those declarations with the
live schema, so tables added later were never cleared and a brand with a period could not be
deleted at all (its periods kept a foreign key to the brand).

Table-name-free on purpose (app-shell code, like test_org_isolation_all_tables.py): everything is
derived from the registry and the live catalog.

1. Every live table with a `brand_id` column is declared by some registered module, apart from
   `EXEMPT_BRAND_TABLES` (one reason each). That list may only shrink: a new entry means brand
   data that outlives its brand, which is a product decision, not a test edit.
2. Every declared table still exists (a dropped table left in a registry is a stale claim).
3. Delete order can satisfy every foreign key between cleared tables: registration order is
   delete order (cleanup.delete_all), so the module clearing a referrer registers no later than
   the module clearing what it references.
4. An exempt (kept) table that references a cleared table does so with an ON DELETE action, or
   it would block the delete (the kept AI-spend rows pointing at a period did exactly that).

The seeded end-to-end regressions live with their owners: app/tests/test_schedule_brand_delete.py
and app/tests/test_ads_brand_delete.py.

Imports only legacy facades: `app.main` (the composition root, so every module's registration
has run in production order) and `app.core`.
"""

import unittest

import app.main  # noqa: F401 -- composition root: runs every cleanup.register() in production order
from app.core import cleanup, db

# Brand data kept on purpose after the brand is deleted. May only shrink.
EXEMPT_BRAND_TABLES = {
    # AI spend record: the money was spent even if the brand is gone (user ruling, pinned by
    # app/tests/test_orders_core_brand_cleanup.py test_delete_brand_keeps_llm_task).
    "llm_task": "AI 花費紀錄：品牌刪掉，那筆支出仍然發生過",
    # Audit outlives its subject: brand delete itself writes the final audit row.
    "audit_log": "稽核紀錄比被稽核的對象活得久（刪品牌本身也寫一筆）",
}
_EXEMPTION_CEILING = frozenset({"llm_task", "audit_log"})

# Known order violations, one reason each; may only shrink (the test below fails once one is fixed).
KNOWN_ORDER_VIOLATIONS = {
    # 品牌智庫 (imported by everything, so registered first) deletes the brand's products before
    # 投放中心 deletes its ads; an ad pointing at a product makes the brand delete fail. Same
    # class and same fix as 20260911000002_workbench_brief_product_fk_set_null.sql: an ads
    # migration switching this FK to ON DELETE SET NULL (outside F31-I09's touch; reported).
    "ads_ad_product_id_fkey": "ads 表的 product 外鍵沒有 ON DELETE，刪品牌時先刪產品會被擋",
}

# pg_constraint.confdeltype: a = NO ACTION, r = RESTRICT block the parent delete.
_BLOCKING_DELETE_ACTIONS = {"a", "r"}


def _live_brand_tables(conn) -> set:
    rows = conn.execute(
        "SELECT c.table_name FROM information_schema.columns c"
        " JOIN information_schema.tables t"
        "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
        " WHERE c.table_schema = current_schema() AND c.column_name = 'brand_id'"
        "   AND t.table_type = 'BASE TABLE'"
    ).fetchall()
    return {r["table_name"] for r in rows}


def _foreign_keys(conn) -> list:
    """[(referrer table, referenced table, delete action, constraint name)] in this schema."""
    rows = conn.execute(
        "SELECT child.relname AS child, parent.relname AS parent,"
        "       con.confdeltype::text AS action, con.conname AS name"
        " FROM pg_constraint con"
        " JOIN pg_class child ON child.oid = con.conrelid"
        " JOIN pg_class parent ON parent.oid = con.confrelid"
        " JOIN pg_namespace ns ON ns.oid = con.connamespace"
        " WHERE con.contype = 'f' AND ns.nspname = current_schema()"
    ).fetchall()
    return [(r["child"], r["parent"], r["action"], r["name"]) for r in rows]


def _owners() -> dict:
    """{table: registered module name} for every declared brand table."""
    return {t: name for name, tables in cleanup.declared_brand_tables().items() for t in tables}


class CleanupCoverageTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def test_every_live_brand_table_is_cleared_or_exempt(self):
        live = _live_brand_tables(self.conn)
        unclaimed = live - set(_owners()) - set(EXEMPT_BRAND_TABLES)
        self.assertEqual(
            unclaimed, set(),
            "these tables carry brand_id but no cleanup.register() declares them: deleting a "
            "brand leaves their rows behind (or fails on a foreign key)")

    def test_declared_tables_exist(self):
        stale = set(_owners()) - _live_brand_tables(self.conn)
        self.assertEqual(stale, set(), "registries declare tables that no longer exist")

    def test_exemptions_are_live_undeclared_and_only_shrink(self):
        self.assertLessEqual(set(EXEMPT_BRAND_TABLES), _EXEMPTION_CEILING)
        live = _live_brand_tables(self.conn)
        declared = set(_owners())
        for table, reason in EXEMPT_BRAND_TABLES.items():
            self.assertTrue(reason)
            self.assertIn(table, live, f"exempt table {table} no longer exists: drop the exemption")
            self.assertNotIn(table, declared, f"{table} is exempt yet a registry clears it")

    def test_referrers_are_cleared_no_later_than_what_they_reference(self):
        order = {name: i for i, name in enumerate(cleanup.registered_names())}
        owners = _owners()
        late = []
        for child, parent, action, name in _foreign_keys(self.conn):
            if child == parent or action not in _BLOCKING_DELETE_ACTIONS:
                continue
            if child in owners and parent in owners and name not in KNOWN_ORDER_VIOLATIONS:
                if order[owners[child]] > order[owners[parent]]:
                    late.append(f"{name}: {child} ({owners[child]}) is cleared after "
                                f"{parent} ({owners[parent]})")
        self.assertEqual(late, [], "registration order is delete order; these FKs would block it")

    def test_known_order_violations_are_still_live(self):
        """Remove an entry from KNOWN_ORDER_VIOLATIONS once its FK stops blocking."""
        order = {name: i for i, name in enumerate(cleanup.registered_names())}
        owners = _owners()
        live = {
            name for child, parent, action, name in _foreign_keys(self.conn)
            if action in _BLOCKING_DELETE_ACTIONS and child in owners and parent in owners
            and order[owners[child]] > order[owners[parent]]
        }
        for name, reason in KNOWN_ORDER_VIOLATIONS.items():
            self.assertTrue(reason)
            self.assertIn(name, live,
                          f"{name} no longer blocks: drop it from KNOWN_ORDER_VIOLATIONS")

    def test_uncleared_tables_do_not_block_deleting_cleared_ones(self):
        owners = _owners()
        blocking = [
            f"{name}: {child} -> {parent}"
            for child, parent, action, name in _foreign_keys(self.conn)
            if parent in owners and child not in owners and child in EXEMPT_BRAND_TABLES
            and action in _BLOCKING_DELETE_ACTIONS
        ]
        self.assertEqual(
            blocking, [],
            "a kept (exempt) table references a cleared one without an ON DELETE action, so the "
            "brand delete fails on it")


if __name__ == "__main__":
    unittest.main()
