"""app/tests/test_dashboard_guide_cards.py — 票 04-guide-card-engine：下一步指南卡引擎。

純函數測試，不碰資料庫（app/dashboard/guide_cards.py 只吃一份 facts dict）。
每條登記規則各自測「觸發」與「不觸發」，另外測優先序（多規則同時觸發時取前 3、順序正確）
與無待辦時回空清單（呼叫端負責顯示「一切正常」）。

外殼切片（2026-08-28）：pacing_alert／reading_unread／next_cycle_draft／cycle_stage
四條規則隨 `app/ads/` 一起刪掉，對應的 class 一併移除（見 guide_cards.py 檔頭）。
ADR 0036（2026-08-29）：節日日曆備戰提醒那條隨整份節日日曆刪掉，同樣一併移除。
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
        "intake_draft": None,
        # 預設沒回答過投放史問題，避免每條既有測試都要額外處理票 past-ads/04 新規則；
        # PastAdsPendingRuleTest 自己覆寫來測觸發。
        "advertising_history": None,
        "imported_ad_count": 0,
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


class PastAdsPendingRuleTest(unittest.TestCase):
    """票 past-ads/04（ADR 0067）：說過投放過廣告、老廣告一則都沒帶進來標座標時出卡。"""

    def test_triggers_when_has_history_and_zero_imported(self):
        facts = _facts(advertising_history="has_history", imported_ad_count=0)
        card = guide_cards.RULES["past_ads_pending"](facts)
        self.assertIsNotNone(card)
        self.assertEqual(card["action_url"], f"/app/brands/{BRAND_ID}/intake/history")

    def test_does_not_trigger_when_already_imported(self):
        facts = _facts(advertising_history="has_history", imported_ad_count=3)
        self.assertIsNone(guide_cards.RULES["past_ads_pending"](facts))

    def test_does_not_trigger_when_no_history(self):
        facts = _facts(advertising_history="none", imported_ad_count=0)
        self.assertIsNone(guide_cards.RULES["past_ads_pending"](facts))

    def test_does_not_trigger_when_history_unanswered(self):
        facts = _facts(advertising_history=None, imported_ad_count=0)
        self.assertIsNone(guide_cards.RULES["past_ads_pending"](facts))

    def test_outranks_intake_in_progress_and_conversion_goal_missing(self):
        """票 04 走查 round 2（## Rejected）：總覽品牌卡只露出 build() 的第一張卡當
        next_step，一個剛建檔的品牌必定同時缺 conversion_goal、有進行中的建檔草稿——
        past_ads_pending 排最前面，剛按過「投放過廣告」的人才看得到自己的下一步。"""
        facts = _facts(
            conversion_goal=None,
            advertising_history="has_history",
            imported_ad_count=0,
            intake_draft={"step": 2, "resume_path": f"/app/brands/{BRAND_ID}/intake"},
        )
        cards = guide_cards.build(facts)
        self.assertIn("投放過廣告", cards[0]["title"])


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


class BuildPriorityAndCapTest(unittest.TestCase):
    def test_no_rules_triggered_returns_empty_list(self):
        self.assertEqual(guide_cards.build(_facts()), [])

    def test_cards_come_back_in_registration_order(self):
        facts = _facts(
            conversion_goal=None,
            intake_draft={"step": 2, "resume_path": f"/app/brands/{BRAND_ID}/intake"},
            pending_facts_count=2,
        )
        # 三條規則刻意同時滿足各自的觸發條件，純粹測 build() 的排序，
        # 不代表真實資料一定會三條同時成立。
        cards = guide_cards.build(facts)
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
