"""app/tests/test_campaign_skip.py — 票 03-cycle-skip-record：這期跳過紀錄。

app/core/campaign_skip.py 的 CRUD 邏輯，用 conftest.py 逐模組建的 Postgres schema
（不需要起 FastAPI app）。每個測試方法用自己專屬的 brand id（不是共用字面值）：
conftest.py 的 schema 是整個模組共用一份，不是逐測試重建，共用 brand id 字面值會讓
不同測試方法在同一張表裡互相看到對方留下的列。
"""

import unittest
from pathlib import Path

from app.core import campaign_skip, db

_NEXTCYCLE_PATH = Path(__file__).resolve().parent.parent / "ads" / "nextcycle.py"


class NextCycleEngineNotCoupledTest(unittest.TestCase):
    """驗收清單：跳過紀錄不寫入、不影響下期建議引擎（app/ads/nextcycle.py）的任何計算
    （ADR 0015 第二節）。最直接、最不會腐爛的保證：下期建議引擎的原始碼裡完全不提
    campaign_skip 這個字——沒有 import 就沒有耦合，之後有人想接進去也會在 code review
    被這條測試攔下來。"""

    def test_nextcycle_source_never_mentions_campaign_skip(self):
        self.assertTrue(_NEXTCYCLE_PATH.exists(), f"{_NEXTCYCLE_PATH} 不存在")
        text = _NEXTCYCLE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("campaign_skip", text)


class RecordAndGetSkipTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.bid = f"brd_{db.new_id('t')}"

    def test_no_record_returns_none(self):
        self.assertIsNone(campaign_skip.get_skip(self.conn, self.bid, "cny", 2026))

    def test_record_with_reason_is_retrievable(self):
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="收假太晚",
            org_id=db.DEV_ORG_ID)
        self.assertEqual(
            campaign_skip.get_skip(self.conn, self.bid, "cny", 2026), {"reason": "收假太晚"})

    def test_reason_is_optional(self):
        campaign_skip.record_skip(self.conn, self.bid, "valentine", 2026, org_id=db.DEV_ORG_ID)
        self.assertEqual(
            campaign_skip.get_skip(self.conn, self.bid, "valentine", 2026), {"reason": None})

    def test_repeated_record_overwrites_reason_not_duplicates(self):
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="舊理由",
            org_id=db.DEV_ORG_ID)
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="新理由",
            org_id=db.DEV_ORG_ID)
        self.assertEqual(
            campaign_skip.get_skip(self.conn, self.bid, "cny", 2026), {"reason": "新理由"})
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM campaign_skip WHERE brand_id = %s AND holiday_id = %s"
            " AND year = %s", (self.bid, "cny", 2026)).fetchone()
        self.assertEqual(rows["c"], 1, "同品牌＋節日＋年份只該留一列，不是疊加")

    def test_different_year_is_independent(self):
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="今年跳過",
            org_id=db.DEV_ORG_ID)
        self.assertIsNone(campaign_skip.get_skip(self.conn, self.bid, "cny", 2027))

    def test_different_brand_is_independent(self):
        other = f"brd_{db.new_id('t')}"
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="A 跳過",
            org_id=db.DEV_ORG_ID)
        self.assertIsNone(campaign_skip.get_skip(self.conn, other, "cny", 2026))


class CleanupRegistrationTest(unittest.TestCase):
    """刪品牌時 campaign_skip 要被清掉（app.core.cleanup 登記；機器閘門見 ticket 02-5——
    舊版漏表警報器 test_cleanup_coverage.py 已刪，理由見 02-4-deleted.md）。這裡直接驗證
    登記函式本身行為正確。"""

    def setUp(self):
        self.conn = db.current()
        self.bid = f"brd_{db.new_id('t')}"

    def test_delete_brand_data_removes_rows_and_count_matches(self):
        campaign_skip.record_skip(self.conn, self.bid, "cny", 2026, reason="理由",
            org_id=db.DEV_ORG_ID)
        campaign_skip.record_skip(self.conn, self.bid, "valentine", 2026, org_id=db.DEV_ORG_ID)
        self.assertEqual(
            dict(campaign_skip.count_brand_data(self.conn, self.bid)), {"檔期跳過紀錄": 2})

        counts = campaign_skip.delete_brand_data(self.conn, self.bid)
        self.conn.commit()
        self.assertEqual(counts, {"檔期跳過紀錄": 2})
        self.assertIsNone(campaign_skip.get_skip(self.conn, self.bid, "cny", 2026))

    def test_count_skips_brands_with_no_rows(self):
        self.assertEqual(campaign_skip.count_brand_data(self.conn, f"brd_{db.new_id('t')}"), [])


if __name__ == "__main__":
    unittest.main()
