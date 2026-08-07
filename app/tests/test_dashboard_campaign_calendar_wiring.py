# -*- coding: utf-8 -*-
"""app/tests/test_dashboard_campaign_calendar_wiring.py — 票 06-campaign-calendar：
儀表板 API 接上檔期日曆真貨源（純函數邏輯已在 test_campaign_calendar.py 測過，這裡
只驗證 repository 有把純函數結果組進指南卡與駕駛艙 campaign_stage 欄位）。

真實檔期日期是外部世界的事實（雙11 就是 11 月 11 日），沒辦法像訂單那樣隨測試
「今天」調整，所以用 calendar_events 這個測試縫注入合成檔期，維持跟其他隔離測試
一樣的可控性（見 app/dashboard/repository.py 檔頭說明）。

隔離測試資料庫（BRAND_OS_DB 指向 tmp 檔）。測試品牌一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_dashboard_campaign_calendar_")
os.environ["BRAND_OS_DB"] = str(os.path.join(_tmpdir, "test.db"))
os.environ["BRAND_OS_BACKUP_DIR"] = str(os.path.join(_tmpdir, "backups"))
os.environ["BRAND_OS_UPLOADS"] = str(os.path.join(_tmpdir, "uploads"))

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.dashboard import repository as dashboard_repo  # noqa: E402

main.reopen_connection()


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
        self.assertEqual(card["action_url"], f"/brands/{self.brand['id']}/ads/new")

    def test_no_guide_card_when_no_event_in_window(self):
        data = self._cockpit([{"id": "far", "name": "遠檔期", "date": "2028-01-01",
                               "tier": "large"}])
        self.assertEqual(data["guide_cards"], [])


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
