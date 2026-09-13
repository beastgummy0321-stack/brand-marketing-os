"""app/tests/test_ads_settings_budget_card.py — F03-I17 falsifier.

檔期規劃退場、預算搬進投放中心（使用者裁決 4）：設定頁的規則卡清單不再列出
`schedule_budget`，但卡片定義本身沒被刪——舊 `app/schedule/**` 還在讀
`daily_budget`，`get_value`/`get_card` 對這張卡要繼續正常運作。
"""

import unittest

from app.core import db, rule_cards

BID = "brand_ads_i17"


class HiddenBudgetCardTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id = %s", (BID,))
        self.conn.commit()

    def test_list_cards_drops_schedule_budget(self):
        keys = [card["key"] for card in rule_cards.list_cards(self.conn, BID)]
        self.assertNotIn("schedule_budget", keys)
        # 其他卡片都還在——不是清空整張表，只是不列這一張。
        self.assertIn("rule_prompt_cap", keys)
        self.assertIn("gross_margin", keys)
        self.assertIn("schedule_plan_count", keys)

    def test_get_value_still_works_for_hidden_card(self):
        self.assertEqual(
            rule_cards.get_value(self.conn, BID, "schedule_budget", "daily_budget"), 0.0
        )
        rule_cards.set_value(
            self.conn, BID, "schedule_budget", "daily_budget", 1500.0,
            actor="tester", org_id=db.DEV_ORG_ID,
        )
        self.assertEqual(
            rule_cards.get_value(self.conn, BID, "schedule_budget", "daily_budget"), 1500.0
        )


if __name__ == "__main__":
    unittest.main()
