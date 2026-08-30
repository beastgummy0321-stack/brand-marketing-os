"""app/tests/test_product_delete.py — 永久刪除產品（決策 0020，比照品牌 0015）。

守四件事：
1. 使用中的產品刪不掉（一定要先封存）。
2. 刪掉之後，這個產品在所有掛的子表都不留一列，audit_log 留得下 before 全文與各表筆數。
3. 別的產品、品牌層資料一列都不能少（刪除只挑 product_id 對得上的列）。
4. 封存 → 恢復使用來回不留副作用。
"""

import unittest

from app.brand_intelligence import repository as repo
from app.core import db


class ProductDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

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
                                    storage_key=f"{db.DEV_ORG_ID}/brands/{brand_id}/assets/oas_fake/logo.png",
                                    product_id=pid, actor="測試員")
        # strategy_hypothesis／learning_ledger 沒有寫入端了（票 04：唯一寫入端隨 app/ads/
        # 一起刪除，表留著）。
        self.conn.execute(
            "INSERT INTO strategy_hypothesis (id, org_id, brand_id, product_id, hypothesis_type,"
            " statement, status, created_by, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, 'audience', '測試假設', 'proposed', '測試員', %s, %s)",
            (db.new_id("hyp"), db.DEV_ORG_ID, brand_id, pid, db.now_utc(), db.now_utc()),
        )
        self.conn.commit()
        repo.create_brand_performance_baseline(self.conn, brand_id, metric="典型CTR", value=1.2,
                                                as_of_date="2026-01-01", created_by="測試員",
                                                product_id=pid, actor="測試員")
        self.conn.execute(
            "INSERT INTO learning_ledger (id, org_id, brand_id, product_id, learning_text,"
            " applicability_scope, learned_at, created_by, created_at, source_track)"
            " VALUES (%s, %s, %s, %s, '測試學習', 'product', %s, '測試員', %s, 'ads')",
            (db.new_id("lrn"), db.DEV_ORG_ID, brand_id, pid, db.now_utc(), db.now_utc()),
        )
        self.conn.commit()
        return pid

    def _row_counts(self, product_id):
        return {t: self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {t} WHERE product_id = %s", (product_id,)).fetchone()["n"]
            for t, _label in repo.PRODUCT_CHILD_TABLES}

    def test_active_product_cannot_be_deleted(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        pid = self._seed_product(bid, "未封存產品（刪除測試）")
        with self.assertRaises(ValueError):
            repo.delete_product(self.conn, bid, pid, actor="測試員")
        self.assertIsNotNone(repo.get_product(self.conn, bid, pid))

    def test_archived_product_is_wiped_from_every_child_table(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除2）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        pid = self._seed_product(bid, "待刪產品（刪除測試）")
        self.assertTrue(all(n > 0 for n in self._row_counts(pid).values()))

        repo.update_product(self.conn, bid, pid, name="待刪產品（刪除測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, pid, actor="測試員")

        self.assertIsNone(repo.get_product(self.conn, bid, pid))
        self.assertEqual(set(self._row_counts(pid).values()), {0})

    def test_failure_midway_rolls_back_everything(self):
        """刪除中途出錯要整批回捲：產品與所有子資料原封不動，也不留刪除稽核。

        ADR 0027：一條連線一個 request，不 commit 不等於自動回捲——沒有明確 rollback
        的話，懸著的 DELETE 會在這條連線被歸還連線池、下次借出時才被沖掉，而且沒有
        紀錄。這條測試守的就是那個明確的 rollback（見 repository.py delete_product()
        的 try/except）。
        """
        bid = repo.create_brand(self.conn, name="測試皂坊（產品回捲）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        pid = self._seed_product(bid, "回捲產品（刪除測試）")
        before = self._row_counts(pid)
        repo.update_product(self.conn, bid, pid, name="回捲產品（刪除測試）",
                             status="archived", actor="測試員")

        # write_audit 在所有 DELETE 之後、commit 之前執行，讓它爆掉最能驗出回捲
        original = repo.write_audit
        repo.write_audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("故意失敗"))
        try:
            with self.assertRaises(RuntimeError):
                repo.delete_product(self.conn, bid, pid, actor="測試員")
        finally:
            repo.write_audit = original

        self.assertIsNotNone(repo.get_product(self.conn, bid, pid), "產品應該原封不動還在")
        self.assertEqual(self._row_counts(pid), before, "子資料應該一列都沒少")
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM audit_log WHERE entity_type = 'product' AND action = 'delete' "
            "AND entity_id = %s", (pid,)).fetchone(), "不該留下刪除稽核")

    def test_delete_leaves_audit_trail(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除3）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        pid = self._seed_product(bid, "留痕產品（刪除測試）")
        repo.update_product(self.conn, bid, pid, name="留痕產品（刪除測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, pid, actor="測試員")

        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'product' AND action = 'delete' "
            "AND entity_id = %s", (pid,)).fetchone()
        self.assertIsNotNone(row)
        before = row["before_json"]  # jsonb 欄位，psycopg 已自動解碼成 dict，不必 json.loads
        self.assertEqual(before["name"], "留痕產品（刪除測試）")
        self.assertEqual(before["deleted_counts"]["產品事實"], 1)
        self.assertEqual(row["actor"], "測試員")

    def test_other_product_and_brand_level_rows_untouched(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（產品刪除4）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        gone = self._seed_product(bid, "要刪的產品（隔離測試）")
        kept = self._seed_product(bid, "留著的產品（隔離測試）")
        # 品牌層規則（product_id=None），不該被產品刪除動到。
        repo.create_rule(self.conn, bid, rule_type="tone", content="品牌層規則",
                          severity="soft", actor="測試員")
        before_kept = self._row_counts(kept)
        before_brand_rules = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule WHERE brand_id = %s AND product_id IS NULL", (bid,)
        ).fetchone()["n"]

        repo.update_product(self.conn, bid, gone, name="要刪的產品（隔離測試）",
                             status="archived", actor="測試員")
        repo.delete_product(self.conn, bid, gone, actor="測試員")

        self.assertEqual(self._row_counts(kept), before_kept)
        self.assertIsNotNone(repo.get_product(self.conn, bid, kept))
        after_brand_rules = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule WHERE brand_id = %s AND product_id IS NULL", (bid,)
        ).fetchone()["n"]
        self.assertEqual(after_brand_rules, before_brand_rules)

    def test_archive_and_restore_round_trip(self):
        bid = repo.create_brand(self.conn, name="測試皂坊（封存恢復）", client_name="測試客戶",
                                 actor="測試員", org_id=db.DEV_ORG_ID)["id"]
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
