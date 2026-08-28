"""app/tests/test_dashboard_health.py — 票 02-overview-cards：健康度燈號純函數情境測試。

規格 0001「健康度燈號第一版」：有未結 money_loss＝紅、有未結 rule_warning＝黃、
其餘綠；純規則，不用 AI。純函數測試，無需資料庫。
"""

import unittest

from app.dashboard.health import brand_health


class BrandHealthTest(unittest.TestCase):
    def test_no_open_interrupts_is_green(self):
        self.assertEqual(brand_health([]), "green")

    def test_only_informational_is_still_green(self):
        self.assertEqual(brand_health(["informational"]), "green")

    def test_rule_warning_is_yellow(self):
        self.assertEqual(brand_health(["rule_warning"]), "yellow")

    def test_money_loss_is_red(self):
        self.assertEqual(brand_health(["money_loss"]), "red")

    def test_money_loss_outranks_rule_warning(self):
        self.assertEqual(brand_health(["rule_warning", "money_loss"]), "red")


if __name__ == "__main__":
    unittest.main()
