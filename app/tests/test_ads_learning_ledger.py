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

    def test_source_track_filters_and_defaults_to_ads(self):
        row_visual = repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                           learning_text="視覺學習：手機原生抓拍",
                                           applicability_scope="brand",
                                           confidence="observed", sample_size="1",
                                           source_track="visual")
        row_ads = repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                        learning_text="投放學習：早鳥受眾轉換較高",
                                        applicability_scope="brand",
                                        confidence="observed", sample_size="1")
        self.assertEqual(row_ads["source_track"], "ads")

        visual_rows = repo.list_learnings(self.conn, self.bid_a, source_track="visual")
        ads_rows = repo.list_learnings(self.conn, self.bid_a, source_track="ads")
        all_rows = repo.list_learnings(self.conn, self.bid_a, source_track=None)

        self.assertEqual([r["id"] for r in visual_rows], [row_visual["id"]])
        self.assertEqual([r["id"] for r in ads_rows], [row_ads["id"]])
        self.assertEqual({r["id"] for r in all_rows}, {row_visual["id"], row_ads["id"]})

    def test_expire_learning_hides_row_and_is_idempotent(self):
        row = repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                    learning_text="要被降級的學習", applicability_scope="brand",
                                    confidence="likely", sample_size="1")

        expired = repo.expire_learning(self.conn, self.bid_a, row["id"], actor="測試員")
        self.assertTrue(expired["expired"])
        self.assertEqual(repo.list_learnings(self.conn, self.bid_a), [])
        visible = repo.list_learnings(self.conn, self.bid_a, include_expired=True)
        self.assertEqual(len(visible), 1)
        self.assertTrue(visible[0]["expired"])

        # F07-I13 item 1: expire_learning must write exactly one audit row for this entity
        # (app/brand_intelligence/repository.py:986-987's write_audit call).
        audit_rows = [
            dict(r) for r in self.conn.execute(
                "SELECT * FROM audit_log WHERE entity_type = 'learning_ledger'"
                " AND entity_id = %s", (row["id"],),
            ).fetchall()
        ]
        update_rows = [r for r in audit_rows if r["action"] == "update"]
        self.assertEqual(len(update_rows), 1)
        audit_row = update_rows[0]
        self.assertEqual(audit_row["actor"], "測試員")
        self.assertFalse(audit_row["before_json"]["expired"])
        self.assertTrue(audit_row["after_json"]["expired"])

        # F07-I13 item 2: expire_learning must commit (repository.py:988) so a second pooled
        # connection sees the change immediately, not just this test's own connection.
        with db.pool().connection() as other:
            other_row = other.execute(
                "SELECT expired FROM learning_ledger WHERE id = %s", (row["id"],),
            ).fetchone()
            self.assertTrue(other_row["expired"])

        again = repo.expire_learning(self.conn, self.bid_a, row["id"], actor="測試員")
        self.assertTrue(again["expired"])

    def test_expire_learning_wrong_brand_returns_none_and_changes_nothing(self):
        row = repo.record_learning(self.conn, self.bid_a, actor="測試員",
                                    learning_text="不該被別品牌降級", applicability_scope="brand",
                                    confidence="likely", sample_size="1")

        result = repo.expire_learning(self.conn, self.bid_b, row["id"], actor="測試員")
        self.assertIsNone(result)
        rows = repo.list_learnings(self.conn, self.bid_a)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["expired"])
        no_update = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE entity_type = 'learning_ledger'"
            " AND entity_id = %s AND action = 'update'", (row["id"],),
        ).fetchone()
        self.assertEqual(no_update["n"], 0)

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
