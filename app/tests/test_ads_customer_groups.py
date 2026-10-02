"""app/tests/test_ads_customer_groups.py — F43-I02: the 【這個賣法的顧客】 section the strategy and
delivery-plan prompts share. Falsifiers: the line shape (pain label + key, quote, when); the caps
(≤3 per knowledge product, ≤6 in all, with the 「另有 N 群」 line); a bundle lists both of its
products' groups; the campaign's picked `customer_group_ids` narrow the list, the default (missing,
empty or stale) lists every group; no groups / no product say so instead of inventing one.
"""

import unittest

import app.shared.web as web
from app.ads import customer_groups
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb

ACTOR = "測試員"

_ECONOMICS = {"selling_price": 990, "unit_variable_cost": 200, "shipping_cost": 60}


def _group(who: str, pains: list[str], quote: str | None = None,
           when_used: str | None = None) -> dict:
    return {"who": who, "pain_keys": pains, "quote": quote, "when_used": when_used}


class CustomerGroupsSectionTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：賣法的顧客", client_name=None,
            actor=ACTOR,
        )["id"]

    def _product(self, name: str, groups: list[dict]) -> dict:
        product = bi_repo.create_product(web.conn, self.brand_id, name=name, actor=ACTOR)
        if groups:
            bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], groups,
                                         actor=ACTOR)
        return product

    def _sell_way(self, name: str, *products: dict) -> str:
        """F45: one product -> a base sell-way; several -> a bundle of each one's base."""
        if len(products) == 1:
            return bi_repo.save_sell_way(
                web.conn, self.brand_id, name=name, economics=dict(_ECONOMICS), actor=ACTOR,
                product_id=products[0]["id"],
            )["id"]
        bases = [self._sell_way("單件", p) for p in products]
        return bi_repo.save_sell_way(
            web.conn, self.brand_id, name=name, economics=dict(_ECONOMICS), actor=ACTOR,
            components=[{"sell_way_id": b, "qty": 1} for b in bases],
        )["id"]

    def _section(self, context_json: dict) -> tuple[str, list[str]]:
        return customer_groups.prompt_section(
            web.conn, self.org_id, self.brand_id, {"context_json": context_json},
        )

    def _group_ids(self, product: dict) -> list[str]:
        rows = bi_repo.list_customer_groups(web.conn, self.brand_id, product["id"])
        return [g["id"] for g in rows]

    def test_two_groups_of_a_single_product_sell_way_print_label_key_quote_and_when(self):
        product = self._product("薑黃錠", [
            _group("常應酬的上班族", ["effort", "uncertainty"], "每天吃一顆就好嗎", "應酬前一晚"),
            _group("照顧爸媽的子女", ["cost"]),
        ])
        sell_way_id = self._sell_way("單瓶", product)

        text, ids = self._section({"product_ids": [sell_way_id]})

        self.assertEqual(text, "\n".join([
            "【這個賣法的顧客】",
            "第 1 群：常應酬的上班族｜煩惱：太麻煩（pain=effort）、怕買錯（pain=uncertainty）"
            "｜顧客會說：每天吃一顆就好嗎｜什麼時候用：應酬前一晚",
            "第 2 群：照顧爸媽的子女｜煩惱：太貴（pain=cost）"
            "｜顧客會說：（沒寫）｜什麼時候用：（沒寫）",
        ]))
        self.assertEqual(ids, self._group_ids(product))

    def test_bundle_with_two_products_lists_both_products_groups_in_component_order(self):
        first = self._product("薑黃錠", [_group("常應酬的上班族", ["effort"])])
        second = self._product("魚油", [_group("久坐的工程師", ["experience"]),
                                         _group("健身新手", ["identity"])])
        bundle_id = self._sell_way("保養雙入組", first, second)

        text, ids = self._section({"product_ids": [bundle_id]})

        self.assertIn("第 1 群：常應酬的上班族", text)
        self.assertIn("第 2 群：久坐的工程師", text)
        self.assertIn("第 3 群：健身新手", text)
        self.assertEqual(ids, self._group_ids(first) + self._group_ids(second))

    def test_three_products_of_three_groups_are_capped_at_six_with_the_rest_counted(self):
        products = [
            self._product(f"商品{i}", [_group(f"商品{i}第{j}群", ["cost"]) for j in range(1, 4)])
            for i in range(1, 4)
        ]
        bundle_id = self._sell_way("三入組", *products)

        text, ids = self._section({"product_ids": [bundle_id]})

        self.assertEqual(len(ids), 6)
        self.assertEqual(ids, self._group_ids(products[0]) + self._group_ids(products[1]))
        self.assertIn("第 6 群：商品2第3群", text)
        self.assertNotIn("商品3第1群", text)
        self.assertTrue(text.endswith("（另有 3 群沒有列出）"))

    def test_picked_ids_narrow_the_list(self):
        product = self._product("薑黃錠", [
            _group("常應酬的上班族", ["effort"]), _group("照顧爸媽的子女", ["cost"]),
        ])
        sell_way_id = self._sell_way("單瓶", product)
        second_id = self._group_ids(product)[1]

        text, ids = self._section({"product_ids": [sell_way_id], "customer_group_ids": [second_id]})

        self.assertEqual(ids, [second_id])
        self.assertIn("第 1 群：照顧爸媽的子女", text)
        self.assertNotIn("常應酬的上班族", text)

    def test_missing_empty_or_stale_picks_list_every_group(self):
        product = self._product("薑黃錠", [
            _group("常應酬的上班族", ["effort"]), _group("照顧爸媽的子女", ["cost"]),
        ])
        sell_way_id = self._sell_way("單瓶", product)
        every = self._group_ids(product)

        for picked in (None, [], ["pcg_gone"]):
            context = {"product_ids": [sell_way_id]}
            if picked is not None:
                context["customer_group_ids"] = picked
            with self.subTest(picked=picked):
                self.assertEqual(self._section(context)[1], every)

    def test_old_sell_way_row_reads_its_parent_products_groups(self):
        mother = self._product("薑黃錠", [_group("常應酬的上班族", ["effort"])])
        child = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 3 入組", actor=ACTOR, parent_id=mother["id"],
        )

        _, ids = self._section({"product_ids": [child["id"]]})

        self.assertEqual(ids, self._group_ids(mother))

    def test_product_without_groups_says_so(self):
        product = self._product("薑黃錠", [])

        text, ids = self._section({"product_ids": [self._sell_way("單瓶", product)]})

        self.assertEqual(text, "【這個賣法的顧客】（這個商品還沒有建顧客群）")
        self.assertEqual(ids, [])

    def test_campaign_without_a_product_says_so(self):
        text, ids = self._section({})

        self.assertEqual(text, "【這個賣法的顧客】（這個 Campaign 沒有指定商品）")
        self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main()
