"""app/tests/test_ads_learning_ledger.py — learning_ledger 讀寫端（F03-I02）。

守四件事：寫入的學習只回自己品牌的 list_learnings；confidence／learning_text 兩個必填
守門；expired 預設藏起來；刪品牌照樣清得掉（既有 test_brand_delete.py 已驗過清理路徑，
這裡不重複）。
"""

import unittest

from app.brand_intelligence import repository as repo
from app.core import db


class LearningLedgerTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.bid_a = repo.create_brand(self.conn, name="學習品牌A", client_name="測試客戶",
                                        actor="測試員", org_id=db.DEV_ORG_ID)["id"]
        self.bid_b = repo.create_brand(self.conn, name="學習品牌B", client_name="測試客戶",
                                        actor="測試員", org_id=db.DEV_ORG_ID)["id"]

    def test_written_row_returns_for_own_brand_only(self):
        repo.record_learning(self.conn, self.bid_a, actor="測試員",
                              learning_text="早鳥受眾轉換較高", applicability_scope="brand",
                              confidence="observed", sample_size="1")
        rows_a = repo.list_learnings(self.conn, self.bid_a)
        rows_b = repo.list_learnings(self.conn, self.bid_b)
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0]["learning_text"], "早鳥受眾轉換較高")
        self.assertEqual(rows_b, [])

    def test_unknown_confidence_raises(self):
        with self.assertRaises(ValueError):
            repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                  learning_text="測試學習", applicability_scope="brand",
                                  confidence="超級確定", sample_size="1")

    def test_empty_learning_text_raises(self):
        with self.assertRaises(ValueError):
            repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                  learning_text="   ", applicability_scope="brand",
                                  confidence="observed", sample_size="1")

    def test_expired_hidden_by_default_and_visible_when_asked(self):
        row = repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                    learning_text="已過期的學習", applicability_scope="brand",
                                    confidence="observed", sample_size="1")
        self.conn.execute("UPDATE learning_ledger SET expired = true WHERE id = %s", (row["id"],))
        self.conn.commit()
        self.assertEqual(repo.list_learnings(self.conn, self.bid_a), [])
        visible = repo.list_learnings(self.conn, self.bid_a, include_expired=True)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["id"], row["id"])

    def test_deleting_brand_removes_learning_rows(self):
        repo.record_learning(self.conn, self.bid_a, actor="測試員",
                              learning_text="要被刪掉的學習", applicability_scope="brand",
                              confidence="observed", sample_size="1")
        repo.update_brand(self.conn, self.bid_a, name="學習品牌A", client_name="測試客戶",
                           actor="測試員", status="archived")
        repo.delete_brand(self.conn, self.bid_a, actor="測試員")
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM learning_ledger WHERE brand_id = %s", (self.bid_a,),
        ).fetchone()
        self.assertEqual(row["n"], 0)


if __name__ == "__main__":
    unittest.main()
