"""app/tests/test_ads_budget_sell_way.py — F31-I01: a parent product's first sell-way is the one
entered first, not the one whose name sorts first. `_economics_for` used `list_products`' name
order, so a parent entered as 「單品」 then 「3 入組」 priced its budget off 「3 入組」.
"""

import unittest

import app.shared.web as web
from app.ads import budget
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb


class FirstSellWayTest(unittest.TestCase):
    def setUp(self):
        brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：賣法順序", client_name=None,
            actor="測試員",
        )
        self.brand_id = brand["id"]
        self.parent_id = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠", actor="測試員")["id"]

    def _sell_way(self, name: str, price: float) -> str:
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name=name, actor="測試員", parent_id=self.parent_id)["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=price, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=100, shipping_cost=0,
        )
        return product_id

    def test_parent_uses_the_sell_way_entered_first(self):
        # Entered first, but sorts after 「薑黃錠 · 3 入組」 by name.
        single = self._sell_way("薑黃錠 · 單品", 600)
        self._sell_way("薑黃錠 · 3 入組", 1600)
        names = [p["name"] for p in bi_repo.list_products(web.conn, self.brand_id)
                 if p["parent_id"] == self.parent_id]
        self.assertEqual(names[0], "薑黃錠 · 3 入組")  # the name order this must not follow

        economics, product_id = budget.economics_for(web.conn, self.brand_id, [self.parent_id])

        self.assertEqual(product_id, single)
        self.assertEqual(float(economics["selling_price"]), 600)


if __name__ == "__main__":
    unittest.main()
