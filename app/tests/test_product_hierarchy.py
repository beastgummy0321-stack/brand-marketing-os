"""app/tests/test_product_hierarchy.py — F05-I02: knowledge lives on the mother product
(ARCHITECTURE.md §8 item 1). `context_compiler.compile()` resolves a sell way's `product_id`
through `bi_repo.knowledge_product_id()` before reading facts, so a sell way with no facts of
its own still gets the mother product's confirmed facts in the prompt text.

This file does not belong to any managed module, so it must not import `app.ads.*` or
`app.workbench.*` internals (the architecture checker would flag it) — only `context_compiler`
and the shared `brand_intelligence` repository.
"""

import unittest

import psycopg

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import context_compiler

ACTOR = "測試員"


class ContextCompilerFollowsMotherProductTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：知識掛母產品", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        self.sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR,
            parent_id=self.mother["id"],
        )
        bi_repo.create_product_fact(
            web.conn, self.brand_id, self.mother["id"], actor=ACTOR, fact_type="ingredient",
            label="主成分", value="薑黃萃取物", status="confirmed", confirmed_by=ACTOR,
        )

    def test_compile_on_sell_way_includes_mother_products_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.sell_way["id"])
        self.assertIn("薑黃萃取物", text)

    def test_compile_on_mother_product_still_includes_its_own_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.mother["id"])
        self.assertIn("薑黃萃取物", text)


class SameNameGuardTest(unittest.TestCase):
    """F36-I10 (drill-6 #16, Contract W): `create_product` is get-or-create on a trimmed,
    case-insensitive name within one scope (brand for parents, parent for sell-ways), and the
    two partial unique indexes back it up."""

    def setUp(self):
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：同名守門", client_name=None,
            actor=ACTOR,
        )["id"]

    def _active_parents(self) -> list:
        return [p for p in bi_repo.list_products(web.conn, self.brand_id)
                if p["parent_id"] is None and p["status"] == "active"]

    def test_same_parent_name_twice_returns_one_row(self):
        first = bi_repo.create_product(web.conn, self.brand_id, name="超能特惠組", actor=ACTOR)
        for variant in (" 超能特惠組 ", "超能特惠組", "\t超能特惠組\n"):
            again = bi_repo.create_product(web.conn, self.brand_id, name=variant, actor=ACTOR)
            self.assertEqual(again["id"], first["id"], repr(variant))
            self.assertEqual(again["name"], "超能特惠組")
        self.assertEqual(len(self._active_parents()), 1)
        # Existing row is returned untouched: no second create audit, no update audit.
        audits = web.conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'product' AND entity_id = %s",
            (first["id"],),
        ).fetchall()
        self.assertEqual([a["action"] for a in audits], ["create"])

    def test_case_variants_collapse_to_one_row(self):
        first = bi_repo.create_product(web.conn, self.brand_id, name="Omega Plus", actor=ACTOR)
        for variant in ("omega plus", "OMEGA PLUS", " Omega plus "):
            again = bi_repo.create_product(web.conn, self.brand_id, name=variant, actor=ACTOR)
            self.assertEqual(again["id"], first["id"], repr(variant))
        self.assertEqual(len(self._active_parents()), 1)

    def test_created_name_is_stored_trimmed(self):
        row = bi_repo.create_product(web.conn, self.brand_id, name="  薑黃錠  ", actor=ACTOR)
        self.assertEqual(row["name"], "薑黃錠")
        self.assertEqual(bi_repo.get_product(web.conn, self.brand_id, row["id"])["name"], "薑黃錠")

    def test_sell_way_may_share_a_name_with_another_parent(self):
        mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        other = bi_repo.create_product(web.conn, self.brand_id, name="單瓶", actor=ACTOR)
        sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother["id"])
        self.assertNotEqual(sell_way["id"], other["id"])
        self.assertEqual(sell_way["parent_id"], mother["id"])
        self.assertIsNone(bi_repo.get_product(web.conn, self.brand_id, other["id"])["parent_id"])

    def test_two_sell_ways_with_one_name_under_one_parent_collapse(self):
        mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        first = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR, parent_id=mother["id"])
        second = bi_repo.create_product(
            web.conn, self.brand_id, name=" 薑黃錠 · 單瓶 ", actor=ACTOR, parent_id=mother["id"])
        self.assertEqual(second["id"], first["id"])
        children = [p for p in bi_repo.list_products(web.conn, self.brand_id)
                    if p["parent_id"] == mother["id"]]
        self.assertEqual(len(children), 1)

    def test_same_sell_way_name_under_two_parents_stays_two_rows(self):
        mother_a = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        mother_b = bi_repo.create_product(web.conn, self.brand_id, name="魚油", actor=ACTOR)
        child_a = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother_a["id"])
        child_b = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother_b["id"])
        self.assertNotEqual(child_a["id"], child_b["id"])

    def test_index_is_the_backstop_for_a_direct_insert(self):
        """The partial unique index rejects a same-name active parent even when the facade is
        bypassed; an archived same-name row is not in the index."""
        first = bi_repo.create_product(web.conn, self.brand_id, name="守門測試", actor=ACTOR)
        org_id = web.conn.execute(
            "SELECT org_id FROM brand WHERE id = %s", (self.brand_id,)).fetchone()["org_id"]
        insert = (
            "INSERT INTO product (id, org_id, brand_id, name, status, knowledge_version,"
            " created_at, updated_at, parent_id) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, NULL)"
        )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            web.conn.execute(insert, (coredb.new_id("prd"), org_id, self.brand_id, " 守門測試 ",
                                      "active", coredb.now_utc(), coredb.now_utc()))
        web.conn.rollback()
        web.conn.execute(insert, (coredb.new_id("prd"), org_id, self.brand_id, "守門測試",
                                  "archived", coredb.now_utc(), coredb.now_utc()))
        web.conn.commit()
        self.assertEqual(len(self._active_parents()), 1)
        self.assertEqual(self._active_parents()[0]["id"], first["id"])


if __name__ == "__main__":
    unittest.main()
