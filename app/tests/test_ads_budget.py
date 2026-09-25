"""app/tests/test_ads_budget.py — F03-I04 falsifiers: breakeven never guesses a margin,
cold-start scenarios are 2/5/10x the one cap (F28-I01) with the 冷啟動估算 flag, history
scenarios are x0.6/x1/x1.6 of the previous daily budget with the sample named, and `split`
always sums exactly to the total.
"""

import unittest
from datetime import date

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

    def test_no_ratio_constant_survives(self):
        # F28-I01: cold start multiplies the resolved cap itself -- no 0.7 on top of it.
        self.assertFalse(hasattr(budget, "TARGET_CPA_RATIO"))
        self.assertFalse(hasattr(budget, "target_cpa"))


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

    def test_cold_start_scenarios_are_2_5_10x_the_cap_and_flagged(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=10,
            history=None, cap=300,
        )
        self.assertEqual(result["mode"], "cold_start")
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["minimum"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1500)
        self.assertEqual(by_key["aggressive"]["daily"], 3000)
        for row in result["scenarios"]:
            self.assertIn("冷啟動估算", row["caption"])
            self.assertIn("上限", row["caption"])
            self.assertEqual(row["total"], row["daily"] * 10)
        self.assertEqual(result["recommended"], "recommended")
        self.assertEqual(result["basis"]["cap"], 300)
        self.assertEqual(result["basis"]["product_id"], self.product_id)

    def test_no_cap_yields_no_fabricated_scenario_numbers(self):
        # Product economics alone never turn into a number here: the caller resolves the cap.
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
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
        for row in result["scenarios"]:
            self.assertIn("上一期日預算", row["caption"])
            self.assertNotIn("中位數", row["caption"])

    def test_history_caption_never_mentions_cpa_median_when_cpa_absent(self):
        history = {"last_daily_budget": 1000, "sample_days": 5, "sample_ads": 1}
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        for row in result["scenarios"]:
            self.assertNotIn("中位數", row["caption"])
            self.assertNotIn("CPA", row["caption"])

    def test_history_caption_names_the_source_when_given_and_amount_is_unchanged(self):
        """F05-I11: `source_text` 只換 caption 開頭那句話，三張卡的金額不動。"""
        history = {
            "cpa": 280, "last_daily_budget": 1000, "sample_days": 30, "sample_ads": None,
            "source": "meta_account", "source_text": "Meta 近 30 天平均日花費",
        }
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["conservative"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1000)
        self.assertEqual(by_key["aggressive"]["daily"], 1600)
        for row in result["scenarios"]:
            self.assertIn("Meta 近 30 天平均日花費", row["caption"])
        self.assertEqual(result["basis"]["source"], "meta_account")


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


class BudgetCapScenariosTest(unittest.TestCase):
    """F28-I03 (ads.md §6.32 "Budget cap is a soft warning"): `current_scenarios` reads the
    campaign's budget cap (`constraints_json.budget`) on every read -- `budget_cap`, per-row
    `over_cap`, the 照預算上限 row, and `recommended` moving to it when the old pick is over."""

    START, END = date(2026, 10, 1), date(2026, 10, 10)  # 10 days

    def _campaign(self, budget_cap=None, *, dates=True) -> dict:
        constraints = {} if budget_cap is None else {"budget": budget_cap}
        return {
            "start_date": self.START if dates else None, "end_date": self.END if dates else None,
            "constraints_json": constraints,
        }

    def _cold(self, budget_cap=None, *, cap=300, dates=True) -> dict:
        return budget.current_scenarios(
            {"mode": "cold_start"}, self._campaign(budget_cap, dates=dates), cap=cap,
        )

    def test_no_cap_unset_zero_negative_or_junk_adds_nothing(self):
        for value in (None, 0, -5, "abc", True, float("nan")):
            with self.subTest(value=value):
                result = self._cold(value)
                self.assertIsNone(result["budget_cap"])
                self.assertEqual([r["key"] for r in result["scenarios"]],
                                 ["minimum", "recommended", "aggressive"])
                self.assertTrue(all(r["over_cap"] is None for r in result["scenarios"]))
                self.assertEqual(result["recommended"], "recommended")

    def test_cold_start_labels(self):
        labels = [r["label"] for r in self._cold()["scenarios"]]
        self.assertEqual(labels, ["最低", "穩定成長", "積極"])

    def test_cap_row_and_over_amounts_when_the_recommendation_fits(self):
        # 300 x 2/5/10 x 10 days = 6000 / 15000 / 30000
        result = self._cold(20000)
        self.assertEqual(result["budget_cap"], 20000)
        rows = result["scenarios"]
        self.assertEqual([r["key"] for r in rows],
                         ["minimum", "cap", "recommended", "aggressive"])
        cap_row = rows[1]
        self.assertEqual((cap_row["label"], cap_row["daily"], cap_row["total"]),
                         ("照預算上限", 2000, 20000))
        self.assertEqual([r["over_cap"] for r in rows], [0, 0, 0, 10000])
        self.assertEqual(result["recommended"], "recommended")

    def test_recommended_moves_to_cap_when_it_is_over(self):
        result = self._cold(12000)
        self.assertEqual(result["recommended"], "cap")
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertEqual(by_key["recommended"]["over_cap"], 3000)

    def test_cap_exactly_equal_to_a_total_is_not_over(self):
        result = self._cold(15000)
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertEqual(by_key["recommended"]["over_cap"], 0)
        self.assertEqual(result["recommended"], "recommended")

    def test_unknown_totals_are_never_over(self):
        result = self._cold(12000, cap=None)  # no cost-per-result cap -> no amounts
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertIsNone(by_key["recommended"]["total"])
        self.assertIsNone(by_key["recommended"]["over_cap"])
        self.assertEqual(by_key["cap"]["total"], 12000)
        self.assertEqual(result["recommended"], "recommended")

    def test_days_unknown_keeps_the_cap_total_without_a_daily(self):
        result = self._cold(12000, dates=False)
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertIsNone(by_key["cap"]["daily"])
        self.assertEqual(by_key["cap"]["total"], 12000)
        self.assertIsNone(by_key["aggressive"]["over_cap"])

    def test_numeric_string_cap_from_the_wizard_is_read(self):
        self.assertEqual(self._cold("20,000")["budget_cap"], 20000)

    def test_stored_history_snapshot_reconciles_idempotently_with_new_labels(self):
        stored = {
            "mode": "history", "recommended": "cap", "basis": {},
            "scenarios": [
                {"key": "conservative", "label": "保守", "daily": 600, "total": 1, "caption": "x"},
                {"key": "cap", "label": "照預算上限", "daily": 1, "total": 1, "caption": "x"},
                {"key": "recommended", "label": "推薦", "daily": 1000, "total": 1, "caption": "x"},
                {"key": "aggressive", "label": "積極", "daily": 1600, "total": 1, "caption": "x"},
            ],
        }
        campaign = self._campaign(20000)
        once = budget.current_scenarios(stored, campaign)
        twice = budget.current_scenarios(once, campaign)
        self.assertEqual(once, twice)
        self.assertEqual([r["key"] for r in once["scenarios"]],
                         ["conservative", "cap", "recommended", "aggressive"])
        self.assertEqual([r["label"] for r in once["scenarios"]],
                         ["保守", "照預算上限", "照上一期", "積極"])
        self.assertEqual([r["total"] for r in once["scenarios"]], [6000, 20000, 10000, 16000])
        self.assertEqual(once["recommended"], "recommended")  # 10000 fits under 20000
        # Lowering the cap moves the recommendation; clearing it drops the row again.
        lower = budget.current_scenarios(once, self._campaign(8000))
        self.assertEqual(lower["recommended"], "cap")
        cleared = budget.current_scenarios(lower, self._campaign(None))
        self.assertNotIn("cap", [r["key"] for r in cleared["scenarios"]])
        self.assertEqual(cleared["recommended"], "recommended")
