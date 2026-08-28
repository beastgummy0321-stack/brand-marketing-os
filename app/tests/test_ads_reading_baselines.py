"""app/tests/test_ads_reading_baselines.py — 票 10-split-reading-py：品牌基線純函數測試。

從 app/tests/test_ads_reading.py 搬過來，原樣不改——鏡射 app/ads/reading_baselines.py
的拆檔（見該檔開頭說明）。純函數測試，不需要 app.main 那套資料庫／FastAPI 骨架。
"""

import unittest

from app.ads import reading


class SeasonLabelTest(unittest.TestCase):
    """票 #39：基線兩條並列＋旺淡季標注，用「去年同期」vs「全年平均」的比值判斷。"""

    def test_same_period_much_higher_than_annual_is_peak_season(self):
        result = reading._season_label({"roas": 3.0}, {"roas": 2.0})
        self.assertEqual(result["level"], "peak")

    def test_same_period_much_lower_than_annual_is_low_season(self):
        result = reading._season_label({"roas": 1.0}, {"roas": 2.0})
        self.assertEqual(result["level"], "low")

    def test_close_to_annual_average_is_typical(self):
        result = reading._season_label({"roas": 2.1}, {"roas": 2.0})
        self.assertEqual(result["level"], "typical")

    def test_missing_either_side_says_so_honestly(self):
        result = reading._season_label({}, {"roas": 2.0})
        self.assertIsNone(result["level"])
        self.assertTrue(result["label"])  # 有誠實的說明文字，不比對確切文案
