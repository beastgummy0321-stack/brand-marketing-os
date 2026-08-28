"""app/tests/test_dashboard_guide_cards.py — 票 04-guide-card-engine：下一步指南卡引擎。

純函數測試，不碰資料庫（app/dashboard/guide_cards.py 只吃一份 facts dict）。
每條登記規則各自測「觸發」與「不觸發」，另外測優先序（多規則同時觸發時取前 3、順序正確）
與無待辦時回空清單（呼叫端負責顯示「一切正常」）。

外殼切片（2026-08-28）：pacing_alert／reading_unread／next_cycle_draft／cycle_stage
四條規則隨 `app/ads/` 一起刪掉，對應的 class 一併移除（見 guide_cards.py 檔頭）。
"""

import unittest

from app.dashboard import guide_cards

BRAND_ID = "brd_test123"


def _facts(**overrides) -> dict:
    base = {
        "brand_id": BRAND_ID,
        # 預設已設定，避免每條既有測試都要額外處理票 C 新規則；
        # ConversionGoalMissingRuleTest 自己覆寫成 None 來測觸發。
        "conversion_goal": "purchase",
        "pending_facts_count": 0,
        "campaign_reminder": None,
        "intake_draft": None,
    }
    base.update(overrides)
    return base


class ConversionGoalMissingRuleTest(unittest.TestCase):
    """票 C：conversion_goal 沒設定時方法論篩選沒接電，提醒去品牌編輯頁設定。"""

    def test_triggers_when_conversion_goal_missing(self):
        facts = _facts(conversion_goal=None)
        card = guide_cards.RULES["conversion_goal_missing"](facts)
        self.assertIsNotNone(card)
        self.assertIn("廣告目標", card["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/library")

    def test_does_not_trigger_when_conversion_goal_set(self):
        self.assertIsNone(guide_cards.RULES["conversion_goal_missing"](_facts()))

    def test_outranks_pending_facts(self):
        """資料正確性前提優先度高於一般提醒，兩條規則同時觸發時排在 pending_facts 之前。"""
        cards = guide_cards.build(_facts(conversion_goal=None, pending_facts_count=2))
        self.assertIn("廣告目標", cards[0]["title"])


class PendingFactsRuleTest(unittest.TestCase):
    def test_triggers_when_count_positive(self):
        facts = _facts(pending_facts_count=3)
        card = guide_cards.RULES["pending_facts"](facts)
        self.assertIsNotNone(card)
        self.assertIn("3", card["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/library?tab=facts")

    def test_does_not_trigger_when_count_zero(self):
        facts = _facts(pending_facts_count=0)
        self.assertIsNone(guide_cards.RULES["pending_facts"](facts))


class CampaignCalendarRuleTest(unittest.TestCase):
    """票 06-campaign-calendar：檔期日曆備戰提醒轉成指南卡文字。"""

    def test_triggers_prep_reminder_with_weeks_until_in_title(self):
        facts = _facts(campaign_reminder={
            "id": "cny_2026", "name": "農曆新年", "tier": "large", "tier_label": "大檔",
            "days_until": 28, "weeks_until": 4, "kind": "prep",
        })
        card = guide_cards.RULES["campaign_calendar"](facts)
        self.assertIsNotNone(card)
        self.assertIn("農曆新年", card["title"])
        self.assertIn("4", card["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}")

    def test_triggers_creative_reminder_with_days_until_in_title(self):
        facts = _facts(campaign_reminder={
            "id": "double11_2026", "name": "雙11購物節", "days_until": 10, "kind": "creative",
        })
        card = guide_cards.RULES["campaign_calendar"](facts)
        self.assertIsNotNone(card)
        self.assertIn("雙11購物節", card["title"])
        self.assertIn("素材", card["title"])
        self.assertIn("10", card["title"])

    def test_does_not_trigger_when_no_reminder(self):
        self.assertIsNone(guide_cards.RULES["campaign_calendar"](_facts(campaign_reminder=None)))

    def test_last_year_skip_reason_appended_to_title(self):
        """票 03-cycle-skip-record：去年有跳過紀錄時附帶顯示去年的理由。"""
        facts = _facts(campaign_reminder={
            "id": "cny_2027", "name": "農曆新年", "tier": "large", "tier_label": "大檔",
            "days_until": 28, "weeks_until": 4, "kind": "prep",
            "last_year_skipped": True, "last_year_skip_reason": "收假太晚，沒空間做素材",
        })
        card = guide_cards.RULES["campaign_calendar"](facts)
        self.assertIn("收假太晚，沒空間做素材", card["title"])

    def test_last_year_skip_without_reason_still_notes_it_was_skipped(self):
        facts = _facts(campaign_reminder={
            "id": "cny_2027", "name": "農曆新年", "tier": "large", "tier_label": "大檔",
            "days_until": 28, "weeks_until": 4, "kind": "prep",
            "last_year_skipped": True, "last_year_skip_reason": None,
        })
        card = guide_cards.RULES["campaign_calendar"](facts)
        self.assertIn("去年跳過", card["title"])

    def test_no_last_year_skip_note_when_not_skipped(self):
        facts = _facts(campaign_reminder={
            "id": "cny_2027", "name": "農曆新年", "tier": "large", "tier_label": "大檔",
            "days_until": 28, "weeks_until": 4, "kind": "prep",
        })
        card = guide_cards.RULES["campaign_calendar"](facts)
        self.assertNotIn("跳過", card["title"])


class BuildPriorityAndCapTest(unittest.TestCase):
    def test_no_rules_triggered_returns_empty_list(self):
        self.assertEqual(guide_cards.build(_facts()), [])

    def test_takes_top_three_in_registration_order_when_all_four_trigger(self):
        facts = _facts(
            conversion_goal=None,
            intake_draft={"step": 2, "resume_path": f"/app/brands/{BRAND_ID}/intake"},
            pending_facts_count=2,
            campaign_reminder={"id": "cny_2026", "name": "農曆新年", "tier": "large",
                               "tier_label": "大檔", "days_until": 28, "weeks_until": 4,
                               "kind": "prep"},
        )
        # 四條規則刻意同時滿足各自的觸發條件，純粹測 build() 的排序與上限，
        # 不代表真實資料一定會四條同時成立。
        cards = guide_cards.build(facts)
        self.assertEqual(len(cards), 3, "MAX_CARDS 是 3，第四條不該進來")
        titles = [c["title"] for c in cards]
        self.assertIn("廣告目標", titles[0])
        self.assertIn("建檔進行中", titles[1])
        self.assertIn("事實", titles[2])

    def test_single_rule_triggered_returns_one_card(self):
        facts = _facts(pending_facts_count=1)
        cards = guide_cards.build(facts)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["action_url"], f"/app/brands/{BRAND_ID}/library?tab=facts")


if __name__ == "__main__":
    unittest.main()
