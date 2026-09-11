"""app/tests/test_workbench_product_delete.py — 產品／品牌刪除撞上素材工作檯的簡報（F01-T05-I01）。

`workbench_brief.product_id` 曾是一般外鍵（預設 RESTRICT）：品牌智庫刪產品或整個品牌時，
簡報還連著這個 product_id，刪除會噴外鍵違規。修法是把外鍵改成 ON DELETE SET NULL——
這裡守兩條刪除路徑各自會走到的結果。
"""

import unittest

from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.workbench import repository as wb_repo  # noqa: F401 — import registers cleanup.register()


class WorkbenchProductDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed_brief(self, brand_id, product_id):
        brief_id = db.new_id("wbb")
        self.conn.execute(
            "INSERT INTO workbench_brief (id, org_id, brand_id, kind, source_kind, product_id)"
            " VALUES (%s, %s, %s, 'copy', 'manual', %s)",
            (brief_id, db.DEV_ORG_ID, brand_id, product_id),
        )
        self.conn.commit()
        return brief_id

    def test_brand_with_product_linked_brief_deletes(self):
        bid = bi_repo.create_brand(self.conn, name="測試品牌（工作檯刪除）",
                                    client_name="測試客戶", actor="測試員",
                                    org_id=db.DEV_ORG_ID)["id"]
        pid = bi_repo.create_product(self.conn, bid, name="測試產品", actor="測試員")["id"]
        self._seed_brief(bid, pid)

        bi_repo.update_brand(self.conn, bid, name="測試品牌（工作檯刪除）",
                              client_name="測試客戶", status="archived", actor="測試員")
        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        self.assertIsNone(bi_repo.get_brand(self.conn, bid))
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM workbench_brief WHERE brand_id = %s", (bid,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)

    def test_product_delete_keeps_brief_unlinked(self):
        bid = bi_repo.create_brand(self.conn, name="測試品牌（工作檯刪除2）",
                                    client_name="測試客戶", actor="測試員",
                                    org_id=db.DEV_ORG_ID)["id"]
        pid = bi_repo.create_product(self.conn, bid, name="測試產品2", actor="測試員")["id"]
        brief_id = self._seed_brief(bid, pid)

        bi_repo.update_product(self.conn, bid, pid, name="測試產品2",
                                status="archived", actor="測試員")
        bi_repo.delete_product(self.conn, bid, pid, actor="測試員")

        row = self.conn.execute(
            "SELECT product_id FROM workbench_brief WHERE id = %s", (brief_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["product_id"])


if __name__ == "__main__":
    unittest.main()
