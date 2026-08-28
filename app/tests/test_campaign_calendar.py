"""app/tests/test_campaign_calendar.py — 票 06-campaign-calendar：檔期日曆第一層。

純函數情境測試，不碰資料庫（app/dashboard/campaign_calendar.py 只吃 today／event
dict）。涵蓋提前期分級三種等級（大 90／中 45／小 30 天）各有觸發／不觸發案例、
素材 14 天完稿提醒的觸發／不觸發案例、三階段（遠期備戰／中期備戰／近期備戰）推導、以及跨
多檔期取最急迫一筆的排序邏輯。
"""

import unittest
from datetime import date

from app.dashboard import campaign_calendar as cal


def _event(event_id="evt_1", name="測試檔期", event_date="2026-11-11", tier="large",
           applicable_industries="all") -> dict:
    return {"id": event_id, "name": name, "date": event_date, "tier": tier,
            "applicable_industries": applicable_industries}


class LeadDaysConstantsTest(unittest.TestCase):
    def test_lead_days_by_tier(self):
        self.assertEqual(cal.LEAD_DAYS["large"], 90)
        self.assertEqual(cal.LEAD_DAYS["medium"], 45)
        self.assertEqual(cal.LEAD_DAYS["small"], 30)

    def test_creative_lead_days_is_14_regardless_of_tier(self):
        self.assertEqual(cal.CREATIVE_LEAD_DAYS, 14)


class PrepReminderTest(unittest.TestCase):
    """三種等級各測「剛好在提前期窗口內」（觸發）與「還沒到提前期」（不觸發）。"""

    def test_large_tier_triggers_at_90_days_out(self):
        today = date(2026, 8, 13)  # 2026-11-11 - 90 天
        card = cal.prep_reminder(today, _event(event_date="2026-11-11", tier="large"))
        self.assertIsNotNone(card)
        self.assertEqual(card["kind"], "prep")
        self.assertEqual(card["tier"], "large")

    def test_large_tier_does_not_trigger_at_91_days_out(self):
        today = date(2026, 8, 12)  # 91 天前，還沒到大檔提前期
        self.assertIsNone(cal.prep_reminder(today, _event(event_date="2026-11-11", tier="large")))

    def test_medium_tier_triggers_at_45_days_out(self):
        today = date(2026, 5, 4)  # 2026-06-18 - 45 天
        card = cal.prep_reminder(today, _event(event_date="2026-06-18", tier="medium"))
        self.assertIsNotNone(card)

    def test_medium_tier_does_not_trigger_at_46_days_out(self):
        today = date(2026, 5, 3)
        self.assertIsNone(cal.prep_reminder(today, _event(event_date="2026-06-18", tier="medium")))

    def test_small_tier_triggers_at_30_days_out(self):
        today = date(2026, 1, 15)  # 2026-02-14 - 30 天
        card = cal.prep_reminder(today, _event(event_date="2026-02-14", tier="small"))
        self.assertIsNotNone(card)

    def test_small_tier_does_not_trigger_at_31_days_out(self):
        today = date(2026, 1, 14)
        self.assertIsNone(cal.prep_reminder(today, _event(event_date="2026-02-14", tier="small")))

    def test_does_not_trigger_after_event_has_passed(self):
        today = date(2026, 11, 12)
        self.assertIsNone(cal.prep_reminder(today, _event(event_date="2026-11-11", tier="large")))

    def test_weeks_until_rounds_up(self):
        # 2026-08-13 → 2026-11-11 是 90 天＝12 週又 6 天 → 無條件進位 13 週
        today = date(2026, 8, 13)
        card = cal.prep_reminder(today, _event(event_date="2026-11-11", tier="large"))
        self.assertEqual(card["weeks_until"], 13)


class CreativeReminderTest(unittest.TestCase):
    def test_triggers_at_14_days_out(self):
        today = date(2026, 10, 28)  # 2026-11-11 - 14 天
        card = cal.creative_reminder(today, _event(event_date="2026-11-11"))
        self.assertIsNotNone(card)
        self.assertEqual(card["kind"], "creative")
        self.assertEqual(card["days_until"], 14)

    def test_does_not_trigger_at_15_days_out(self):
        today = date(2026, 10, 27)
        self.assertIsNone(cal.creative_reminder(today, _event(event_date="2026-11-11")))

    def test_does_not_trigger_after_event_has_passed(self):
        today = date(2026, 11, 12)
        self.assertIsNone(cal.creative_reminder(today, _event(event_date="2026-11-11")))


class CampaignStageTest(unittest.TestCase):
    """大檔（90 天）三等分：0-29 天遠期備戰、30-59 天中期備戰、60-90 天近期備戰（elapsed＝已過天數）。"""

    def test_none_before_prep_window_opens(self):
        self.assertIsNone(cal.campaign_stage(date(2026, 8, 12), date(2026, 11, 11), "large"))

    def test_warmup_stage_right_after_window_opens(self):
        self.assertEqual(cal.campaign_stage(date(2026, 8, 13), date(2026, 11, 11), "large"), "遠期備戰")

    def test_peak_stage_in_the_middle(self):
        # elapsed = 90 - 30 = 60... 挑一個明確落在中段的日子
        today = date(2026, 9, 20)  # elapsed ≈ 38 天
        self.assertEqual(cal.campaign_stage(today, date(2026, 11, 11), "large"), "中期備戰")

    def test_sprint_stage_near_event_date(self):
        today = date(2026, 11, 5)  # elapsed = 84 天
        self.assertEqual(cal.campaign_stage(today, date(2026, 11, 11), "large"), "近期備戰")

    def test_sprint_stage_on_event_date_itself(self):
        self.assertEqual(cal.campaign_stage(date(2026, 11, 11), date(2026, 11, 11), "large"), "近期備戰")

    def test_none_after_event_has_passed(self):
        self.assertIsNone(cal.campaign_stage(date(2026, 11, 12), date(2026, 11, 11), "large"))


class NextCalendarReminderTest(unittest.TestCase):
    def test_none_when_no_event_triggers(self):
        events = [_event(event_date="2027-11-11", tier="large")]
        self.assertIsNone(cal.next_calendar_reminder(events, date(2026, 8, 5)))

    def test_creative_reminder_wins_over_prep_reminder_for_same_event(self):
        """同一檔期兩個窗口重疊時（素材期限比備戰期更急迫），只回素材那張。"""
        events = [_event(event_id="evt_1", event_date="2026-02-14", tier="small")]
        # 小檔提前期 30 天／素材 14 天在事件前 14 天內同時成立，素材期限應勝出
        today = date(2026, 2, 5)  # 2026-02-14 前 9 天
        card = cal.next_calendar_reminder(events, today)
        self.assertEqual(card["kind"], "creative")

    def test_picks_the_soonest_event_among_multiple(self):
        events = [
            _event(event_id="far", name="遠檔期", event_date="2026-04-01", tier="large"),
            _event(event_id="near", name="近檔期", event_date="2026-02-14", tier="small"),
        ]
        today = date(2026, 1, 20)  # 兩者都在各自提前期窗口內，近檔期天數較小
        card = cal.next_calendar_reminder(events, today)
        self.assertEqual(card["id"], "near")

    def test_filters_out_events_not_relevant_to_brand_industry(self):
        """業種對不到清單 -> 就算在窗口內也不提醒（ADR 0014 第一節）。"""
        events = [_event(event_date="2026-11-11", tier="large",
                         applicable_industries=["beauty_personal_care"])]
        today = date(2026, 8, 13)  # 90 天前，剛好開窗
        self.assertIsNone(cal.next_calendar_reminder(events, today, "food_beverage"))

    def test_keeps_events_matching_brand_industry(self):
        """業種對到清單 -> 正常提醒。"""
        events = [_event(event_date="2026-11-11", tier="large",
                         applicable_industries=["beauty_personal_care"])]
        today = date(2026, 8, 13)
        card = cal.next_calendar_reminder(events, today, "beauty_personal_care")
        self.assertIsNotNone(card)

    def test_keeps_all_tagged_events_regardless_of_brand_industry(self):
        """節日標 "all" -> 不分業種都提醒，即使品牌業種沒設定（None）。"""
        events = [_event(event_date="2026-11-11", tier="large", applicable_industries="all")]
        today = date(2026, 8, 13)
        card = cal.next_calendar_reminder(events, today, None)
        self.assertIsNotNone(card)


class IndustryRelevantTest(unittest.TestCase):
    def test_all_tagged_event_matches_any_industry(self):
        self.assertTrue(cal.industry_relevant(_event(applicable_industries="all"), None))
        self.assertTrue(cal.industry_relevant(_event(applicable_industries="all"), "food_beverage"))

    def test_brand_industry_in_list_is_relevant(self):
        event = _event(applicable_industries=["beauty_personal_care", "fashion_apparel"])
        self.assertTrue(cal.industry_relevant(event, "beauty_personal_care"))

    def test_brand_industry_not_in_list_is_not_relevant(self):
        event = _event(applicable_industries=["beauty_personal_care"])
        self.assertFalse(cal.industry_relevant(event, "food_beverage"))
        self.assertFalse(cal.industry_relevant(event, None))  # 業種未設定，對不到特定清單

    def test_missing_field_defaults_to_all_for_backward_compat(self):
        """手刻的 event dict（沒帶 applicable_industries）視為 all，相容既有呼叫端。"""
        event = {"id": "e", "name": "e", "date": "2026-11-11", "tier": "large"}
        self.assertTrue(cal.industry_relevant(event, "food_beverage"))


class CurrentCampaignStageIndustryTest(unittest.TestCase):
    def test_filters_out_stage_for_irrelevant_industry(self):
        events = [_event(event_date="2026-11-11", tier="large",
                         applicable_industries=["beauty_personal_care"])]
        self.assertIsNone(cal.current_campaign_stage(
            events, date(2026, 8, 13), "food_beverage"))

    def test_keeps_stage_for_matching_industry(self):
        events = [_event(event_date="2026-11-11", tier="large",
                         applicable_industries=["beauty_personal_care"])]
        stage = cal.current_campaign_stage(events, date(2026, 8, 13), "beauty_personal_care")
        self.assertIsNotNone(stage)


class DismissedCategoriesFilterTest(unittest.TestCase):
    """票 02-permanent-dismiss-category（ADR 0014 第二節）：dismissed_categories 濾掉
    永久關閉的節日類別，即使業種比對判成相關也不再提醒。"""

    def test_next_calendar_reminder_suppressed_when_category_dismissed(self):
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)  # 90 天前，剛好開窗
        self.assertIsNone(cal.next_calendar_reminder(events, today, dismissed_categories={"cny"}))

    def test_next_calendar_reminder_kept_when_different_category_dismissed(self):
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)
        card = cal.next_calendar_reminder(events, today, dismissed_categories={"valentine"})
        self.assertIsNotNone(card)

    def test_next_calendar_reminder_kept_when_no_categories_dismissed(self):
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)
        self.assertIsNotNone(cal.next_calendar_reminder(events, today, dismissed_categories=None))

    def test_re_enabling_restores_reminder(self):
        """驗收清單：重新開啟後恢復提醒——不在 dismissed_categories 集合內即視為開啟。"""
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)
        self.assertIsNone(cal.next_calendar_reminder(events, today, dismissed_categories={"cny"}))
        self.assertIsNotNone(
            cal.next_calendar_reminder(events, today, dismissed_categories=set()))

    def test_current_campaign_stage_suppressed_when_category_dismissed(self):
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)
        self.assertIsNone(
            cal.current_campaign_stage(events, today, dismissed_categories={"cny"}))

    def test_current_campaign_stage_kept_when_different_category_dismissed(self):
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large")]
        today = date(2026, 8, 13)
        self.assertIsNotNone(
            cal.current_campaign_stage(events, today, dismissed_categories={"valentine"}))

    def test_dismissal_combines_with_industry_filter(self):
        """業種對到、但類別被永久關閉——兩個濾網都要生效，關閉的優先擋下。"""
        events = [_event(event_id="cny_2026", event_date="2026-11-11", tier="large",
                         applicable_industries=["beauty_personal_care"])]
        today = date(2026, 8, 13)
        self.assertIsNone(cal.next_calendar_reminder(
            events, today, "beauty_personal_care", dismissed_categories={"cny"}))


class LoadEventsTest(unittest.TestCase):
    def test_loads_bundled_data_file_with_required_fields(self):
        events = cal.load_events()
        self.assertGreater(len(events), 0)
        for event in events:
            self.assertIn("id", event)
            self.assertIn("name", event)
            self.assertIn("date", event)
            self.assertIn(event["tier"], cal.LEAD_DAYS)
            self.assertIn("applicable_industries", event)


class HolidayIdTest(unittest.TestCase):
    """票 03-cycle-skip-record：holiday_id() 去掉逐年事件 id 的年份尾碼，拿到跨年
    穩定識別碼——同一節日逐年 id 不同（cny_2026／cny_2027），要靠這個穩定碼才能比對
    「去年是否跳過」。"""

    def test_strips_trailing_year_suffix(self):
        self.assertEqual(cal.holiday_id("cny_2026"), "cny")
        self.assertEqual(cal.holiday_id("cny_2027"), "cny")

    def test_same_holiday_different_years_map_to_same_id(self):
        self.assertEqual(cal.holiday_id("double11_2026"), cal.holiday_id("double11_2027"))

    def test_id_without_year_suffix_passes_through_unchanged(self):
        self.assertEqual(cal.holiday_id("evt_1"), "evt_1")

    def test_bundled_data_file_ids_all_strip_to_a_year_independent_holiday_id(self):
        """真實資料檔逐年 id 都帶年份尾碼——這裡防止資料檔改格式後 holiday_id() 悄悄失效。"""
        events = cal.load_events()
        for event in events:
            self.assertRegex(event["id"], r"_\d{4}$")


if __name__ == "__main__":
    unittest.main()
