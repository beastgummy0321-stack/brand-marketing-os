"""app/tests/test_ads_cell_trust_flags.py — 純函式 `nextcycle.cell_trust_flags()` 與吃它的
`theme_feedback.theme_quota()`。不碰資料庫，從 test_ads_nextcycle.py 分出來（該檔已達行數上限）。
"""

import unittest

from app.ads import nextcycle, theme_feedback


class SampleTrustFlagsTest(unittest.TestCase):
    """票 03-sample-trust-threshold（ADR 0011 第一至三節）：純函式 cell_trust_flags()，三種
    驗收情境＋旗標互相獨立的證明。條件不成立的旗標鍵不出現（不是回傳 False）。"""

    def test_low_conversions_flag_insufficient_evidence(self):
        """轉換數 20 次（< 50 可信門檻）：應標證據不足，該切角本身不受影響（純函式只回旗標）。"""
        flags = nextcycle.cell_trust_flags(conversions=20, spend=100, allocated_budget=1000)
        self.assertEqual(flags, {"evidence_sufficient": False})

    def test_60_percent_spend_zero_conversions_flags_underperforming(self):
        """花費達分配預算 60%、零轉換：應標表現差。"""
        flags = nextcycle.cell_trust_flags(conversions=0, spend=600, allocated_budget=1000)
        self.assertTrue(flags["underperforming"])

    def test_80_conversions_with_results_flags_neither(self):
        """轉換數 80 次且有轉換：兩個旗標都不該出現。"""
        flags = nextcycle.cell_trust_flags(conversions=80, spend=800, allocated_budget=1000)
        self.assertEqual(flags, {})

    def test_flags_are_independent_and_can_coexist(self):
        """兩個旗標互相獨立：0 轉換同時符合「未達可信門檻」與「花費過半零轉換」，該同時出現。"""
        flags = nextcycle.cell_trust_flags(conversions=0, spend=600, allocated_budget=1000)
        self.assertEqual(flags, {"evidence_sufficient": False, "underperforming": True,
                                 "underperforming_reason": "zero_conversion"})

    def test_below_spend_threshold_does_not_flag_underperforming(self):
        """零轉換但花費還沒到分配預算一半：不該標表現差（仍標證據不足）。"""
        flags = nextcycle.cell_trust_flags(conversions=0, spend=100, allocated_budget=1000)
        self.assertNotIn("underperforming", flags)
        self.assertFalse(flags["evidence_sufficient"])

    def test_economic_underperformance_signal(self):
        """票 03 驗收 1、2：虧到停損線以下（在地手工品質_03，0.34／打平 1.75）算
        underperforming；只略低於打平線的（快速到貨便利_04，1.68）不算——那是 judge() 既有的 learning
        「在打平線附近」那格，不是失敗（D3）。新參數純附加：零轉換不被蓋掉、只傳三個位置參數行為不變。"""
        ctf = nextcycle.cell_trust_flags
        self.assertTrue(ctf(2, 2500, 5000, revenue=840, breakeven_roas=1.75)["underperforming"])
        self.assertEqual(ctf(2, 2500, 5000, revenue=840, breakeven_roas=1.75)["underperforming_reason"],
                         "roas_below_stop_loss")
        self.assertEqual(ctf(0, 600, 1000)["underperforming_reason"], "zero_conversion")
        self.assertNotIn("underperforming", ctf(10, 2500, 5000, revenue=4200, breakeven_roas=1.75))
        self.assertEqual(ctf(0, 600, 1000), ctf(0, 600, 1000, revenue=2000, breakeven_roas=1.75))
        self.assertEqual(ctf(20, 100, 1000), {"evidence_sufficient": False})

    def test_theme_quota_reflects_economic_flag_and_degrades_safely(self):
        """theme_feedback.theme_quota()：沒打平的角度扣配額；沒有 revenue 資料的舊列不受影響；
        只要有一列缺打平線就整組不做經濟判斷（不拿 A 列的線審 B 列的數字）。"""
        cell, tq = {"creative_angle": "pain"}, theme_feedback.theme_quota
        failing = [{"creative_angle": "pain", "conversions": 2, "spend": 2500, "allocated_budget": 5000, "revenue": 840, "breakeven_roas": 1.75}]
        legacy = [{"creative_angle": "pain", "conversions": 80, "spend": 800, "allocated_budget": 1000}]
        mixed = [{"creative_angle": "pain", "conversions": 5, "spend": 1000, "allocated_budget": 2000, "revenue": 4000, "breakeven_roas": 3.0},
                 {"creative_angle": "pain", "conversions": 1, "spend": 1000, "allocated_budget": 2000, "revenue": 100}]
        self.assertEqual(tq(cell, failing), theme_feedback.BASE_THEME_QUOTA - theme_feedback.UNDERPERFORMING_THEME_PENALTY)
        self.assertEqual(tq(cell, legacy), theme_feedback.BASE_THEME_QUOTA + theme_feedback.CONVERTING_THEME_BONUS)
        self.assertEqual(tq(cell, mixed), theme_feedback.BASE_THEME_QUOTA)  # 中立，不是扣分
