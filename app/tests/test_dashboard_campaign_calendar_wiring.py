# -*- coding: utf-8 -*-
"""app/tests/test_dashboard_campaign_calendar_wiring.py — 票 06-campaign-calendar：
儀表板 API 接上檔期日曆真貨源（純函數邏輯已在 test_campaign_calendar.py 測過，這裡
只驗證 repository 有把純函數結果組進指南卡與駕駛艙 campaign_stage 欄位）。

真實檔期日期是外部世界的事實（雙11 就是 11 月 11 日），沒辦法像訂單那樣隨測試
「今天」調整，所以用 calendar_events 這個測試縫注入合成檔期，維持跟其他隔離測試
一樣的可控性（見 app/dashboard/repository.py 檔頭說明）。

每個測試模組一個 Postgres schema（conftest.py 的 `_module_schema` fixture）。
測試品牌一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_dashboard_campaign_calendar_")

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import calendar_dismiss as core_calendar_dismiss  # noqa: E402
from app.core import campaign_skip as core_campaign_skip  # noqa: E402
from app.dashboard import repository as dashboard_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
TODAY = "2026-08-05"


class CampaignCalendarCockpitWiringTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構備戰茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        # 票 C：conversion_goal 沒設定會多冒出一張提醒卡，蓋掉本檔要測的檔期日曆卡；
        # 先設定好讓本檔繼續只測檔期日曆這一件事。
        bi_repo.set_brand_switches(main.conn, self.brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)

    def _cockpit(self, events):
        return dashboard_repo.cockpit(main.conn, self.brand["id"], today=TODAY,
                                      calendar_events=events)

    def test_campaign_stage_is_none_without_active_campaign(self):
        data = self._cockpit([{"id": "far", "name": "遠檔期", "date": "2028-01-01",
                               "tier": "large"}])
        self.assertIsNone(data["campaign_stage"])

    def test_campaign_stage_surfaces_current_stage_label(self):
        # 2026-08-05 到 2026-11-03 恰好 90 天，剛進大檔提前期窗口的第一天＝遠期備戰
        events = [{"id": "double11", "name": "雙11購物節", "date": "2026-11-03",
                  "tier": "large"}]
        data = self._cockpit(events)
        self.assertIsNotNone(data["campaign_stage"])
        self.assertEqual(data["campaign_stage"]["stage"], "遠期備戰")
        self.assertEqual(data["campaign_stage"]["name"], "雙11購物節")

    def test_guide_cards_include_campaign_reminder_pointing_to_open_new_cycle(self):
        events = [{"id": "double11", "name": "雙11購物節", "date": "2026-11-03",
                  "tier": "large"}]
        data = self._cockpit(events)
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertIn("雙11購物節", titles)
        card = next(c for c in data["guide_cards"] if "雙11購物節" in c["title"])
        self.assertEqual(card["action_url"], f"/app/brands/{self.brand['id']}/campaigns/new")

    def test_no_guide_card_when_no_event_in_window(self):
        data = self._cockpit([{"id": "far", "name": "遠檔期", "date": "2028-01-01",
                               "tier": "large"}])
        self.assertEqual(data["guide_cards"], [])


class CampaignCalendarIndustryRelevanceWiringTest(unittest.TestCase):
    """ADR 0014 第一節：brand.industry 一路接到 cockpit 的 campaign_stage／指南卡，
    業種對不到節日的 applicable_industries 清單就不提醒（完整流程，不只純函數）。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構業種備戰茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, self.brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)

    def _cockpit(self, events):
        return dashboard_repo.cockpit(main.conn, self.brand["id"], today=TODAY,
                                      calendar_events=events)

    def test_irrelevant_industry_suppresses_reminder_and_stage(self):
        bi_repo.set_brand_industry(main.conn, self.brand["id"],
                                   industry="food_beverage", actor=ACTOR)
        events = [{"id": "beauty_evt", "name": "美妝檔期", "date": "2026-11-03",
                  "tier": "large", "applicable_industries": ["beauty_personal_care"]}]
        data = self._cockpit(events)
        self.assertIsNone(data["campaign_stage"])
        self.assertEqual(data["guide_cards"], [])

    def test_matching_industry_surfaces_reminder_and_stage(self):
        bi_repo.set_brand_industry(main.conn, self.brand["id"],
                                   industry="beauty_personal_care", actor=ACTOR)
        events = [{"id": "beauty_evt", "name": "美妝檔期", "date": "2026-11-03",
                  "tier": "large", "applicable_industries": ["beauty_personal_care"]}]
        data = self._cockpit(events)
        self.assertIsNotNone(data["campaign_stage"])
        self.assertEqual(data["campaign_stage"]["name"], "美妝檔期")
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertIn("美妝檔期", titles)

    def test_all_tagged_event_ignores_brand_industry(self):
        """業種沒設定（None），節日標 all 一樣要提醒——不能因為業種未知就整批不提醒。"""
        events = [{"id": "double11", "name": "雙11購物節", "date": "2026-11-03",
                  "tier": "large", "applicable_industries": "all"}]
        data = self._cockpit(events)  # 未呼叫 set_brand_industry，industry 仍是 None
        self.assertIsNotNone(data["campaign_stage"])

    def test_set_brand_industry_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            bi_repo.set_brand_industry(main.conn, self.brand["id"],
                                       industry="not_a_real_industry", actor=ACTOR)


class CampaignSkipRecordWiringTest(unittest.TestCase):
    """票 03-cycle-skip-record（ADR 0015）：今年標記跳過後，明年同一節日提醒觸發時
    附帶顯示去年的理由。事件 id 逐年帶年份尾碼（見真實 campaign_calendar_data.json，
    cny_2026／cny_2027），跨年比對走 holiday_id()（去掉年份尾碼）。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構跳過紀錄茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, self.brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        # 明年（2027）同一節日的合成事件，today 訂在提前期窗口內、素材窗口外
        # （17 天前，小檔 30 天提前期成立、14 天素材窗口不成立，拿到 prep_reminder）。
        self.events = [{"id": "cny_2027", "name": "農曆新年", "date": "2027-02-06",
                        "tier": "small"}]
        self.today = "2027-01-20"

    def _cockpit(self):
        return dashboard_repo.cockpit(main.conn, self.brand["id"], today=self.today,
                                      calendar_events=self.events)

    def test_reminder_still_triggers_and_carries_last_year_reason(self):
        core_campaign_skip.record_skip(main.conn, self.brand["id"], "cny", 2026,
                                       reason="收假太晚，沒空間做素材")
        data = self._cockpit()
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertIn("農曆新年", titles, "去年跳過不代表明年不提醒")
        self.assertIn("收假太晚，沒空間做素材", titles)

    def test_no_skip_record_means_no_note(self):
        data = self._cockpit()
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertIn("農曆新年", titles)
        self.assertNotIn("跳過", titles)

    def test_skip_recorded_for_a_different_holiday_does_not_leak_in(self):
        core_campaign_skip.record_skip(main.conn, self.brand["id"], "double11", 2026,
                                       reason="不相干的理由")
        data = self._cockpit()
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertNotIn("不相干的理由", titles)

    def test_skip_reason_does_not_change_next_cycle_recommendation_facts(self):
        """驗收清單：跳過紀錄不寫入、不影響下期建議引擎的任何計算——這裡驗證同一份
        guide_card facts 裡除了 campaign_reminder 本身多出脈絡欄位外，其餘欄位
        （含跟下期建議相關的 active_cycle／next_cycle_draft_ready）完全不受影響。"""
        before = dashboard_repo._guide_card_facts(main.conn, self.brand["id"], None,
                                                   self.today, self.events)
        core_campaign_skip.record_skip(main.conn, self.brand["id"], "cny", 2026,
                                       reason="收假太晚")
        after = dashboard_repo._guide_card_facts(main.conn, self.brand["id"], None,
                                                  self.today, self.events)
        for key in ("active_cycle", "reading_ready", "next_cycle_draft_ready",
                    "pending_facts_count", "conversion_goal", "pacing_alert"):
            self.assertEqual(before[key], after[key], f"{key} 不該被跳過紀錄影響")


class CalendarDismissWiringTest(unittest.TestCase):
    """票 02-permanent-dismiss-category（ADR 0014 第二節）：品牌永久關閉某節日類別後，
    cockpit 的 campaign_stage／指南卡都不再提醒；重新開啟後恢復（完整流程，不只純函數）。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構永久覆寫茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, self.brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        self.events = [{"id": "cny_2026", "name": "農曆新年", "date": "2026-11-03",
                        "tier": "large", "applicable_industries": "all"}]

    def _cockpit(self):
        return dashboard_repo.cockpit(main.conn, self.brand["id"], today=TODAY,
                                      calendar_events=self.events)

    def test_dismissed_category_suppresses_stage_and_guide_card(self):
        core_calendar_dismiss.dismiss(main.conn, self.brand["id"], "cny")
        data = self._cockpit()
        self.assertIsNone(data["campaign_stage"])
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertNotIn("農曆新年", titles)

    def test_undismissed_category_restores_stage_and_guide_card(self):
        core_calendar_dismiss.dismiss(main.conn, self.brand["id"], "cny")
        core_calendar_dismiss.undismiss(main.conn, self.brand["id"], "cny")
        data = self._cockpit()
        self.assertIsNotNone(data["campaign_stage"])
        self.assertEqual(data["campaign_stage"]["name"], "農曆新年")
        titles = " ".join(c["title"] for c in data["guide_cards"])
        self.assertIn("農曆新年", titles)

    def test_dismissing_unrelated_category_does_not_leak_in(self):
        core_calendar_dismiss.dismiss(main.conn, self.brand["id"], "double11")
        data = self._cockpit()
        self.assertIsNotNone(data["campaign_stage"])
        self.assertEqual(data["campaign_stage"]["name"], "農曆新年")


class CampaignCalendarOverviewWiringTest(unittest.TestCase):
    def test_next_step_can_surface_campaign_reminder_when_nothing_else_pending(self):
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構總覽備戰雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        bi_repo.set_brand_switches(main.conn, brand["id"], market_region=None,
                                   conversion_goal="purchase", actor=ACTOR)
        events = [{"id": "double11", "name": "雙11購物節", "date": "2026-11-03",
                  "tier": "large"}]
        cards = dashboard_repo.overview(main.conn, today=TODAY, calendar_events=events)
        card = next(c for c in cards if c["brand_id"] == brand["id"])
        self.assertIsNotNone(card["next_step"])
        self.assertIn("雙11購物節", card["next_step"]["title"])


if __name__ == "__main__":
    unittest.main()
