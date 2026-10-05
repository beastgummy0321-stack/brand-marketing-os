"""app/tests/test_ads_product_hierarchy.py — F05-I01 falsifiers (ARCHITECTURE.md §8 items 1-3,
settled): one product, many ways to sell it. `parent_id` is self-referencing and exactly one
level deep; `knowledge_product_id()` is the one resolver every reader is supposed to call;
`close_rate`/`assumptions_json` round-trip through `product_economics` and its version table;
`breakeven_cpa` keeps its pre-F05 numbers for products (`close_rate is None`) and multiplies by
`close_rate` for services/leads.
"""

import unittest

import app.shared.web as web
from app.ads import budget
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb


class ProductHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：產品層級", client_name=None,
            actor="測試員",
        )
        self.brand_id = self.brand["id"]

    def test_parent_and_two_children_show_up_in_list_products(self):
        parent = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor="測試員")
        child_a = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor="測試員", parent_id=parent["id"])
        child_b = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 3 入組", actor="測試員", parent_id=parent["id"])
        rows = bi_repo.all_product_rows(web.conn, self.brand_id)
        self.assertEqual(len(rows), 3)
        by_id = {r["id"]: r for r in rows}
        self.assertIsNone(by_id[parent["id"]]["parent_id"])
        self.assertEqual(by_id[child_a["id"]]["parent_id"], parent["id"])
        self.assertEqual(by_id[child_b["id"]]["parent_id"], parent["id"])

    def test_a_child_cannot_have_a_child(self):
        parent = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor="測試員")
        child = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor="測試員", parent_id=parent["id"])
        with self.assertRaises(ValueError):
            bi_repo.create_product(
                web.conn, self.brand_id, name="薑黃錠 · 單瓶 · 加購", actor="測試員",
                parent_id=child["id"])

    def test_parent_id_cannot_cross_brands(self):
        other_brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="別的品牌", client_name=None, actor="測試員")
        parent = bi_repo.create_product(
            web.conn, other_brand["id"], name="別品牌的產品", actor="測試員")
        with self.assertRaises(ValueError):
            bi_repo.create_product(
                web.conn, self.brand_id, name="賣法", actor="測試員", parent_id=parent["id"])

    def test_knowledge_product_id_resolves_child_to_parent(self):
        parent = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor="測試員")
        child = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor="測試員", parent_id=parent["id"])
        resolve = bi_repo.knowledge_product_id
        self.assertEqual(resolve(web.conn, self.brand_id, child["id"]), parent["id"])
        self.assertEqual(resolve(web.conn, self.brand_id, parent["id"]), parent["id"])


class ProductEconomicsCloseRateTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：成交率", client_name=None, actor="測試員",
        )
        self.brand_id = self.brand["id"]
        self.product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="諮詢服務", actor="測試員")["id"]

    def test_close_rate_and_assumptions_round_trip_through_the_version_table(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=5000, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=1000, shipping_cost=0,
            close_rate=20, assumptions=["close_rate"],
        )
        current = bi_repo.get_product_economics(web.conn, self.brand_id, self.product_id)
        self.assertEqual(float(current["close_rate"]), 20.0)
        self.assertEqual(current["assumptions_json"], ["close_rate"])
        latest_version = web.conn.execute(
            "SELECT * FROM product_economics_version WHERE product_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (self.product_id,),
        ).fetchone()
        self.assertEqual(float(latest_version["close_rate"]), 20.0)
        self.assertEqual(latest_version["assumptions_json"], ["close_rate"])

    def test_close_rate_out_of_range_is_rejected(self):
        # F50 Contract I: a percent 0 < x <= 100, refused with the one percent sentence.
        for value in (0, 120):
            with self.assertRaises(ValueError) as caught:
                bi_repo.save_product_economics(
                    web.conn, self.brand_id, self.product_id, selling_price=5000, currency="TWD",
                    confirmed_by="測試員", actor="測試員", close_rate=value,
                )
            self.assertEqual(str(caught.exception), "成交率要大於 0、最多 100（填 20 代表 20%）。")

    def test_breakeven_cpa_unchanged_for_products_without_close_rate(self):
        economics = {"selling_price": 500, "unit_variable_cost": 150, "shipping_cost": 50}
        self.assertEqual(budget.breakeven_cpa(economics), 300)

    def test_breakeven_cpa_multiplies_by_close_rate_for_services(self):
        economics = {
            "selling_price": 5000, "unit_variable_cost": 1000, "shipping_cost": 0,
            "close_rate": 20,
        }
        # value x rate_fraction(20) = 4000 x 0.2 (F50 Contract I: stored percent, one multiplier).
        self.assertAlmostEqual(budget.breakeven_cpa(economics), 800.0)


if __name__ == "__main__":
    unittest.main()
