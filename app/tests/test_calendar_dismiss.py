# -*- coding: utf-8 -*-
"""app/tests/test_calendar_dismiss.py — 票 02-permanent-dismiss-category：節日類別永久覆寫。

app/core/calendar_dismiss.py 的 CRUD 邏輯，用 conftest.py 逐模組建的 Postgres schema
（不需要起 FastAPI app）。每個測試方法用自己專屬的 brand id（不是共用字面值）：
conftest.py 的 schema 是整個模組共用一份，不是逐測試重建，共用 brand id 字面值會讓
不同測試方法在同一張表裡互相看到對方留下的列。
"""

import unittest

from app.core import calendar_dismiss, db


class ListDismissedTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.bid = f"brd_{db.new_id('t')}"

    def test_empty_state_no_dismissed_categories(self):
        """G14.10 空狀態：品牌從沒關過任何類別，list_dismissed 回空集合（等同全部提醒中）。"""
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), set())

    def test_dismiss_adds_to_dismissed_set(self):
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), {"cny"})

    def test_dismiss_is_idempotent_not_duplicated(self):
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        rows = self.conn.execute(
            "SELECT COUNT(*) AS c FROM brand_dismissed_calendar_category"
            " WHERE brand_id = %s AND category = %s", (self.bid, "cny")).fetchone()
        self.assertEqual(rows["c"], 1, "重複關閉同一類別不該疊加成兩列")

    def test_undismiss_removes_from_dismissed_set(self):
        """驗收清單：重新開啟＝刪除該筆，恢復提醒。"""
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        calendar_dismiss.undismiss(self.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), set())

    def test_undismiss_on_never_dismissed_category_is_a_no_op(self):
        calendar_dismiss.undismiss(self.conn, self.bid, "valentine")  # 不報錯
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), set())

    def test_multiple_categories_can_be_dismissed_independently(self):
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        calendar_dismiss.dismiss(self.conn, self.bid, "valentine")
        calendar_dismiss.undismiss(self.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), {"valentine"})

    def test_different_brand_is_independent(self):
        other = f"brd_{db.new_id('t')}"
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, other), set())


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
    """刪品牌時 brand_dismissed_calendar_category 要被清掉（app.core.cleanup 登記，機器閘門
    見 ticket 02-5——舊版漏表警報器 test_cleanup_coverage.py 已刪，理由見 02-4-deleted.md）。"""

    def setUp(self):
        self.conn = db.current()
        self.bid = f"brd_{db.new_id('t')}"

    def test_delete_brand_data_removes_rows_and_count_matches(self):
        calendar_dismiss.dismiss(self.conn, self.bid, "cny")
        calendar_dismiss.dismiss(self.conn, self.bid, "valentine")
        self.assertEqual(
            dict(calendar_dismiss.count_brand_data(self.conn, self.bid)),
            {"節日類別永久覆寫": 2})

        counts = calendar_dismiss.delete_brand_data(self.conn, self.bid)
        self.conn.commit()
        self.assertEqual(counts, {"節日類別永久覆寫": 2})
        self.assertEqual(calendar_dismiss.list_dismissed(self.conn, self.bid), set())

    def test_count_skips_brands_with_no_rows(self):
        self.assertEqual(calendar_dismiss.count_brand_data(self.conn, f"brd_{db.new_id('t')}"), [])


if __name__ == "__main__":
    unittest.main()
