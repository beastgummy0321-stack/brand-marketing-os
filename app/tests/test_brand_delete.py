# -*- coding: utf-8 -*-
"""app/tests/test_brand_delete.py — 永久刪除品牌（決策 0015）。

刪除是不可逆動作，這裡守三件事：
1. 使用中的品牌刪不掉（一定要先封存）。
2. 刪掉之後，這個品牌在所有表都不留一列，audit_log 留得下 before 全文與各表筆數。
3. 別的品牌一列都不能少（刪除照樣受品牌隔離約束）。
"""

import unittest

from app.brand_intelligence import repository as repo
from app.core import db
from app.intake import repository as intake_repo

ALL_TABLES = [t for t, _ in repo.BRAND_CHILD_TABLES] + ["intake_item", "intake_draft"]


class BrandDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed_brand(self, name):
        """一個品牌，每張表都塞一列，才驗得出「刪乾淨」。"""
        bid = repo.create_brand(self.conn, name=name, client_name="測試客戶", actor="測試員")["id"]
        pid = repo.create_product(self.conn, bid, name=f"{name}-產品", actor="測試員")["id"]
        repo.create_brand_fact(self.conn, bid, fact_type="positioning", label="定位",
                                value="測試內容", status="pending", actor="測試員")
        repo.create_product_fact(self.conn, bid, pid, fact_type="core_info", label="規格",
                                  value="測試", status="pending", actor="測試員")
        repo.create_rule(self.conn, bid, rule_type="tone", content="測試規則",
                          severity="soft", actor="測試員")
        repo.create_claim(self.conn, bid, claim_text="測試宣稱", claim_type="approved",
                           actor="測試員")
        repo.create_channel(self.conn, bid, channel_type="website", name="測試官網",
                             actor="測試員")
        repo.save_product_economics(self.conn, bid, pid, selling_price=100, currency="TWD",
                                     confirmed_by="測試員", actor="測試員")
        repo.create_source_reference(self.conn, bid, title="測試來源", source_type="web",
                                      captured_date="2026-01-01", actor="測試員")
        repo.create_official_asset(self.conn, bid, asset_kind="logo",
                                    file_path="C:/tmp/logo.png", actor="測試員")
        repo.create_strategy_hypothesis(self.conn, bid, hypothesis_type="audience",
                                         statement="測試假設", created_by="測試員", actor="測試員")
        repo.create_brand_performance_baseline(self.conn, bid, metric="典型CTR", value=1.2,
                                                as_of_date="2026-01-01", created_by="測試員",
                                                actor="測試員")
        repo.create_customer_voice(self.conn, bid, actor="測試員", raw_text="測試顧客原話",
                                    source_channel="ptt", source_type="manual", extraction=[])
        # brand_report 在 DB 層有外鍵指向 brand：沒被清就不是「刪不乾淨」而是「整個刪除失敗」
        repo.create_brand_report(self.conn, bid, actor="測試員", model="test-model",
                                  llm_task_id=None, brand_version=1, source_fact_count=1,
                                  sections={"定位": "測試段落"})
        repo.create_learning_ledger_entry(self.conn, bid, learning_text="測試學習",
                                           applicability_scope="brand", created_by="測試員",
                                           actor="測試員", source_track="ads", product_id=pid)
        draft = intake_repo.create_draft(self.conn, bid, "測試品牌描述", [], [], actor="測試員")
        intake_repo.create_items(self.conn, bid, draft["id"], [{
            "kind": "品牌事實", "category": "品牌定位", "title": "測試標題",
            "content": "測試內容", "scope": "整個品牌", "evidence": "測試來源",
        }])
        return bid

    def _row_counts(self, brand_id):
        return {t: self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {t} WHERE brand_id = %s", (brand_id,)).fetchone()["n"]
            for t in ALL_TABLES}

    def _delete(self, brand_id):
        """只叫 delete_brand()——intake 的資料由清理登記處負責清，這裡不補刀。

        故意不再手動呼叫 intake_repo.delete_brand_data()：留著那行的話，就算登記處
        壞掉沒清到 intake，這個測試照樣會綠。現在 intake_draft / intake_item 歸零
        是登記處真的有做事的證明。
        """
        return repo.delete_brand(self.conn, brand_id, actor="測試員")

    def test_active_brand_cannot_be_deleted(self):
        bid = self._seed_brand("未封存品牌（刪除測試）")
        with self.assertRaises(ValueError):
            repo.delete_brand(self.conn, bid, actor="測試員")
        self.assertIsNotNone(repo.get_brand(self.conn, bid))

    def test_archived_brand_is_wiped_from_every_table(self):
        bid = self._seed_brand("待刪品牌（刪除測試）")
        self.assertTrue(all(n > 0 for n in self._row_counts(bid).values()))

        repo.update_brand(self.conn, bid, name="待刪品牌（刪除測試）", client_name="測試客戶",
                           status="archived", actor="測試員")
        self._delete(bid)

        self.assertIsNone(repo.get_brand(self.conn, bid))
        self.assertEqual(set(self._row_counts(bid).values()), {0})

    def test_delete_leaves_audit_trail(self):
        bid = self._seed_brand("留痕品牌（刪除測試）")
        repo.update_brand(self.conn, bid, name="留痕品牌（刪除測試）", client_name="測試客戶",
                           status="archived", actor="測試員")
        self._delete(bid)

        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'brand' AND action = 'delete' "
            "AND entity_id = %s", (bid,)).fetchone()
        self.assertIsNotNone(row)
        before = row["before_json"]  # jsonb 欄位，psycopg 已自動解碼成 dict，不必 json.loads
        self.assertEqual(before["name"], "留痕品牌（刪除測試）")
        self.assertEqual(before["deleted_counts"]["產品"], 1)
        self.assertEqual(row["actor"], "測試員")

    def test_other_brands_untouched(self):
        gone = self._seed_brand("要刪的品牌（隔離測試）")
        kept = self._seed_brand("留著的品牌（隔離測試）")
        before = self._row_counts(kept)

        repo.update_brand(self.conn, gone, name="要刪的品牌（隔離測試）", client_name="測試客戶",
                           status="archived", actor="測試員")
        self._delete(gone)

        self.assertEqual(self._row_counts(kept), before)
        self.assertIsNotNone(repo.get_brand(self.conn, kept))


if __name__ == "__main__":
    unittest.main()
