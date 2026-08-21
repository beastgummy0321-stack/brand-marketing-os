# -*- coding: utf-8 -*-
"""app/tests/test_dashboard_guide_cards.py — 票 04-guide-card-engine：下一步指南卡引擎。

純函數測試，不碰資料庫（app/dashboard/guide_cards.py 只吃一份 facts dict）。
每條登記規則各自測「觸發」與「不觸發」，另外測優先序（多規則同時觸發時取前 3、順序正確）
與無待辦時回空清單（呼叫端負責顯示「一切正常」）。
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
        "active_cycle": None,
        "reading_ready": False,
        "next_cycle_draft_ready": False,
        "campaign_reminder": None,
        "pacing_alert": None,
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
        self.assertEqual(card["action_url"], f"/brands/{BRAND_ID}/edit")

    def test_does_not_trigger_when_conversion_goal_set(self):
        self.assertIsNone(guide_cards.RULES["conversion_goal_missing"](_facts()))

    def test_outranks_pacing_alert(self):
        """資料正確性前提優先度高於一般提醒，兩條規則同時觸發時排在 pacing_alert 之前。"""
        facts = _facts(conversion_goal=None,
                       pacing_alert={"kind": "overspend", "action_url": None})
        cards = guide_cards.build(facts)
        self.assertIn("廣告目標", cards[0]["title"])


class PacingAlertRuleTest(unittest.TestCase):
    def test_overspend_triggers_with_interrupt_action_url(self):
        facts = _facts(pacing_alert={"kind": "overspend", "action_url": "/brands/b/ads/c1"})
        card = guide_cards.RULES["pacing_alert"](facts)
        self.assertIsNotNone(card)
        self.assertIn("燒太快", card["title"])
        self.assertEqual(card["action_url"], "/brands/b/ads/c1")

    def test_underspend_without_action_url_falls_back_to_ads_home(self):
        facts = _facts(pacing_alert={"kind": "underspend", "action_url": None})
        card = guide_cards.RULES["pacing_alert"](facts)
        self.assertIn("花不完", card["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/campaigns")

    def test_does_not_trigger_without_alert(self):
        self.assertIsNone(guide_cards.RULES["pacing_alert"](_facts()))

    def test_pacing_outranks_reading_unread(self):
        """錢的步調行動價值最高：pacing 與判讀未讀同時觸發時，pacing 排第一。"""
        facts = _facts(pacing_alert={"kind": "overspend", "action_url": None},
                       active_cycle={"id": "ccy_1", "stage_label": None}, reading_ready=True)
        cards = guide_cards.build(facts)
        self.assertIn("燒太快", cards[0]["title"])


class ReadingUnreadRuleTest(unittest.TestCase):
    def test_triggers_when_reading_ready_and_no_draft_yet(self):
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None}, reading_ready=True)
        card = guide_cards.RULES["reading_unread"](facts)
        self.assertIsNotNone(card)
        self.assertIn("action_url", card)
        self.assertEqual(card["action_url"], f"/brands/{BRAND_ID}/ads/ccy_1/performance")

    def test_does_not_trigger_when_reading_not_ready(self):
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None}, reading_ready=False)
        self.assertIsNone(guide_cards.RULES["reading_unread"](facts))

    def test_does_not_trigger_once_next_cycle_draft_is_ready(self):
        """判讀出爐後系統已經備好下期草案，代表結論已經被拿去用了，不算「未讀」。"""
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None},
                       reading_ready=True, next_cycle_draft_ready=True)
        self.assertIsNone(guide_cards.RULES["reading_unread"](facts))

    def test_does_not_trigger_without_active_cycle(self):
        facts = _facts(active_cycle=None, reading_ready=True)
        self.assertIsNone(guide_cards.RULES["reading_unread"](facts))


class NextCycleDraftRuleTest(unittest.TestCase):
    def test_triggers_when_draft_ready(self):
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None},
                       next_cycle_draft_ready=True)
        card = guide_cards.RULES["next_cycle_draft"](facts)
        self.assertIsNotNone(card)
        self.assertEqual(card["action_url"], f"/brands/{BRAND_ID}/ads/ccy_1/performance")

    def test_does_not_trigger_when_draft_not_ready(self):
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None},
                       next_cycle_draft_ready=False)
        self.assertIsNone(guide_cards.RULES["next_cycle_draft"](facts))

    def test_does_not_trigger_without_active_cycle(self):
        facts = _facts(active_cycle=None, next_cycle_draft_ready=True)
        self.assertIsNone(guide_cards.RULES["next_cycle_draft"](facts))


class CycleStageRuleTest(unittest.TestCase):
    def test_triggers_when_stage_label_present(self):
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": "素材"})
        card = guide_cards.RULES["cycle_stage"](facts)
        self.assertIsNotNone(card)
        self.assertIn("素材", card["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/campaigns/ccy_1")

    def test_does_not_trigger_when_stage_label_absent(self):
        """stage_label 為 None＝已經在成效格（第 5 格），不算「卡住」，不用提醒去推進。"""
        facts = _facts(active_cycle={"id": "ccy_1", "stage_label": None})
        self.assertIsNone(guide_cards.RULES["cycle_stage"](facts))

    def test_does_not_trigger_without_active_cycle(self):
        facts = _facts(active_cycle=None)
        self.assertIsNone(guide_cards.RULES["cycle_stage"](facts))


class PendingFactsRuleTest(unittest.TestCase):
    def test_triggers_when_count_positive(self):
        facts = _facts(pending_facts_count=3)
        card = guide_cards.RULES["pending_facts"](facts)
        self.assertIsNotNone(card)
        self.assertIn("3", card["title"])
        self.assertEqual(card["action_url"], f"/brands/{BRAND_ID}/hub/facts")

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
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/campaigns/new")

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
            active_cycle={"id": "ccy_1", "stage_label": "素材"},
            reading_ready=True,
            next_cycle_draft_ready=False,
            pending_facts_count=2,
        )
        # cycle_stage 規則要求 stage_label 存在才觸發；reading_unread 要求
        # next_cycle_draft_ready 為 False——這裡刻意讓四條規則同時滿足各自的觸發條件，
        # 純粹測 build() 的排序與上限，不代表真實資料一定會四條同時成立。
        cards = guide_cards.build(facts)
        self.assertEqual(len(cards), 3)
        titles = [c["title"] for c in cards]
        self.assertIn("判讀", titles[0])
        self.assertIn("素材", titles[1] + titles[2])
        self.assertIn("事實", titles[1] + titles[2])

    def test_single_rule_triggered_returns_one_card(self):
        facts = _facts(pending_facts_count=1)
        cards = guide_cards.build(facts)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["action_url"], f"/brands/{BRAND_ID}/hub/facts")


if __name__ == "__main__":
    unittest.main()
