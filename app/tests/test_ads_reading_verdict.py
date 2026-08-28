"""app/tests/test_ads_reading_verdict.py — 票 10-split-reading-py：判讀結論周邊純函數測試。

從 app/tests/test_ads_reading.py 搬過來，原樣不改——鏡射 app/ads/reading_verdict.py
的拆檔（見該檔開頭說明）。純函數測試，不需要 app.main 那套資料庫／FastAPI 骨架。
"""

import unittest

from app.ads import reading


class BreakevenTest(unittest.TestCase):
    def test_breakeven_comes_from_margin_not_a_fixed_number(self):
        """毛利率 40% 要 2.5 倍才回本；毛利率 70% 只要 1.43 倍。"""
        low = reading.breakeven_roas({"selling_price": 1000, "unit_variable_cost": 600})
        high = reading.breakeven_roas({"selling_price": 1000, "unit_variable_cost": 300})
        self.assertEqual(low, 2.5)
        self.assertEqual(high, 1.43)

    def test_unknown_economics_returns_none_not_a_guess(self):
        self.assertIsNone(reading.breakeven_roas(None))
        self.assertIsNone(reading.breakeven_roas({"selling_price": 100,
                                                  "unit_variable_cost": 150}))


class RepurchaseBreakevenTest(unittest.TestCase):
    """票 #39：回購實質打平線＝首單打平線 ÷ 回購倍數（fixture 驗算）。"""

    def test_multiplier_lowers_the_breakeven_line(self):
        self.assertEqual(reading.repurchase_breakeven_roas(1.67, 2.0), 0.83)

    def test_missing_first_order_breakeven_returns_none(self):
        self.assertIsNone(reading.repurchase_breakeven_roas(None, 2.0))

    def test_missing_multiplier_returns_none(self):
        """樣本不足時 multiplier 是 None，實質線就不該存在（票 #39 驗收條件）。"""
        self.assertIsNone(reading.repurchase_breakeven_roas(1.67, None))


class VerdictShiftTest(unittest.TestCase):
    """翻盤分級規則寫死在程式（票 #38，決策 0025：「翻盤警示分級——微調不吵、判定翻盤才進佇列」）。"""

    def test_unchanged_status_is_unchanged(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "scale_candidate"), "unchanged")

    def test_positive_to_negative_is_a_reversal(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "pause_candidate"), "reversal")
        self.assertEqual(
            reading.classify_verdict_shift("maintain", "pause_candidate"), "reversal")

    def test_negative_to_positive_is_also_a_reversal(self):
        self.assertEqual(
            reading.classify_verdict_shift("pause_candidate", "maintain"), "reversal")

    def test_move_within_the_same_group_is_just_an_adjustment(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "maintain"), "adjustment")

    def test_move_involving_an_uncertain_status_is_not_a_reversal(self):
        """還看不準／學習期是中間群，不跟正負任一群構成翻盤——不確定不是結論反轉。"""
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "learning"), "adjustment")
        self.assertEqual(
            reading.classify_verdict_shift("pause_candidate", "insufficient_data"), "adjustment")
