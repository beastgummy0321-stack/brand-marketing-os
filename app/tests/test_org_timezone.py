"""app/tests/test_org_timezone.py — 票 04-1b：`today_for_org()` 讀不到合法時區時的退路。

「不同時區的組織看到不同的今天」由 test_meta_daily_spend.py 的
`SpendDateFollowsOrgTimezoneTest` 從資料層一路驗到底（那才是這件事真正會出錯的地方），
這裡只補它沒走到的那條分支：設定值壞掉或從沒設過，一律退回預設時區，不炸。
壞一格設定不該讓每日花費拉取整個停擺——那會從「日期差一天」升級成「那天沒有數字」。

F50 Contract K (`OneClockTest`): every helper of the one clock reads its instant from
`db.now_utc()`, so patching that one function (as the drill clock does) moves them all.
"""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from app.core import db
from app.core import settings as coresettings

ORG = "org_tz_fallback_test"


class OrgTimezoneFallbackTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING", (ORG, ORG))
        self.conn.commit()
        self.taipei_today = datetime.now(ZoneInfo(coresettings.DEFAULT_ORG_TIMEZONE)).date()

    def tearDown(self):
        self.conn.execute("DELETE FROM app_setting WHERE org_id = %s", (ORG,))
        self.conn.execute("DELETE FROM organisation WHERE id = %s", (ORG,))
        self.conn.commit()

    def test_never_set_or_broken_values_all_fall_back_to_taipei(self):
        self.assertEqual(coresettings.today_for_org(self.conn, org_id=ORG), self.taipei_today,
                         "沒設過時區的組織應該拿到預設的 Asia/Taipei")
        for broken in ("Asia/Taipeh", "", "not a timezone"):
            coresettings.set_setting(
                self.conn, coresettings.ORG_TIMEZONE_SETTING, broken, org_id=ORG)
            self.conn.commit()
            self.assertEqual(coresettings.today_for_org(self.conn, org_id=ORG), self.taipei_today,
                             f"壞值 {broken!r} 應該退回預設時區，不是拋例外")



class OneClockTest(unittest.TestCase):
    """F50 Contract K: the org's day, month start and last complete day follow `db.now_utc`."""

    def setUp(self):
        self.conn = db.current()
        self.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING", (ORG, ORG))
        self.conn.execute("DELETE FROM app_setting WHERE org_id = %s", (ORG,))
        self.conn.commit()

    def tearDown(self):
        self.conn.execute("DELETE FROM app_setting WHERE org_id = %s", (ORG,))
        self.conn.execute("DELETE FROM organisation WHERE id = %s", (ORG,))
        self.conn.commit()

    def _at(self, instant: datetime):
        return mock.patch.object(db, "now_utc", return_value=instant)

    def test_today_for_org_follows_db_now_utc(self):
        # 23:30 UTC on 31 Oct is 07:30 on 1 Nov in Taipei: the org's day is already the 1st.
        with self._at(datetime(2026, 10, 31, 23, 30, tzinfo=UTC)):
            self.assertEqual(coresettings.today_for_org(self.conn, org_id=ORG), date(2026, 11, 1))
            self.assertEqual(coresettings.today_in(ZoneInfo("America/Los_Angeles")),
                             date(2026, 10, 31))

    def test_last_complete_day_with_and_without_a_zone(self):
        with self._at(datetime(2026, 10, 31, 23, 30, tzinfo=UTC)):
            self.assertEqual(coresettings.last_complete_day(self.conn, org_id=ORG),
                             date(2026, 10, 31), "no zone: the org's yesterday (Taipei)")
            self.assertEqual(
                coresettings.last_complete_day(self.conn, org_id=ORG,
                                               zone=ZoneInfo("America/Los_Angeles")),
                date(2026, 10, 30), "a zone: that zone's yesterday (16:30 on 31 Oct in LA)")

    def test_last_complete_day_follows_a_patched_today_for_org(self):
        # Tests and the drill tool patch the module attribute; the helper must see it.
        with mock.patch.object(coresettings, "today_for_org", return_value=date(2026, 3, 1)):
            self.assertEqual(coresettings.last_complete_day(self.conn, org_id=ORG),
                             date(2026, 2, 28))

    def test_org_month_start_at_seven_on_the_first_is_this_month(self):
        # 07:00 Taipei on 1 Nov = 23:00 UTC on 31 Oct: the machine's month is still October.
        with self._at(datetime(2026, 10, 31, 23, 0, tzinfo=UTC)):
            start = coresettings.org_month_start(self.conn, org_id=ORG)
        self.assertEqual(start, datetime(2026, 10, 31, 16, 0, tzinfo=UTC))
        self.assertEqual(start.astimezone(ZoneInfo("Asia/Taipei")).date(), date(2026, 11, 1))

    def test_org_day_start_is_midnight_in_the_org_zone(self):
        coresettings.set_setting(self.conn, coresettings.ORG_TIMEZONE_SETTING,
                                 "America/New_York", org_id=ORG)
        start = coresettings.org_day_start(self.conn, org_id=ORG, day=date(2026, 10, 5))
        self.assertEqual(start, datetime(2026, 10, 5, 4, 0, tzinfo=UTC))  # EDT = UTC-4

    def test_day_window_has_exactly_that_many_dates(self):
        start, end = coresettings.day_window(date(2026, 10, 5), 30)
        self.assertEqual((start, end), (date(2026, 9, 6), date(2026, 10, 5)))
        self.assertEqual((end - start).days + 1, 30)
        self.assertEqual(coresettings.day_window(date(2026, 10, 5), 1),
                         (date(2026, 10, 5), date(2026, 10, 5)))
        self.assertEqual(start + timedelta(days=29), end)


if __name__ == "__main__":
    unittest.main()
