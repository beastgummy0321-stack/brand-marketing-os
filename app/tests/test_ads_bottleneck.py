"""app/tests/test_ads_bottleneck.py — 票 C2-01：瓶頸判斷樹（CPA 恆等式拆解）純函數測試。

`bottleneck.diagnose()` 比照 `reading.judge()` 的慣例：純函數，不碰資料庫，`conn` 可傳
None（規則卡讀不到就退回預設值，見 app/core/rule_cards.get_value）。這裡不需要
app.main 那套資料庫／FastAPI 骨架，跟 test_ads_reading_baselines.py 同一種輕量寫法。
"""

import unittest

from app.ads import bottleneck, reading


def _totals(*, impressions, clicks, spend, conversions, revenue=0.0, max_frequency=None):
    row = {"impressions": impressions, "clicks": clicks, "spend": spend,
          "conversions": conversions, "revenue": revenue}
    if max_frequency is not None:
        row["max_frequency"] = max_frequency
    return row


class CpaIdentityTest(unittest.TestCase):
    """CPA = (CPM/1000) / (CTR × CVR) 是恆等式，不是啟發式——三個 ratio 相乘必須等於 cpa_ratio。"""

    def _degraded_on_all_three(self):
        # impressions=100000, spend=24000 → cpm=240；clicks=500 → ctr=0.005；
        # conversions=10 → cvr=0.02。基線 cpm=200／ctr=0.01／cvr=0.025，三個因子都變差。
        totals = _totals(impressions=100000, clicks=500, spend=24000, conversions=10)
        baseline = {"cpm": 200.0, "ctr": 0.01, "cvr": 0.025}
        return bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")

    def test_three_ratios_multiply_to_cpa_ratio(self):
        result = self._degraded_on_all_three()
        product = 1.0
        for factor in result["factors"]:
            product *= factor["ratio"]
        self.assertAlmostEqual(product, result["cpa_ratio"], places=6)

    def test_shares_sum_to_one(self):
        result = self._degraded_on_all_three()
        self.assertNotEqual(result["cpa_ratio"], 1)
        total_share = sum(f["share"] for f in result["factors"])
        self.assertAlmostEqual(total_share, 1.0, places=6)


class PrimaryFactorTest(unittest.TestCase):
    def test_ctr_only_degraded_is_primary_with_share_near_one(self):
        # cpm／cvr 跟基線打平（ratio=1），只有 ctr 變差（ratio=2）→ ctr 該獨吞全部貢獻度。
        totals = _totals(impressions=100000, clicks=500, spend=20000, conversions=10)
        baseline = {"cpm": 200.0, "ctr": 0.01, "cvr": 0.02}
        result = bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")
        self.assertEqual(result["primary"], "ctr")
        ctr_factor = next(f for f in result["factors"] if f["key"] == "ctr")
        self.assertAlmostEqual(ctr_factor["share"], 1.0, places=6)

    def test_improved_factor_has_negative_share_and_is_not_primary(self):
        # cpm 比基線便宜（ratio<1，變好了），ctr／cvr 變差——cpm 的 share 該是負的，
        # 且不能被選成 primary（使用者裁決：share 為負代表這個因子其實變好了）。
        totals = _totals(impressions=1_000_000, clicks=4000, spend=200_000, conversions=112)
        baseline = {"cpm": 250.0, "ctr": 0.01, "cvr": 0.03}
        result = bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")
        cpm_factor = next(f for f in result["factors"] if f["key"] == "cpm")
        self.assertLess(cpm_factor["share"], 0)
        self.assertNotEqual(result["primary"], "cpm")


class ReliabilityTest(unittest.TestCase):
    def test_below_min_impressions_is_unreliable_with_no_factors(self):
        totals = _totals(impressions=500, clicks=10, spend=100, conversions=1)
        result = bottleneck.diagnose(totals, baseline={}, brand_id="b1")
        self.assertFalse(result["reliable"])
        self.assertEqual(result["factors"], [])
        self.assertIsNotNone(result["reason_unreliable"])


class ZeroConversionTest(unittest.TestCase):
    def test_zero_conversions_only_splits_cpm_and_ctr_without_crashing(self):
        totals = _totals(impressions=100000, clicks=500, spend=20000, conversions=0)
        baseline = {"cpm": 200.0, "ctr": 0.01, "cvr": 0.02}
        result = bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")
        self.assertIsNone(result["cpa_ratio"])
        self.assertEqual({f["key"] for f in result["factors"]}, {"cpm", "ctr"})


class MissingBaselineTest(unittest.TestCase):
    def test_no_baseline_gives_null_ratio_share_and_a_reference(self):
        totals = _totals(impressions=100000, clicks=500, spend=20000, conversions=10)
        result = bottleneck.diagnose(totals, baseline={}, brand_id="b1")
        self.assertIsNone(result["cpa_ratio"])
        self.assertIsNone(result["primary"])
        for factor in result["factors"]:
            self.assertIsNone(factor["ratio"])
            self.assertIsNone(factor["share"])
            self.assertEqual(factor["detail"], "還沒有你自己的歷史可比")
        self.assertIsNotNone(result["reference"])
        self.assertEqual(result["reference"]["ctr"], reading.INDUSTRY_FALLBACK["ctr"])


class ThresholdGateTest(unittest.TestCase):
    def test_cpa_ratio_below_yellow_multiplier_clears_primary(self):
        # cpa_ratio=1.2，沒超過規則卡預設的 1.3 黃燈倍率——factors 照樣回，但 primary 該是 None
        # （呼叫端才知道沒有值得報的瓶頸；使用者裁決第 3 條：全部列出，不是不算）。
        totals = _totals(impressions=1_000_000, clicks=4000, spend=240_000, conversions=112)
        baseline = {"cpm": 200.0, "ctr": 0.004, "cvr": 0.028}
        result = bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")
        self.assertAlmostEqual(result["cpa_ratio"], 1.2, places=6)
        self.assertIsNone(result["primary"])


class FatigueSubFactorTest(unittest.TestCase):
    def _cpm_primary_totals(self, max_frequency):
        totals = _totals(impressions=1_000_000, clicks=4000, spend=400_000, conversions=112,
                         max_frequency=max_frequency)
        baseline = {"cpm": 200.0, "ctr": 0.004, "cvr": 0.028}
        return bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")

    def test_cpm_primary_over_fatigue_warning_gets_audience_too_narrow_sub(self):
        result = self._cpm_primary_totals(max_frequency=3.0)  # 冷受眾預設警示門檻 2.5
        self.assertEqual(result["primary"], "cpm")
        cpm_factor = next(f for f in result["factors"] if f["key"] == "cpm")
        self.assertEqual(cpm_factor["sub"], "audience_too_narrow")

    def test_cpm_primary_without_frequency_data_does_not_guess(self):
        result = self._cpm_primary_totals(max_frequency=None)
        cpm_factor = next(f for f in result["factors"] if f["key"] == "cpm")
        self.assertIsNone(cpm_factor["sub"])


class NearCancellingTest(unittest.TestCase):
    """審查發現 1：三個因子互相抵銷、總倍率貼近 1 時，log 的分母趨近 0，貢獻度會炸成
    天文數字（例如「貢獻約 138640%」）印到使用者臉上。這一帶本來就沒有淨變化可歸因。"""

    def test_near_cancelling_factors_give_no_share_instead_of_absurd_percent(self):
        # cpm 貴一倍（ratio 2.0）、ctr 好一倍（ratio 0.5）、cvr 幾乎沒動（ratio 1.0005）
        # → cpa_ratio ≈ 1.0005，三者幾乎完全抵銷。
        totals = _totals(impressions=100000, clicks=2000, spend=40000, conversions=40)
        baseline = {"cpm": 200.0, "ctr": 0.01, "cvr": 0.02001}
        result = bottleneck.diagnose(totals, baseline=baseline, brand_id="b1")
        self.assertAlmostEqual(result["cpa_ratio"], 1.0005, places=4)
        for factor in result["factors"]:
            self.assertIsNone(factor["share"],
                              f"{factor['key']} 的貢獻度應該算不出來，不該是 {factor['share']}")
        self.assertIsNone(result["primary"])


if __name__ == "__main__":
    unittest.main()
