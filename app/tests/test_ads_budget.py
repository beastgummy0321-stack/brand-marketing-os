"""app/tests/test_ads_budget.py — F03-I04 falsifiers: breakeven/target CPA never guess a margin,
cold-start scenarios are 2/5/10x target CPA with the 冷啟動估算 flag, history scenarios are
x0.6/x1/x1.6 of the previous daily budget with the sample named, and `split` always sums exactly
to the total.
"""

import unittest

import app.shared.web as web
from app.ads import budget
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb


class BreakevenCpaTest(unittest.TestCase):
    def test_breakeven_is_price_minus_cost_minus_shipping(self):
        economics = {"selling_price": 500, "unit_variable_cost": 150, "shipping_cost": 50}
        self.assertEqual(budget.breakeven_cpa(economics), 300)

    def test_breakeven_without_shipping_defaults_to_zero(self):
        economics = {"selling_price": 500, "unit_variable_cost": 150, "shipping_cost": None}
        self.assertEqual(budget.breakeven_cpa(economics), 350)

    def test_missing_unit_variable_cost_returns_none_not_a_guess(self):
        economics = {"selling_price": 500, "unit_variable_cost": None, "shipping_cost": 50}
        self.assertIsNone(budget.breakeven_cpa(economics))

    def test_missing_economics_row_returns_none(self):
        self.assertIsNone(budget.breakeven_cpa(None))

    def test_target_cpa_is_070_of_breakeven(self):
        self.assertAlmostEqual(budget.target_cpa(300), 210)

    def test_target_cpa_of_none_is_none(self):
        self.assertIsNone(budget.target_cpa(None))


class ScenariosTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心預算", client_name=None,
            actor="測試員",
        )
        self.brand_id = self.brand["id"]
        self.product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor="測試員")["id"]

    def test_cold_start_scenarios_are_2_5_10x_target_cpa_and_flagged(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=10,
            history=None,
        )
        self.assertEqual(result["mode"], "cold_start")
        by_key = {row["key"]: row for row in result["scenarios"]}
        target = budget.target_cpa(300)  # 210
        self.assertAlmostEqual(by_key["minimum"]["daily"], round(target * 2))
        self.assertAlmostEqual(by_key["recommended"]["daily"], round(target * 5))
        self.assertAlmostEqual(by_key["aggressive"]["daily"], round(target * 10))
        for row in result["scenarios"]:
            self.assertIn("冷啟動估算", row["caption"])
            self.assertEqual(row["total"], row["daily"] * 10)
        self.assertEqual(result["recommended"], "recommended")

    def test_missing_economics_yields_no_fabricated_scenario_numbers(self):
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=10,
            history=None,
        )
        self.assertEqual(result["mode"], "cold_start")
        for row in result["scenarios"]:
            self.assertIsNone(row["daily"])
            self.assertIsNone(row["total"])

    def test_history_scenarios_are_06_1_16x_previous_daily_and_name_the_sample(self):
        history = {"cpa": 280, "last_daily_budget": 1000, "sample_days": 27, "sample_ads": 4}
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        self.assertEqual(result["mode"], "history")
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["conservative"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1000)
        self.assertEqual(by_key["aggressive"]["daily"], 1600)
        self.assertEqual(by_key["recommended"]["total"], 7000)
        self.assertEqual(result["basis"]["cpa"], 280)
        self.assertEqual(result["basis"]["sample_days"], 27)
        self.assertEqual(result["basis"]["sample_ads"], 4)


class SplitTest(unittest.TestCase):
    def test_split_sums_exactly_to_total_for_an_awkward_amount(self):
        rows = budget.split(30001, {"新客": 0.5, "再行銷": 0.3, "探索": 0.2})
        self.assertEqual(sum(row["amount"] for row in rows), 30001)
        by_label = {row["label"]: row["amount"] for row in rows}
        self.assertEqual(by_label["新客"], 15001)  # remainder goes to the largest share
        self.assertEqual(by_label["再行銷"], 9000)
        self.assertEqual(by_label["探索"], 6000)

    def test_split_empty_weights_returns_empty(self):
        self.assertEqual(budget.split(1000, {}), [])


if __name__ == "__main__":
    unittest.main()
