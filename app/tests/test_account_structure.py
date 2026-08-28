"""app/tests/test_account_structure.py — 帳戶結構＋預算配置底案純函數（票 5，決策 0023 第 14、15 點）。

驗：三個預算級距（小／中／大）分別出對的帳戶結構與分組比例、每組下限警示、
改規則卡數值後底案立即跟著變。
"""

import unittest

from app.ads import account_structure
from app.core import db, rule_cards


class AccountStructureTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    BID = "brand_demo"

    def test_small_budget_does_not_split(self):
        """日預算 500（< 中預算門檻 600）：全額投入單一測試組，不硬拆。"""
        rec = account_structure.recommend(self.conn, self.BID, 500)
        self.assertEqual(rec.tier, "small")
        self.assertEqual(len(rec.groups), 1)
        self.assertEqual(rec.groups[0].role, "test")
        self.assertEqual(rec.groups[0].daily_budget, 500)
        self.assertFalse(rec.groups[0].below_floor)

    def test_medium_budget_splits_70_30(self):
        """日預算 1000（600–1200 之間）：CBO 兩組，70% 驗證／30% 測試。"""
        rec = account_structure.recommend(self.conn, self.BID, 1000)
        self.assertEqual(rec.tier, "medium")
        self.assertEqual([g.role for g in rec.groups], ["validation", "test"])
        self.assertEqual(rec.groups[0].daily_budget, 700.0)
        self.assertEqual(rec.groups[1].daily_budget, 300.0)
        self.assertFalse(rec.groups[1].below_floor)  # 剛好貼著下限，不算低於

    def test_large_budget_dual_cbo_80_20(self):
        """日預算 2000（>= 1200）：雙 CBO，80% 放大／20% 測試。"""
        rec = account_structure.recommend(self.conn, self.BID, 2000)
        self.assertEqual(rec.tier, "large")
        self.assertEqual([g.role for g in rec.groups], ["scaling", "testing"])
        self.assertEqual(rec.groups[0].daily_budget, 1600.0)
        self.assertEqual(rec.groups[1].daily_budget, 400.0)

    def test_medium_split_can_dip_below_floor_and_says_so_honestly(self):
        """日預算 650：屬中預算級距，但 30% 那組只有 195 元，低於每組下限，要誠實標出來。"""
        rec = account_structure.recommend(self.conn, self.BID, 650)
        self.assertTrue(rec.groups[1].below_floor)
        self.assertFalse(rec.groups[0].below_floor)

    def test_tier_boundaries_are_inclusive_on_the_upper_tier(self):
        self.assertEqual(account_structure.recommend(self.conn, self.BID, 600).tier, "medium")
        self.assertEqual(account_structure.recommend(self.conn, self.BID, 1200).tier, "large")
        self.assertEqual(account_structure.recommend(self.conn, self.BID, 599.99).tier, "small")

    def test_invalid_daily_budget_raises(self):
        with self.assertRaises(ValueError):
            account_structure.recommend(self.conn, self.BID, 0)
        with self.assertRaises(ValueError):
            account_structure.recommend(self.conn, self.BID, -100)

    def test_rule_card_change_takes_effect_immediately(self):
        """改規則卡數值落庫後，底案立即用新值——不用重開程式（比照票 12 的驗收標準）。

        用專屬 brand_id（不是共用的 self.BID）：這個模組的 schema 是整個檔案共用一份
        （conftest.py 逐模組 schema，不是逐測試），改到 self.BID 的規則卡會被其他測試
        方法看到，跟本測試無關的斷言會被污染。
        """
        bid = "brand_demo_rule_card_override"
        rule_cards.set_value(self.conn, bid, "budget_structure", "medium_validation_ratio",
                             0.5, actor="測試員")
        rec = account_structure.recommend(self.conn, bid, 1000)
        self.assertEqual(rec.groups[0].daily_budget, 500.0)
        self.assertEqual(rec.groups[1].daily_budget, 500.0)

    def test_brand_override_does_not_leak_into_other_brands(self):
        """A 品牌改規則卡值不影響 B 品牌（設定中心票 01 分品牌驗收）。"""
        brand_a = "brand_demo_isolation_a"
        rule_cards.set_value(self.conn, brand_a, "budget_structure", "medium_validation_ratio",
                             0.5, actor="測試員")
        other = account_structure.recommend(self.conn, "brand_demo_isolation_b", 1000)
        self.assertEqual(other.groups[0].daily_budget, 700.0)  # 系統預設 0.7，沒被 A 品牌的覆寫值污染

    def test_falls_back_to_default_without_db(self):
        """conn=None 時優雅回程式常數預設值，不噴錯（principles 16，比照 rule_cards 慣例）。"""
        rec = account_structure.recommend(None, self.BID, 1000)
        self.assertEqual(rec.tier, "medium")
        self.assertEqual(rec.groups[0].daily_budget, 700.0)


if __name__ == "__main__":
    unittest.main()
