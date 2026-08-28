"""app/tests/test_ads_pacing_curve.py — 票 pacing-curve 兩個純函數的邊界測試。

比照 test_ads_budget_guardrails.py 的既有風格：重點放在邊界與守恆（四捨五入會不會把
錢算丟、天數門檻兩側行為對不對），不是覆誦正常路徑。
"""

import unittest

from app.ads import budget, pacing_curve


class RecommendPacingStrategyTest(unittest.TestCase):
    """四種輸入組合（短天數/長天數 × 有無優惠）全部覆蓋。"""

    def test_short_duration_with_offer_still_continuous(self):
        strategy, reason = pacing_curve.recommend_pacing_strategy(7, has_offer=True)
        self.assertEqual(strategy, "continuous")
        self.assertIn("太短", reason)

    def test_short_duration_without_offer_is_continuous(self):
        strategy, _ = pacing_curve.recommend_pacing_strategy(13, has_offer=False)
        self.assertEqual(strategy, "continuous")

    def test_long_duration_with_offer_is_pulse(self):
        strategy, reason = pacing_curve.recommend_pacing_strategy(21, has_offer=True)
        self.assertEqual(strategy, "pulse")
        self.assertIn("優惠", reason)

    def test_long_duration_without_offer_is_still_continuous(self):
        """沒有優惠訊號時不預設脈動——脈動的正當性建立在限時優惠上。"""
        strategy, _ = pacing_curve.recommend_pacing_strategy(21, has_offer=False)
        self.assertEqual(strategy, "continuous")

    def test_boundary_14_days_is_not_short(self):
        strategy, _ = pacing_curve.recommend_pacing_strategy(14, has_offer=True)
        self.assertEqual(strategy, "pulse")
        strategy, _ = pacing_curve.recommend_pacing_strategy(13, has_offer=True)
        self.assertEqual(strategy, "continuous")

    def test_reason_is_plain_language(self):
        for duration, offer in ((7, True), (21, True), (21, False)):
            _, reason = pacing_curve.recommend_pacing_strategy(duration, has_offer=offer)
            self.assertNotIn("_", reason)  # 鐵則 12：人話，不出現內部代號


class ComputeCurveTest(unittest.TestCase):
    def test_continuous_every_day_is_the_same_value(self):
        """ADR 0010 第四節：連續策略每天是同一個值，不套餘數分配。"""
        days = pacing_curve.compute_curve("continuous", 14, 10000)
        self.assertEqual(len(days), 14)
        self.assertTrue(all(d["budget"] == 714.29 for d in days))
        self.assertTrue(all(d["phase"] == "normal" for d in days))

    def test_pulse_sums_exactly_to_total_budget(self):
        for total, duration in ((10000, 14), (12345.67, 17), (999.99, 30), (7000, 21)):
            days = pacing_curve.compute_curve("pulse", duration, total)
            self.assertEqual(len(days), duration)
            self.assertAlmostEqual(sum(d["budget"] for d in days), total, places=2,
                                   msg=f"total={total} duration={duration} 加總對不上")

    def test_intermittent_sums_exactly_to_total_budget(self):
        for total, duration in ((10000, 14), (12345.67, 17), (999.99, 30), (7000, 21)):
            days = pacing_curve.compute_curve("intermittent", duration, total)
            self.assertEqual(len(days), duration)
            self.assertAlmostEqual(sum(d["budget"] for d in days), total, places=2,
                                   msg=f"total={total} duration={duration} 加總對不上")

    def test_pulse_phase_order_and_sprint_is_highest_intensity(self):
        """衝刺期強度最高，不是高潮期——截止日效應（ADR 0010 第一節）。"""
        days = pacing_curve.compute_curve("pulse", 14, 10000)
        phases = [d["phase"] for d in days]
        self.assertEqual(phases[0], "warmup")
        self.assertEqual(phases[-1], "sprint")
        self.assertIn("peak", phases)
        warmup_budget = next(d["budget"] for d in days if d["phase"] == "warmup")
        peak_budget = next(d["budget"] for d in days if d["phase"] == "peak")
        sprint_budget = next(d["budget"] for d in days if d["phase"] == "sprint")
        self.assertLess(warmup_budget, peak_budget)
        self.assertLess(peak_budget, sprint_budget)

    def test_intermittent_reduced_day_has_a_floor(self):
        """降量日下限沿用既有 budget.MIN_DAILY_BUDGET，不新發明門檻——小預算時不能砍到 0。"""
        days = pacing_curve.compute_curve("intermittent", 15, 3000)  # 平均日預算 200，4 成只有 80
        reduced = [d["budget"] for d in days if d["phase"] == "reduced"]
        self.assertTrue(reduced)
        # 除了可能吸收餘數的最後一天，其餘降量日都不該低於下限太多
        self.assertTrue(all(b >= budget.MIN_DAILY_BUDGET - 1 for b in reduced[:-1]))

    def test_intermittent_cycle_pattern_is_two_normal_one_reduced(self):
        days = pacing_curve.compute_curve("intermittent", 14, 10000)
        phases = [d["phase"] for d in days]
        self.assertEqual(phases[:6], ["normal", "normal", "reduced",
                                      "normal", "normal", "reduced"])

    def test_stop_loss_uses_existing_multiplier(self):
        days = pacing_curve.compute_curve("continuous", 14, 10000)
        for d in days:
            self.assertEqual(d["stop_loss"], round(d["budget"] * budget.DAILY_STOP_LOSS_MULTIPLIER, 2))

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            pacing_curve.compute_curve("continuous", 0, 10000)
        with self.assertRaises(ValueError):
            pacing_curve.compute_curve("continuous", 14, 0)

    def test_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            pacing_curve.compute_curve("random", 14, 10000)


if __name__ == "__main__":
    unittest.main()
