# -*- coding: utf-8 -*-
"""app/tests/test_audit.py — audit_log 只增不改，每次異動留一筆稽核紀錄。

見 docs/design/03-data-model.md §3.1、§8.5。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.brand_intelligence import repository as repo
from app.core import audit as audit_mod
from app.core import db


class AuditLogTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    def test_append_only_no_mutation_functions_exposed(self):
        """audit.py 存取層強制：只允許 INSERT，不提供 update/delete 函式（03 §8.5）。"""
        exported = [name for name in dir(audit_mod) if not name.startswith("_")]
        self.assertIn("write_audit", exported)
        for name in exported:
            lowered = name.lower()
            self.assertNotIn("update", lowered)
            self.assertNotIn("delete", lowered)

    def test_every_mutation_writes_one_audit_row(self):
        brand = repo.create_brand(self.conn, name="品牌A（稽核測試）", client_name=None, actor="小陳")
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["action"], "create")
        self.assertEqual(first["entity_type"], "brand")
        self.assertEqual(first["entity_id"], brand["id"])
        self.assertEqual(first["actor"], "小陳")
        self.assertIsNone(first["before_json"])
        self.assertEqual(json.loads(first["after_json"])["name"], "品牌A（稽核測試）")

        repo.update_brand(self.conn, brand["id"], name="品牌A（改名）", client_name=None,
                           status="active", actor="小陳")
        rows = self._audit_rows()
        self.assertEqual(len(rows), 2)
        second = rows[1]
        self.assertEqual(second["action"], "update")
        self.assertEqual(json.loads(second["before_json"])["name"], "品牌A（稽核測試）")
        self.assertEqual(json.loads(second["after_json"])["name"], "品牌A（改名）")

        # 先前寫入的那筆稽核紀錄本身不會被後續操作動到（append-only）
        self.assertEqual(rows[0]["id"], first["id"])
        self.assertEqual(json.loads(rows[0]["after_json"])["name"], "品牌A（稽核測試）")

        product = repo.create_product(self.conn, brand["id"], name="產品A-1", actor="小陳")
        fact = repo.create_brand_fact(
            self.conn, brand["id"], fact_type="positioning", label="定位", value="內容",
            status="pending", actor="小陳",
        )
        repo.confirm_brand_fact(self.conn, brand["id"], fact["id"], confirmed_by="小陳", actor="小陳")
        rows = self._audit_rows()
        # brand create/update, product create, fact create, fact confirm = 5 筆
        self.assertEqual(len(rows), 5)
        self.assertEqual([r["action"] for r in rows], ["create", "update", "create", "create", "confirm"])
        self.assertEqual(rows[3]["entity_type"], "brand_fact")
        self.assertEqual(rows[4]["entity_type"], "brand_fact")
        self.assertEqual(rows[4]["actor"], "小陳")
        self.assertEqual(json.loads(rows[4]["after_json"])["confirmed_by"], "小陳")

    def test_actor_required_to_write_audit(self):
        with self.assertRaises(ValueError):
            repo.create_brand(self.conn, name="品牌B（無操作人）", client_name=None, actor="")
        with self.assertRaises(ValueError):
            repo.create_brand(self.conn, name="品牌C（無操作人）", client_name=None, actor="   ")
        # 失敗的呼叫不該留下任何稽核紀錄或資料列
        self.assertEqual(len(self._audit_rows()), 0)
        self.assertEqual(len(repo.list_brands(self.conn)), 0)


if __name__ == "__main__":
    unittest.main()
