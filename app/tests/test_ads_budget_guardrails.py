# -*- coding: utf-8 -*-
"""app/tests/test_ads_budget_guardrails.py — 票 3 兩個純函數模組的邊界測試。

這兩支算的是錢與「要不要加碼」，所以測的重點放在邊界與守恆，而不是覆誦正常路徑：
四捨五入會不會把錢算丟、門檻的兩側行為對不對、樣本數剛好落在階梯邊界時取哪一級。
"""

import unittest

from app.ads import budget, guardrails


class PlanFromPainTest(unittest.TestCase):
    def test_default_is_two_weeks(self):
        plan = budget.plan_from_pain(6000)
        self.assertEqual(plan.duration_days, 14)
        self.assertEqual(plan.daily_budget, 428.57)
        self.assertFalse(plan.daily_below_floor)

    def test_shortens_cycle_to_lift_daily_budget(self):
        """金額不夠撐 14 天時縮短檔期，把日預算墊到實務下限之上。"""
        plan = budget.plan_from_pain(3000)  # 14 天的話日預算只有 214，低於下限 300
        self.assertEqual(plan.duration_days, 10)
        self.assertEqual(plan.daily_budget, 300.0)
        self.assertFalse(plan.daily_below_floor)

    def test_never_shorter_than_floor_duration(self):
        """金額太小就守住 7 天，寧可日預算不足也不讓檔期短到無法判讀，並誠實標記。"""
        plan = budget.plan_from_pain(1000)
        self.assertEqual(plan.duration_days, 7)
        self.assertTrue(plan.daily_below_floor)

    def test_never_longer_than_max_duration(self):
        """錢多是每天多花，不是讓使用者等更久。"""
        plan = budget.plan_from_pain(500000)
        self.assertEqual(plan.duration_days, 14)

    def test_stop_loss_and_pause_threshold(self):
        plan = budget.plan_from_pain(14000)
        self.assertEqual(plan.daily_budget, 1000.0)
        self.assertEqual(plan.daily_stop_loss, 1500.0)
        self.assertEqual(plan.pause_threshold_spend, 7000.0)

    def test_rejects_non_positive(self):
        for value in (0, -1):
            with self.assertRaises(ValueError):
                budget.plan_from_pain(value)


class DailyBudgetForTest(unittest.TestCase):
    """票 3：使用者自訂檔期長度時，日預算改用單純除法重算（不再套自動縮短天數的演算法）。"""

    def test_divides_total_by_chosen_days(self):
        daily, below_floor = budget.daily_budget_for(6000, 30)
        self.assertEqual(daily, 200.0)
        self.assertTrue(below_floor)

    def test_above_floor_is_not_flagged(self):
        daily, below_floor = budget.daily_budget_for(6000, 7)
        self.assertEqual(daily, 857.14)
        self.assertFalse(below_floor)

    def test_rejects_non_positive_days(self):
        with self.assertRaises(ValueError):
            budget.daily_budget_for(1000, 0)


class DurationCommentaryTest(unittest.TestCase):
    """天數變動的即時短評：太短／適中／偏長三段。"""

    def test_short_tier(self):
        self.assertEqual(budget.duration_commentary(7)["tier"], "short")
        self.assertEqual(budget.duration_commentary(9)["tier"], "short")

    def test_moderate_tier(self):
        self.assertEqual(budget.duration_commentary(10)["tier"], "moderate")
        self.assertEqual(budget.duration_commentary(14)["tier"], "moderate")
        self.assertEqual(budget.duration_commentary(21)["tier"], "moderate")

    def test_long_tier(self):
        self.assertEqual(budget.duration_commentary(22)["tier"], "long")
        self.assertEqual(budget.duration_commentary(30)["tier"], "long")

    def test_every_tier_has_a_plain_language_note(self):
        for days in (7, 14, 21, 30):
            note = budget.duration_commentary(days)["note"]
            self.assertTrue(note)
            self.assertNotIn("_", note)  # 鐵則 12：人話，不出現內部代號


class SplitBudgetTest(unittest.TestCase):
    def test_allocates_by_gross_margin(self):
        parts = budget.split_budget(9000, [
            {"product_id": "A", "economics": {"selling_price": 1000, "unit_variable_cost": 400}},
            {"product_id": "B", "economics": {"selling_price": 500, "unit_variable_cost": 200}},
        ])
        # 毛利 600 : 300 = 2 : 1
        self.assertEqual([p.allocated_budget for p in parts], [6000.0, 3000.0])
        self.assertTrue(all(p.allocation_basis == "economics" for p in parts))

    def test_missing_economics_uses_average_and_flags(self):
        parts = budget.split_budget(10000, [
            {"product_id": "A", "economics": {"selling_price": 1000, "unit_variable_cost": 400}},
            {"product_id": "B", "economics": None},
        ])
        self.assertEqual([p.allocation_basis for p in parts], ["economics", "estimated"])
        self.assertEqual([p.economics_missing for p in parts], [False, True])
        # 只有一個已知毛利，平均＝它自己，所以兩者對半分
        self.assertEqual([p.allocated_budget for p in parts], [5000.0, 5000.0])

    def test_all_missing_falls_back_to_even(self):
        parts = budget.split_budget(1000, [
            {"product_id": "A", "economics": None},
            {"product_id": "B", "economics": {}},
        ])
        self.assertTrue(all(p.allocation_basis == "even" for p in parts))
        self.assertTrue(all(p.economics_missing for p in parts))
        self.assertEqual([p.allocated_budget for p in parts], [500.0, 500.0])

    def test_non_positive_margin_treated_as_missing(self):
        """毛利 ≤ 0 不該被靜靜分到 0 元——那等於系統替使用者決定不投這個產品。"""
        parts = budget.split_budget(1000, [
            {"product_id": "A", "economics": {"selling_price": 1000, "unit_variable_cost": 400}},
            {"product_id": "B", "economics": {"selling_price": 100, "unit_variable_cost": 150}},
        ])
        self.assertTrue(parts[1].economics_missing)
        self.assertGreater(parts[1].allocated_budget, 0)

    def test_shipping_cost_counted(self):
        parts = budget.split_budget(1000, [
            {"product_id": "A", "economics": {"selling_price": 1000, "unit_variable_cost": 400,
                                              "shipping_cost": 100}},
            {"product_id": "B", "economics": {"selling_price": 1000, "unit_variable_cost": 400}},
        ])
        # A 毛利 500、B 毛利 600
        self.assertLess(parts[0].allocated_budget, parts[1].allocated_budget)

    def test_sum_always_equals_total(self):
        """四捨五入不能把錢算丟——除不盡的組合逐一驗加總守恆。"""
        cases = [
            (10000, 3), (999.99, 7), (1, 3), (12345.67, 6), (100, 9), (7777, 11),
        ]
        for total, count in cases:
            products = [{"product_id": f"P{i}", "economics": {"selling_price": 100 + i,
                                                              "unit_variable_cost": 10}}
                        for i in range(count)]
            parts = budget.split_budget(total, products)
            self.assertAlmostEqual(sum(p.allocated_budget for p in parts), total, places=2,
                                   msg=f"total={total} count={count} 加總對不上")

    def test_empty_and_invalid(self):
        self.assertEqual(budget.split_budget(1000, []), [])
        with self.assertRaises(ValueError):
            budget.split_budget(0, [{"product_id": "A", "economics": None}])


class ReconcileTest(unittest.TestCase):
    def test_within_normal_fluctuation_is_silent(self):
        """Meta 本來就允許單日超出約 25%，14% 的偏移報警就是狼來了。"""
        self.assertEqual(guardrails.reconcile({"total_budget": 10000}, {"spend": 11400}), [])

    def test_info_and_warn_thresholds(self):
        info = guardrails.reconcile({"total_budget": 10000}, {"spend": 11500})
        self.assertEqual([f.severity for f in info], ["info"])
        warn = guardrails.reconcile({"total_budget": 10000}, {"spend": 12500})
        self.assertEqual([f.severity for f in warn], ["warn"])

    def test_underspend_is_also_caught(self):
        under = guardrails.reconcile({"total_budget": 10000}, {"spend": 7000})
        self.assertEqual([f.code for f in under], ["spend_under_plan"])

    def test_daily_budget_and_schedule_mismatch(self):
        findings = guardrails.reconcile(
            {"total_budget": 10000, "daily_budget": 700, "start_date": "2026-08-01"},
            {"spend": 10000, "daily_budget": 1000, "start_date": "2026-08-05"},
        )
        self.assertEqual({f.code for f in findings},
                         {"daily_budget_mismatch", "start_date_mismatch"})

    def test_missing_actuals_are_skipped(self):
        """CSV 軌只拿得到花費，缺的欄位不該被當成不符。"""
        self.assertEqual(
            guardrails.reconcile({"total_budget": 10000, "daily_budget": 700}, {"spend": 10000}),
            [],
        )

    def test_message_has_no_internal_codes(self):
        findings = guardrails.reconcile({"total_budget": 10000}, {"spend": 13000})
        self.assertNotIn("_", findings[0].message)  # 鐵則 12：人話，不出現 code 之類代號


class SelfAnswerTest(unittest.TestCase):
    def test_all_clear_produces_nothing(self):
        self.assertEqual(guardrails.self_answer_findings(
            {"budget_same": True, "schedule_same": True, "other_campaign_running": False}), [])

    def test_unanswered_is_not_a_problem(self):
        """自答是補充資訊，不是新的必填關卡——沒答不能當成有問題。"""
        self.assertEqual(guardrails.self_answer_findings({}), [])
        self.assertEqual(guardrails.self_answer_findings({"budget_same": None}), [])

    def test_each_question_maps_to_a_finding(self):
        findings = guardrails.self_answer_findings(
            {"budget_same": False, "schedule_same": False, "other_campaign_running": True})
        self.assertEqual({f.code for f in findings},
                         {"daily_budget_mismatch", "schedule_mismatch", "concurrent_campaign"})
        self.assertTrue(all(f.source == "self_answer" for f in findings))

    def test_same_shape_as_api_diff(self):
        """降級版與 API 比對必須是同一種結構，日後接上 API 下游不用改。"""
        api = guardrails.reconcile({"total_budget": 10000, "daily_budget": 700},
                                   {"spend": 10000, "daily_budget": 1000})[0]
        self_answered = guardrails.self_answer_findings({"budget_same": False})[0]
        self.assertEqual(api.code, self_answered.code)
        self.assertEqual(type(api), type(self_answered))


class ConfidenceTest(unittest.TestCase):
    def test_clean_run_is_full_confidence(self):
        self.assertEqual(guardrails.confidence_from_findings([]), 1.0)

    def test_penalties_accumulate_and_clamp(self):
        many = guardrails.self_answer_findings(
            {"budget_same": False, "schedule_same": False, "other_campaign_running": True})
        self.assertEqual(guardrails.confidence_from_findings(many), 0.1)
        self.assertGreaterEqual(guardrails.confidence_from_findings(many * 5), 0.0)


class ScaleCapTest(unittest.TestCase):
    def test_ladder_boundaries(self):
        self.assertEqual(guardrails.cap_scale_up(1000, 29).cap_ratio, 0.20)
        self.assertEqual(guardrails.cap_scale_up(1000, 30).cap_ratio, 0.50)
        self.assertEqual(guardrails.cap_scale_up(1000, 99).cap_ratio, 0.50)
        self.assertEqual(guardrails.cap_scale_up(1000, 100).cap_ratio, 1.50)

    def test_zero_conversions_is_most_conservative(self):
        self.assertEqual(guardrails.cap_scale_up(1000, 0).max_budget, 1200.0)

    def test_proposal_under_cap_is_not_capped(self):
        cap = guardrails.cap_scale_up(1000, 10, proposed_budget=1100)
        self.assertFalse(cap.capped)
        self.assertIsNone(cap.finding)

    def test_proposal_over_cap_is_capped_with_explanation(self):
        cap = guardrails.cap_scale_up(1000, 10, proposed_budget=10000)
        self.assertTrue(cap.capped)
        self.assertEqual(cap.max_budget, 1200.0)
        self.assertEqual(cap.finding.code, "scale_up_capped")
        # 保守起見壓預算不代表資料有疑慮，不該扣判讀可信度
        self.assertEqual(cap.finding.confidence_penalty, 0.0)

    def test_rejects_non_positive_budget(self):
        with self.assertRaises(ValueError):
            guardrails.cap_scale_up(0, 10)


class DataSanityTest(unittest.TestCase):
    def test_clean_row_passes(self):
        self.assertEqual(guardrails.check_data_sanity(
            {"impressions": 1000, "clicks": 50, "spend": 500}), [])

    def test_clicks_over_impressions(self):
        findings = guardrails.check_data_sanity({"impressions": 100, "clicks": 500})
        self.assertEqual([f.code for f in findings], ["ctr_impossible"])

    def test_negative_values(self):
        findings = guardrails.check_data_sanity({"spend": -100, "conversions": -1})
        self.assertEqual([f.code for f in findings], ["negative_value", "negative_value"])

    def test_future_date_only_checked_when_today_given(self):
        row = {"as_of_date": "2099-01-01"}
        self.assertEqual(guardrails.check_data_sanity(row), [])
        self.assertEqual([f.code for f in guardrails.check_data_sanity(row, today="2026-07-31")],
                         ["future_date"])

    def test_zero_values_are_not_flagged(self):
        """花費 0、轉換 0 是常見的正常情形（還沒開始跑），不能當成壞資料。"""
        self.assertEqual(guardrails.check_data_sanity(
            {"impressions": 0, "clicks": 0, "spend": 0, "conversions": 0}), [])


if __name__ == "__main__":
    unittest.main()
