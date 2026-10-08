"""app/tests/test_ads_customer_groups.py — F43-I02: the 【這個賣法的顧客】 section the strategy and
delivery-plan prompts share. Falsifiers: the line shape (pain label + key, quote, when); the caps
(≤3 per knowledge product, ≤6 in all, with the 「另有 N 群」 line); a bundle lists both of its
products' groups; the campaign's picked `customer_group_ids` narrow the list, the default (missing,
empty or stale) lists every group; no groups / no product say so instead of inventing one.
"""

import unittest
from datetime import date, timedelta

import app.shared.web as web
from app.ads import ads_learnings, customer_groups, external_repository, live_creative
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.tests.fixtures.ads_external import outcome_seed
from app.workbench import encode_learning_scope

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

    def test_prompt_groups_returns_the_listed_rows_in_prompt_order(self):
        """F46-I01 (Contract A): 第 N 群 is `listed[N-1]`, from the same read as the text, so
        picks, caps and the bundle's component order all hold for the planner's mapping."""
        first = self._product("薑黃錠", [_group("常應酬的上班族", ["effort"]),
                                         _group("照顧爸媽的子女", ["cost"])])
        second = self._product("魚油", [_group("久坐的工程師", ["experience"])])
        bundle_id = self._sell_way("保養雙入組", first, second)
        picked = [self._group_ids(second)[0], self._group_ids(first)[1]]
        context = {"product_ids": [bundle_id], "customer_group_ids": picked}

        text, listed = customer_groups.prompt_groups(
            web.conn, self.org_id, self.brand_id, {"context_json": context},
        )

        self.assertEqual([g["who"] for g in listed], ["照顧爸媽的子女", "久坐的工程師"])
        for n, group in enumerate(listed, start=1):
            self.assertIn(f"第 {n} 群：{group['who']}｜", text)
        self.assertEqual(
            (text, [g["id"] for g in listed]), self._section(context),
        )
        _, none_listed = customer_groups.prompt_groups(
            web.conn, self.org_id, self.brand_id, {"context_json": {}},
        )
        self.assertEqual(none_listed, [])

    def test_groups_by_id_resolves_every_group_of_the_campaigns_products(self):
        product = self._product("薑黃錠", [_group("常應酬的上班族", ["effort"]),
                                           _group("照顧爸媽的子女", ["cost"])])
        sell_way_id = self._sell_way("單瓶", product)
        found = customer_groups.groups_by_id(
            web.conn, self.brand_id,
            {"context_json": {"product_ids": [sell_way_id],
                              "customer_group_ids": [self._group_ids(product)[0]]}},
        )
        self.assertEqual(set(found), set(self._group_ids(product)))
        self.assertEqual(customer_groups.groups_by_id(web.conn, self.brand_id, {}), {})

    def test_brief_text_joins_the_present_parts(self):
        self.assertEqual(
            customer_groups.brief_text(_group(
                "常應酬的上班族", ["effort", "uncertainty"], "每天吃一顆就好嗎", "應酬前一晚",
            )),
            "常應酬的上班族｜煩惱：太麻煩、怕買錯｜顧客會說：每天吃一顆就好嗎｜什麼時候用：應酬前一晚",
        )
        self.assertEqual(customer_groups.brief_text(_group("照顧爸媽的子女", ["cost"])),
                         "照顧爸媽的子女｜煩惱：太貴")

    def _current(self, sell_way_id):
        return ads_learnings.current_conditions(
            web.conn, self.org_id, self.brand_id, sell_way_id,
        )

    def test_current_qualification_resolves_ordinary_sell_way_without_changing_scope(self):
        product = self._product("Current product", [_group("A1", ["effort"]),
                                                     _group("A2", ["cost"])])
        way = self._sell_way("Single", product)
        unrelated = self._product("Unrelated", [_group("Other buyer", ["cost"])])
        other_way = self._sell_way("Other single", unrelated)
        current = self._current(way)
        self.assertEqual(current["product_id"], way)
        self.assertNotEqual(way, product["id"])
        self.assertEqual(current["customer_group_ids"], self._group_ids(product))
        self.assertTrue(set(current["customer_group_ids"]).isdisjoint(self._group_ids(unrelated)))
        self.assertEqual(self._current(other_way)["customer_group_ids"], self._group_ids(unrelated))

    def test_current_bundle_groups_are_distinct_and_not_capped_by_prompt(self):
        products = [self._product(f"Product {i}", [_group(f"Buyer {i}-{j}", ["cost"])
                                                   for j in range(3)]) for i in range(3)]
        bases = [self._sell_way("Single", product) for product in products]
        duplicate = self._sell_way("Another single of first product", products[0])
        bundle = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="Bundle", economics=dict(_ECONOMICS), actor=ACTOR,
            components=[{"sell_way_id": way, "qty": 1} for way in [*bases, duplicate]],
        )["id"]
        expected = [identity for product in products for identity in self._group_ids(product)]
        current = self._current(bundle)
        self.assertEqual(current["product_id"], bundle)
        self.assertEqual(current["customer_group_ids"], expected)
        self.assertEqual(len(expected), 9)
        self.assertEqual(len(self._section({"product_ids": [bundle]})[1]), 6)

    def test_current_unknown_or_foreign_sell_way_does_not_borrow_groups(self):
        foreign = bi_repo.create_brand(web.conn, org_id=self.org_id, name="Foreign brand",
                                       client_name=None, actor=ACTOR)["id"]
        product = bi_repo.create_product(web.conn, foreign, name="Foreign product", actor=ACTOR)
        bi_repo.save_customer_groups(web.conn, foreign, product["id"],
                                     [_group("Foreign buyer", ["cost"])], actor=ACTOR)
        way = bi_repo.save_sell_way(web.conn, foreign, product_id=product["id"], name="Foreign way",
                                    economics=dict(_ECONOMICS), actor=ACTOR)["id"]
        for selected in (None, "missing-way", product["id"], way):
            with self.subTest(selected=selected):
                current = self._current(selected)
                self.assertIsNone(current["product_id"])
                self.assertEqual(current["customer_group_ids"], [])

    def test_actual_thin_history_is_usable_for_its_current_group_then_revalidates_if_removed(self):
        product = self._product("Historical product", [_group("A1", ["effort"])])
        way = self._sell_way("Single", product)
        customer = self._group_ids(product)[0]
        day = coresettings.today_for_org(web.conn, org_id=self.org_id) - timedelta(days=1)
        self.assertIsInstance(day, date)
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "Retained thin trial", "goal_text": "Limited association", "objective": "購買",
            "target_cost": 300,
            "target_basis": "own", "start_date": day.isoformat(), "end_date": day.isoformat(),
            "context_json": {"product_ids": [way]},
        }, created_by=ACTOR)
        group = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, campaign["id"],
            channel_key="meta", name="Group", role="new", daily_budget=400,
        )
        ad = ads_repo.create_ad(web.conn, self.org_id, self.brand_id, campaign["id"], group["id"],
                               name="Actual thin source", coordinates={
                                   "audience": "cold", "angle": "convenience", "offer": "none",
                               }, coordinates_snapshot={}, customer_group_id=customer)
        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label)"
            " VALUES(%s,%s,%s,'audience','cold','Cold buyers')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        live_creative.record_launch(web.conn, self.org_id, self.brand_id, campaign["id"],
                                    "retained-launch", detail)
        bound = outcome_seed.bind_platform(web.conn, self.org_id, self.brand_id, detail)
        external_repository.upsert_observation(
            web.conn, self.org_id, self.brand_id, campaign["id"], {
                "entity_id": bound[ad["id"]], "day": day, "metric_scope": "ad", "spend": 400,
                "purchases": 2, "revenue": None, "source": "graph", "currency": "TWD",
                "attribution_key": "known-attribution",
            }, result_kind="purchase", result_count=2, result_action="omni_purchase",
            result_attribution="known-attribution",
        )
        web.conn.commit()
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        source = ads_learnings.source_evidence(
            web.conn, self.org_id, self.brand_id, detail, kind="campaign",
            window={"start": day.isoformat(), "end": day.isoformat()},
            ad=detail["groups"][0]["ads"][0], claim_key="convenience", direction="support",
        )
        learned = bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR, product_id=way, source_track="ads",
            source_cycle_id=campaign["id"], learning_text="A limited actual association",
            applicability_scope=encode_learning_scope("ads", source), confidence="observed",
            sample_size="2",
        )

        def item():
            return ads_learnings.evidence_context(
                web.conn, self.org_id, self.brand_id, way, rows=[learned],
            )["items"][0]

        compatible = item()
        self.assertEqual(compatible["scope"]["product_id"], way)
        self.assertEqual(compatible["scope"]["customer_group_id"], customer)
        self.assertEqual(compatible["sample"]["result_events"], 2)
        self.assertEqual(compatible["use_state"], "usable")
        self.assertEqual(compatible["allowed_uses"], ["test", "retain_control"])
        bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], [], actor=ACTOR)
        removed = item()
        self.assertEqual(removed["use_state"], "revalidation")
        self.assertIn("condition_changed", removed["reason_codes"])
        self.assertEqual(removed["allowed_uses"], [])
        self.assertEqual(removed["scope"], compatible["scope"])


if __name__ == "__main__":
    unittest.main()
