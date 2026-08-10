# -*- coding: utf-8 -*-
"""app/tests/test_ads_occasion.py — 票 01-occasion-auto-tagging：檔期情境自動標籤。

品牌名一律虛構，絕不使用真實客戶品牌。

涵蓋：
1. 純函數 match_occasion：落在節日投放窗口內 vs. 沒落在任何窗口內（ADR 0011 第四節，
   驗收清單指名要涵蓋的兩種情況）。
2. 開新檔期（app/ads/repository.create_cycle）真的把比對結果寫進 occasion 欄位，
   兩種情況都要驗（帶入節日名稱／常態檔期為 None）。
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.ads import occasion as ads_occasion
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"

_EVENTS = [{"id": "mothers_day_2026", "name": "母親節", "date": "2026-05-10", "tier": "large"}]


class MatchOccasionTest(unittest.TestCase):
    """純函數，不碰資料庫——ADR 0011 第四節「時間窗口重疊即帶入節日名稱」的核心邏輯。"""

    def test_cycle_overlapping_holiday_window_gets_tagged(self):
        """檔期涵蓋節日當天，落在投放窗口內：帶入節日名稱。"""
        result = ads_occasion.match_occasion(_EVENTS, date(2026, 5, 1), date(2026, 5, 14))
        self.assertEqual(result, "母親節")

    def test_cycle_inside_lead_days_but_before_holiday_still_tagged(self):
        """檔期沒碰到節日當天、但落在大檔 90 天投放窗口內（4/1–4/14，早於 5/10）：仍要帶入
        節日名稱——這條專門驗證投放窗口真的往節日前推 LEAD_DAYS 天，不是只認節日當天。"""
        result = ads_occasion.match_occasion(_EVENTS, date(2026, 4, 1), date(2026, 4, 14))
        self.assertEqual(result, "母親節")

    def test_cycle_before_window_opens_is_untagged(self):
        """檔期在投放窗口開啟前就結束，沒對到任何節日：回 None（常態檔期）。"""
        result = ads_occasion.match_occasion(_EVENTS, date(2026, 1, 1), date(2026, 1, 14))
        self.assertIsNone(result)

    def test_cycle_after_holiday_is_untagged(self):
        """投放窗口只往節日前推，節日過後開始的檔期不算搭上這個節日。"""
        result = ads_occasion.match_occasion(_EVENTS, date(2026, 5, 11), date(2026, 5, 20))
        self.assertIsNone(result)

    def test_closest_event_wins_when_windows_overlap(self):
        """兩個節日的投放窗口同時蓋到這期檔期時，取節日當天離檔期起始日最近的一筆。"""
        events = [
            {"id": "a", "name": "節日A", "date": "2026-05-10", "tier": "large"},  # 窗口早開
            {"id": "b", "name": "節日B", "date": "2026-05-03", "tier": "small"},  # 離起始日更近
        ]
        result = ads_occasion.match_occasion(events, date(2026, 5, 1), date(2026, 5, 5))
        self.assertEqual(result, "節日B")


class CreateCycleWritesOccasionTest(unittest.TestCase):
    """開新檔期時，occasion 欄位要真的有值或維持 None——這是本票要接上的行為。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_cycle_in_holiday_window_gets_occasion_from_real_calendar(self):
        """真實節日日曆（母親節 2026-05-10，大檔，投放窗口 90 天）：檔期落在窗口內。"""
        cycle = ads_repo.create_cycle(
            self.conn, self.bid, product_ids=[], pain_value=5000, objective="sales",
            actor=ACTOR, start_date="2026-05-01", duration_days=14)
        self.assertEqual(cycle["occasion"], "母親節")
        stored = ads_repo.get_cycle(self.conn, self.bid, cycle["id"])
        self.assertEqual(stored["occasion"], "母親節", "回傳值跟寫進資料庫的值必須一致")

    def test_cycle_outside_any_holiday_window_is_normal_cycle(self):
        """618（06-18）跟雙11投放窗口（08-13 起）之間的空檔：沒對到任何節日，occasion 為 None。"""
        cycle = ads_repo.create_cycle(
            self.conn, self.bid, product_ids=[], pain_value=5000, objective="sales",
            actor=ACTOR, start_date="2026-07-01", duration_days=14)
        self.assertIsNone(cycle["occasion"])
        stored = ads_repo.get_cycle(self.conn, self.bid, cycle["id"])
        self.assertIsNone(stored["occasion"])


if __name__ == "__main__":
    unittest.main()
