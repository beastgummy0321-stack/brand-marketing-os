"""app/tests/test_ads_budget_sell_way.py — F43-I04: budget reads the sell-way a campaign carries.

F31-I01 fixed a parent product's first sell-way to be the one entered first; F43-I04 removes that
parent -> first-sell-way fallback altogether (a campaign always carries a sell-way id: only
sell-ways are pickable), so a knowledge product id yields nothing, and a bundle's break-even is
computed from its effective economics (NULL cost = Σ its components' costs).
"""

import unittest

import app.shared.web as web
from app.ads import budget
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb


class SellWayEconomicsTest(unittest.TestCase):
    def setUp(self):
        brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：賣法金額", client_name=None,
            actor="測試員",
        )
        self.brand_id = brand["id"]
        self.gummy = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠", actor="測試員")["id"]
        self.tea = bi_repo.create_product(
            web.conn, self.brand_id, name="濾掛茶", actor="測試員")["id"]

    def _sell_way(self, name: str, components: list, **economics) -> str:
        return bi_repo.save_sell_way(
            web.conn, self.brand_id, name=name, actor="測試員", economics=economics,
            components=[{"product_id": p, "qty": q} for p, q in components],
        )["id"]

    def test_a_knowledge_product_id_no_longer_falls_back_to_its_first_sell_way(self):
        self._sell_way("單品", [(self.gummy, 1)], selling_price=600, unit_variable_cost=100)

        self.assertEqual(budget.economics_for(web.conn, self.brand_id, [self.gummy]), (None, None))

    def test_a_bundle_uses_its_derived_cost(self):
        self._sell_way("單品", [(self.gummy, 1)], selling_price=600, unit_variable_cost=100,
                       shipping_cost=0)
        self._sell_way("單包", [(self.tea, 1)], selling_price=200, unit_variable_cost=50,
                       shipping_cost=0)
        bundle = self._sell_way("茶點組", [(self.gummy, 1), (self.tea, 2)], selling_price=899,
                                shipping_cost=60)

        economics, product_id = budget.economics_for(web.conn, self.brand_id, [bundle])

        self.assertEqual(product_id, bundle)
        self.assertEqual(float(economics["unit_variable_cost"]), 200)  # 100 + 2 × 50
        self.assertIn("unit_variable_cost", economics["derived_fields"])
        self.assertEqual(budget.breakeven_cpa(economics), 639)  # 899 − 200 − 60


if __name__ == "__main__":
    unittest.main()
