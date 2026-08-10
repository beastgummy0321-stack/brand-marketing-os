# -*- coding: utf-8 -*-
"""app/tests/test_calendar_dismiss.py — 票 02-permanent-dismiss-category：節日類別永久覆寫。

app/core/calendar_dismiss.py 的 CRUD 邏輯，隔離 tmp SQLite DB（比照
app/tests/test_campaign_skip.py 風格，不需要起 FastAPI app）。
"""

import tempfile
import unittest
from pathlib import Path

from app.core import calendar_dismiss, db


class ListDismissedTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_empty_state_no_dismissed_categories(self):
        """G14.10 空狀態：品牌從沒關過任何類別，list_dismissed 回空集合（等同全部提醒中）。"""
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), set())

    def test_dismiss_adds_to_dismissed_set(self):
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), {"cny"})

    def test_dismiss_is_idempotent_not_duplicated(self):
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM brand_dismissed_calendar_category"
            " WHERE brand_id = ? AND category = ?", ("brd_x", "cny")).fetchone()
        self.assertEqual(rows["c"], 1, "重複關閉同一類別不該疊加成兩列")

    def test_undismiss_removes_from_dismissed_set(self):
        """驗收清單：重新開啟＝刪除該筆，恢復提醒。"""
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        calendar_dismiss.undismiss(self.conn, "brd_x", "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), set())

    def test_undismiss_on_never_dismissed_category_is_a_no_op(self):
        calendar_dismiss.undismiss(self.conn, "brd_x", "valentine")  # 不報錯
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), set())

    def test_multiple_categories_can_be_dismissed_independently(self):
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        calendar_dismiss.dismiss(self.conn, "brd_x", "valentine")
        calendar_dismiss.undismiss(self.conn, "brd_x", "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), {"valentine"})

    def test_different_brand_is_independent(self):
        calendar_dismiss.dismiss(self.conn, "brd_a", "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_b"), set())


class ListCategoriesTest(unittest.TestCase):
    """節日類別清單：去重後供設定中心出清單，也供 toggle 路由驗證合法性。"""

    def test_returns_unique_categories_with_labels(self):
        categories = calendar_dismiss.list_categories()
        self.assertGreater(len(categories), 0)
        keys = [c["category"] for c in categories]
        self.assertEqual(len(keys), len(set(keys)), "跨年份的同一節日只該出現一次")
        for c in categories:
            self.assertIn("category", c)
            self.assertIn("label", c)

    def test_known_holiday_included_with_correct_label(self):
        categories = {c["category"]: c["label"] for c in calendar_dismiss.list_categories()}
        self.assertEqual(categories.get("cny"), "農曆新年")
        self.assertEqual(categories.get("double11"), "雙11購物節")


class CleanupRegistrationTest(unittest.TestCase):
    """刪品牌時 brand_dismissed_calendar_category 要被清掉（app.core.cleanup 登記，
    test_cleanup_coverage.py 的漏表警報器會擋沒登記的帶 brand_id 新表）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_delete_brand_data_removes_rows_and_count_matches(self):
        calendar_dismiss.dismiss(self.conn, "brd_x", "cny")
        calendar_dismiss.dismiss(self.conn, "brd_x", "valentine")
        self.assertEqual(
            dict(calendar_dismiss.count_brand_data(self.conn, "brd_x")),
            {"節日類別永久覆寫": 2})

        counts = calendar_dismiss.delete_brand_data(self.conn, "brd_x")
        self.conn.commit()
        self.assertEqual(counts, {"節日類別永久覆寫": 2})
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, "brd_x"), set())

    def test_count_skips_brands_with_no_rows(self):
        self.assertEqual(calendar_dismiss.count_brand_data(self.conn, "brd_empty"), [])


if __name__ == "__main__":
    unittest.main()
