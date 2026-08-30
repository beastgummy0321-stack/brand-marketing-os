"""app/tests/test_org_timezone.py — 票 04-1b：`today_for_org()` 讀不到合法時區時的退路。

「不同時區的組織看到不同的今天」由 test_meta_daily_spend.py 的
`SpendDateFollowsOrgTimezoneTest` 從資料層一路驗到底（那才是這件事真正會出錯的地方），
這裡只補它沒走到的那條分支：設定值壞掉或從沒設過，一律退回預設時區，不炸。
壞一格設定不該讓每日花費拉取整個停擺——那會從「日期差一天」升級成「那天沒有數字」。
"""

import unittest
from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
