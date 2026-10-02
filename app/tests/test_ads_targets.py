"""app/tests/test_ads_targets.py — F16-I04 falsifiers, re-cut by F28-I01 (one cap):
`targets.resolve()` never returns a default number, a fallback constant, a zero, or this
campaign's own past actual. Priority is fixed: the user's own cap always wins; else break-even
from product economics when this campaign's own result is a purchase and a product with a cost is
known; else unresolved with a `missing` reason naming what is blocking it.
"""

import unittest
from datetime import timedelta

import app.shared.web as web
from app.ads import channels, repository, targets
from app.ads import external_repository as external
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：目標成本", client_name=None,
            actor="測試員",
        )["id"]
        web.conn.commit()

    def _product(self, *, unit_variable_cost=None):
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor="測試員",
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=unit_variable_cost,
            shipping_cost=50,
        )
        web.conn.commit()
        return product_id

    def _imported_campaign_with_days(self, rows, *, objective=None):
        """`rows` is a list of `(day_offset_before_end, spend, result_kind, result_count,
        result_action, result_attribution)` tuples. `day_offset_before_end=0` is yesterday (the
        last complete day) -- the last complete day.

        `objective` (F16-I04), when given, is a Meta campaign objective string put on the
        campaign-level entity exactly as a real sync would see it; `result_kind` is derived from
        it through the real adapter mapping (`MetaReader.result_kind()`) and saved through the
        real write path (`repository.save_campaign_target`) -- never hand-set on a campaign dict.
        """
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動",
        )["id"]
        entity_fields = {
            "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
            "native_id": "c1",
        }
        if objective is not None:
            entity_fields["objective"] = objective
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id, entity_fields,
        )
        if objective is not None:
            result_kind = channels.external_reader("meta").result_kind(entity)
            repository.save_campaign_target(
                web.conn, self.org_id, self.brand_id, campaign_id,
                result_kind=result_kind, expected_revision=0, actor="測試員",
            )
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        end = today - timedelta(days=1)
        for offset, spend, result_kind, result_count, result_action, result_attribution in rows:
            external.upsert_observation(
                web.conn, self.org_id, self.brand_id, campaign_id,
                {
                    "entity_id": entity["id"], "day": end - timedelta(days=offset),
                    "metric_scope": "campaign", "attribution_key": "unused",
                    "currency": "TWD", "source": "meta", "spend": spend,
                },
                result_kind=result_kind, result_count=result_count,
                result_action=result_action, result_attribution=result_attribution,
            )
        web.conn.commit()
        return campaign_id

    def _imported_campaign_with_objective(self, objective, *, product_id=None):
        """Same real-adapter-mapping + real-write-path shape as `_imported_campaign_with_days`,
        for tests that only need the objective -> `result_kind` provenance, not daily rows.
        """
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動：" + objective,
        )["id"]
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "objective": objective},
        )
        web.conn.commit()
        result_kind = channels.external_reader("meta").result_kind(entity)
        repository.save_campaign_target(
            web.conn, self.org_id, self.brand_id, campaign_id,
            result_kind=result_kind, product_id=product_id, expected_revision=0, actor="測試員",
        )
        return campaign_id

    # -- sales, with/without product cost ------------------------------------------------------

    def test_sales_with_cost_resolves_break_even(self):
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["value"], 300)  # 500 - 150 - 50
        self.assertEqual(result["basis"], "break_even")
        self.assertEqual(result["result_kind"], "purchase")
        self.assertEqual(result["missing"], [])

    def test_sales_without_cost_never_guesses_falls_to_missing(self):
        product_id = self._product(unit_variable_cost=None)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertIn("product_cost", result["missing"])

    # -- F43-I04: the knowledge product behind the sell-way rides along --------------------------

    def test_knowledge_product_id_is_the_sell_ways_first_product(self):
        gummy = bi_repo.create_product(web.conn, self.brand_id, name="軟糖", actor="測試員")["id"]
        tea = bi_repo.create_product(web.conn, self.brand_id, name="濾掛", actor="測試員")["id"]
        single = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單盒", actor="測試員",
            product_id=gummy, economics={"selling_price": 399},
        )["id"]
        tea_bag = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單包", actor="測試員",
            product_id=tea, economics={"selling_price": 200},
        )["id"]
        bundle = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="茶點組", actor="測試員",
            components=[{"sell_way_id": tea_bag, "qty": 1}, {"sell_way_id": single, "qty": 1}],
            economics={"selling_price": 599},
        )["id"]
        for sell_way, knowledge in ((single, gummy), (bundle, tea)):
            result = targets.resolve(web.conn, self.org_id, self.brand_id, {
                "id": "nonexistent", "origin": "internal", "result_kind": None,
                "context_json": {"product_ids": [sell_way]},
            })
            # No cost anywhere: the 「去填商品成本」 link opens the knowledge product.
            self.assertEqual((result["product_id"], result["knowledge_product_id"]),
                             (sell_way, knowledge))
            self.assertIn("product_cost", result["missing"])
        none = targets.resolve(web.conn, self.org_id, self.brand_id, {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "context_json": {"product_ids": []},
        })
        self.assertIsNone(none["knowledge_product_id"])

    # -- no cap and no break-even: unresolved, never this campaign's own past actual ----------

    def test_engagement_with_spend_history_is_unresolved_never_trailing_actual(self):
        campaign_id = self._imported_campaign_with_days([
            (0, 100, "engagement", 10, "post_engagement", "7d_click+1d_view"),
            (5, 200, "engagement", 10, "post_engagement", "7d_click+1d_view"),
            (10, 300, "engagement", 20, "post_engagement", "7d_click+1d_view"),
        ], objective="OUTCOME_ENGAGEMENT")
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertEqual(result["result_kind"], "engagement")
        self.assertEqual(result["missing"], [])

    def test_no_data_and_no_kind_is_missing_result_kind_never_zero(self):
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="還沒同步過",
        )["id"]
        web.conn.commit()
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertEqual(result["missing"], ["result_kind"])

    def test_imported_sales_without_product_is_missing_product(self):
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="已知是購買但沒選商品",
        )["id"]
        web.conn.commit()
        campaign = {
            **repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id),
            "result_kind": "purchase",
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIn("product", result["missing"])

    # -- user override always wins ---------------------------------------------------------------

    def test_own_value_always_wins(self):
        product_id = self._product(unit_variable_cost=150)  # would otherwise break-even to 300
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": "lead",
            "target_basis": "own", "target_cost": 999,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["value"], 999)
        self.assertEqual(result["basis"], "own")
        self.assertEqual(result["result_kind"], "lead")
        self.assertEqual(result["missing"], [])

    def test_own_cap_still_carries_break_even_and_price(self):
        # The ruler's 打平 mark and ROAS 參考 (price / cap) read these even when an own cap wins.
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "target_basis": "own", "target_cost": 250, "target_revision": 3,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["value"], 250)
        self.assertEqual(result["basis"], "own")
        self.assertEqual(result["own_value"], 250)
        self.assertEqual(result["break_even"], 300)
        self.assertEqual(result["price"], 500)
        self.assertEqual(result["product_id"], product_id)
        self.assertEqual(result["result_label"], "購買")
        self.assertEqual(result["revision"], 3)

    # -- F29 Contract D: `cost` (成本含運) beside break-even --------------------------------------

    def test_cost_is_unit_cost_plus_shipping_from_the_break_even_row(self):
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["cost"], 200)  # 150 + 50
        self.assertEqual(result["price"] - result["cost"], result["break_even"])

    def test_cost_rides_along_with_an_own_cap(self):
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "target_basis": "own", "target_cost": 250,
            "context_json": {"product_ids": [product_id]},
        }
        self.assertEqual(targets.resolve(web.conn, self.org_id, self.brand_id, campaign)["cost"],
                         200)

    def test_price_without_cost_has_no_cost(self):
        product_id = self._product(unit_variable_cost=None)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["price"], 500)  # the price is still known...
        self.assertIsNone(result["cost"])  # ...but shipping alone is never a cost
        self.assertIsNone(result["break_even"])

    def test_non_purchase_result_kind_has_no_cost(self):
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": "lead",
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["cost"])
        self.assertIsNone(result["price"])

    def test_target_endpoint_carries_cost(self):
        product_id = self._product(unit_variable_cost=150)
        campaign_id = self._imported_campaign_with_objective("OUTCOME_SALES", product_id=product_id)
        view = repository.get_campaign_target(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertEqual((view["basis"], view["break_even"], view["cost"]),
                         ("break_even", 300, 200))

    # -- result_kind provenance: the real Meta adapter mapping, never a dict literal ------------

    def test_imported_sales_objective_from_meta_resolves_break_even(self):
        product_id = self._product(unit_variable_cost=150)
        campaign_id = self._imported_campaign_with_objective("OUTCOME_SALES", product_id=product_id)
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertEqual(campaign["result_kind"], "purchase")
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "break_even")
        self.assertEqual(result["value"], 300)  # 500 - 150 - 50
        self.assertEqual(result["result_kind"], "purchase")

    def test_imported_unmapped_objective_from_meta_is_missing_not_zero(self):
        campaign_id = self._imported_campaign_with_days([], objective="OUTCOME_AWARENESS")
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertIsNone(campaign["result_kind"])
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertEqual(result["missing"], ["result_kind"])


if __name__ == "__main__":
    unittest.main()
