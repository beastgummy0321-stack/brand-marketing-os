"""app/tests/test_product_economics_version.py — 票 T2c（ADR 0053 §5）：成本只能從今天生效、
絕不回溯。用 mock.patch.object 假 today_for_org()，不真的跨日等待。"""

import unittest
from datetime import date
from unittest import mock

from app.brand_intelligence import repository as repo
from app.core import db


class ProductEconomicsVersionTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.bid = repo.create_brand(self.conn, name="測試茶行（成本版本）", client_name="測試客戶",
                                      actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        self.pid = repo.create_product(self.conn, self.bid, name="測試茶包", actor="測試員")["id"]

    def _save(self, price, today):
        with mock.patch.object(repo.coresettings, "today_for_org", return_value=today):
            repo.save_product_economics(self.conn, self.bid, self.pid, selling_price=price,
                                         currency="TWD", confirmed_by="測試員", actor="測試員")

    def _open_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM product_economics_version"
            " WHERE product_id = %s AND effective_to IS NULL", (self.pid,)).fetchone()["n"]

    def test_cost_change_applies_from_today_never_backwards(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        self._save(300, d1)
        self._save(350, d2)
        self.assertEqual(repo.economics_at(self.conn, self.bid, self.pid, d1)["selling_price"], 300)
        self.assertEqual(repo.economics_at(self.conn, self.bid, self.pid, d2)["selling_price"], 350)
        self.assertEqual(self._open_count(), 1)

    def test_two_saves_same_day_leave_one_open_one_zero_length_closed(self):
        today = date(2026, 9, 3)
        self._save(300, today)
        self._save(350, today)  # 不該炸在 partial unique index 上
        rows = self.conn.execute(
            "SELECT effective_from, effective_to FROM product_economics_version"
            " WHERE product_id = %s ORDER BY version", (self.pid,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["effective_to"], today)  # 零長度：[today, today)
        self.assertIsNone(rows[1]["effective_to"])
        self.assertEqual(self._open_count(), 1)

    def test_list_price_and_cap_are_versioned_and_kept(self):
        """F43-I01: list_price / cap_per_sale travel with each version; a save that does not pass
        them (an editor from before F43) keeps the stored values."""
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        with mock.patch.object(repo.coresettings, "today_for_org", return_value=d1):
            repo.save_product_economics(self.conn, self.bid, self.pid, selling_price=359,
                                         currency="TWD", confirmed_by="測試員", actor="測試員",
                                         list_price=399, cap_per_sale=150)
        self._save(349, d2)
        self.assertEqual((repo.economics_at(self.conn, self.bid, self.pid, d1)["list_price"],
                          repo.economics_at(self.conn, self.bid, self.pid, d2)["list_price"],
                          repo.economics_at(self.conn, self.bid, self.pid, d2)["cap_per_sale"]),
                         (399, 399, 150))
