# -*- coding: utf-8 -*-
"""app/tests/test_versioning.py — 版本遞增、確認流、編輯退回待確認。

見 docs/design/03-data-model.md §2、DESIGN.md §17 決策 3。
"""

import tempfile
import unittest
from pathlib import Path

from app.brand_intelligence import repository as repo
from app.core import db


class VersioningTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = repo.create_brand(self.conn, name="品牌A（版本測試）", client_name=None, actor="小陳")
        self.product = repo.create_product(self.conn, self.brand["id"], name="產品A-1", actor="小陳")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _brand_version(self):
        return repo.get_brand(self.conn, self.brand["id"])["knowledge_version"]

    def _product_version(self):
        return repo.get_product(self.conn, self.brand["id"], self.product["id"])["knowledge_version"]

    def test_brand_fact_lifecycle_versions_and_confirm_flow(self):
        self.assertEqual(self._brand_version(), 1)

        fact = repo.create_brand_fact(
            self.conn, self.brand["id"], fact_type="positioning", label="定位", value="內容",
            status="pending", actor="小陳",
        )
        self.assertEqual(self._brand_version(), 2)
        self.assertEqual(fact["status"], "pending")
        self.assertIsNone(fact["confirmed_by"])

        confirmed = repo.confirm_brand_fact(
            self.conn, self.brand["id"], fact["id"], confirmed_by="小陳", actor="小陳",
        )
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["confirmed_by"], "小陳")
        self.assertIsNotNone(confirmed["confirmed_at"])
        self.assertEqual(self._brand_version(), 3)

        # 決策 0013：已確認的事實被人工編輯 → 直接生效、維持已確認，編輯者成為最新確認人
        edited = repo.update_brand_fact(
            self.conn, self.brand["id"], fact["id"], fact_type="positioning",
            label="定位（修改）", value="改過的內容", actor="小陳",
        )
        self.assertEqual(edited["status"], "confirmed")
        self.assertEqual(edited["confirmed_by"], "小陳")
        self.assertIsNotNone(edited["confirmed_at"])
        self.assertEqual(edited["label"], "定位（修改）")
        self.assertEqual(self._brand_version(), 4)

        # 再次編輯 → 仍維持已確認（人工編輯永遠直接生效）
        edited_again = repo.update_brand_fact(
            self.conn, self.brand["id"], fact["id"], fact_type="positioning",
            label="定位（再修改）", value="再改過的內容", actor="小陳",
        )
        self.assertEqual(edited_again["status"], "confirmed")
        self.assertEqual(self._brand_version(), 5)

    def test_product_fact_bumps_product_version_only(self):
        brand_version_before = self._brand_version()
        self.assertEqual(self._product_version(), 1)

        fact = repo.create_product_fact(
            self.conn, self.brand["id"], self.product["id"], fact_type="core_info", label="規格",
            value="內容", status="pending", actor="小陳",
        )
        self.assertEqual(self._product_version(), 2)
        self.assertEqual(self._brand_version(), brand_version_before)

        repo.confirm_product_fact(
            self.conn, self.brand["id"], self.product["id"], fact["id"],
            confirmed_by="小陳", actor="小陳",
        )
        self.assertEqual(self._product_version(), 3)
        self.assertEqual(self._brand_version(), brand_version_before)

        edited = repo.update_product_fact(
            self.conn, self.brand["id"], self.product["id"], fact["id"], fact_type="core_info",
            label="規格（修改）", value="改過的內容", actor="小陳",
        )
        self.assertEqual(edited["status"], "confirmed")
        self.assertEqual(self._product_version(), 4)
        self.assertEqual(self._brand_version(), brand_version_before)

    def test_rule_and_claim_bump_scope_by_product_id(self):
        repo.create_rule(self.conn, self.brand["id"], rule_type="tone", content="品牌規則",
                          severity="soft", actor="小陳")
        self.assertEqual(self._brand_version(), 2)
        self.assertEqual(self._product_version(), 1)

        repo.create_rule(self.conn, self.brand["id"], product_id=self.product["id"], rule_type="visual",
                          content="產品規則", severity="hard", actor="小陳")
        self.assertEqual(self._brand_version(), 2)
        self.assertEqual(self._product_version(), 2)

        repo.create_claim(self.conn, self.brand["id"], claim_text="品牌宣稱", claim_type="approved",
                           actor="小陳")
        self.assertEqual(self._brand_version(), 3)
        self.assertEqual(self._product_version(), 2)

        repo.create_claim(self.conn, self.brand["id"], product_id=self.product["id"],
                           claim_text="產品宣稱", claim_type="high_risk", actor="小陳")
        self.assertEqual(self._brand_version(), 3)
        self.assertEqual(self._product_version(), 3)


if __name__ == "__main__":
    unittest.main()
