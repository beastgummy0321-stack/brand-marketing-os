# -*- coding: utf-8 -*-
"""app/tests/test_product_delete.py — 永久刪除產品（決策 0020，比照品牌 0015）。

守四件事：
1. 使用中的產品刪不掉（一定要先封存）。
2. 刪掉之後，這個產品在所有掛的子表都不留一列，audit_log 留得下 before 全文與各表筆數。
3. 別的產品、品牌層資料一列都不能少（刪除只挑 product_id 對得上的列）。
4. 封存 → 恢復使用來回不留副作用。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.brand_intelligence import repository as repo
from app.core import db


class ProductDeleteTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _seed_product(self, brand_id, name):
        """一個產品，每張子表都塞一列，才驗得出「刪乾淨」。"""
        pid = repo.create_product(self.conn, brand_id, name=name, actor="測試員")["id"]
        repo.create_product_fact(self.conn, brand_id, pid, fact_type="core_info", label="規格",
                                  value="測試", status="pending", actor="測試員")
        repo.save_product_economics(self.conn, brand_id, pid, selling_price=100, currency="TWD",
                                     confirmed_by="測試員", actor="測試員")
        repo.create_rule(self.conn, brand_id, rule_type="tone", content="測試規則",
                          severity="soft", product_id=pid, actor="測試員")
        repo.create_claim(self.conn, brand_id, claim_text="測試宣稱", claim_type="approved",
                           product_id=pid, actor="測試員")
        repo.create_official_asset(self.conn, brand_id, asset_kind="logo",
                                    file_path="C:/tmp/logo.png", product_id=pid, actor="測試員")
        repo.create_strategy_hypothesis(self.conn, brand_id, hypothesis_type="audience",
                                         statement="測試假設", created_by="測試員",
                                         product_id=pid, actor="測試員")
        repo.create_brand_performance_baseline(self.conn, brand_id, metric="典型CTR", value=1.2,
                                                as_of_date="2026-01-01", created_by="測試員",
                                                product_id=pid, actor="測試員")
        return pid

    def _row_counts(self, product_id):
        return {t: self.conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE product_id = ?", (product_id,)).fetchone()[0]
            for t, _label in repo.PRODUCT_CHILD_TABLES}

    def test_active_product_cannot_be_deleted(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除）", client_name="測試客戶",
                                 actor="測試員")["id"]
        pid = self._seed_product(bid, "未封存產品（刪除測試）")
        with self.assertRaises(ValueError):
            repo.delete_product(self.conn, bid, pid, actor="測試員")
        self.assertIsNotNone(repo.get_product(self.conn, bid, pid))

    def test_archived_product_is_wiped_from_every_child_table(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除2）", client_name="測試客戶",
                                 actor="測試員")["id"]
        pid = self._seed_product(bid, "待刪產品（刪除測試）")
        self.assertTrue(all(n > 0 for n in self._row_counts(pid).values()))

        repo.update_product(self.conn, bid, pid, name="待刪產品（刪除測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, pid, actor="測試員")

        self.assertIsNone(repo.get_product(self.conn, bid, pid))
        self.assertEqual(set(self._row_counts(pid).values()), {0})

    def test_delete_leaves_audit_trail(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除3）", client_name="測試客戶",
                                 actor="測試員")["id"]
        pid = self._seed_product(bid, "留痕產品（刪除測試）")
        repo.update_product(self.conn, bid, pid, name="留痕產品（刪除測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, pid, actor="測試員")

        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'product' AND action = 'delete' "
            "AND entity_id = ?", (pid,)).fetchone()
        self.assertIsNotNone(row)
        before = json.loads(row["before_json"])
        self.assertEqual(before["name"], "留痕產品（刪除測試）")
        self.assertEqual(before["deleted_counts"]["產品事實"], 1)
        self.assertEqual(row["actor"], "測試員")

    def test_other_product_and_brand_level_rows_untouched(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除4）", client_name="測試客戶",
                                 actor="測試員")["id"]
        gone = self._seed_product(bid, "要刪的產品（隔離測試）")
        kept = self._seed_product(bid, "留著的產品（隔離測試）")
        # 品牌層規則（product_id=None），不該被產品刪除動到。
        repo.create_rule(self.conn, bid, rule_type="tone", content="品牌層規則",
                          severity="soft", actor="測試員")
        before_kept = self._row_counts(kept)
        before_brand_rules = self.conn.execute(
            "SELECT COUNT(*) FROM rule WHERE brand_id = ? AND product_id IS NULL", (bid,)
        ).fetchone()[0]

        repo.update_product(self.conn, bid, gone, name="要刪的產品（隔離測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, gone, actor="測試員")

        self.assertEqual(self._row_counts(kept), before_kept)
        self.assertIsNotNone(repo.get_product(self.conn, bid, kept))
        after_brand_rules = self.conn.execute(
            "SELECT COUNT(*) FROM rule WHERE brand_id = ? AND product_id IS NULL", (bid,)
        ).fetchone()[0]
        self.assertEqual(after_brand_rules, before_brand_rules)

    def test_archive_and_restore_round_trip(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（封存恢復）", client_name="測試客戶",
                                 actor="測試員")["id"]
        pid = repo.create_product(self.conn, bid, name="來回封存產品", actor="測試員")["id"]

        archived = repo.update_product(self.conn, bid, pid, name="來回封存產品",
                                        status="archived", actor="測試員")
        self.assertEqual(archived["status"], "archived")

        restored = repo.update_product(self.conn, bid, pid, name="來回封存產品",
                                        status="active", actor="測試員")
        self.assertEqual(restored["status"], "active")
        self.assertIsNotNone(repo.get_product(self.conn, bid, pid))


if __name__ == "__main__":
    unittest.main()
