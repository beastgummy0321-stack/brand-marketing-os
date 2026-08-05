# -*- coding: utf-8 -*-
"""app/tests/test_product_delete_routes.py — 產品封存／刪除的路由層（決策 0020）。

repository 層已驗過刪除本身乾不乾淨（見 test_product_delete.py），這裡守路由層特有的三道
保護：未封存被畫面與後端一起擋、名稱打錯不放行、刪除前會在 backups 資料夾留一份快照。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# 先備好暫存 DB 與 backups 目錄的環境變數，才能 import app.main。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_product_delete_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

_SEQ = [0]


class ProductDeleteRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand_and_product(self, prefix: str):
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        resp = self.client.post("/brands/new", data={"name": name, "client_name": ""},
                                 follow_redirects=False)
        brand_id = resp.headers["location"].split("/brands/")[1].split("?")[0]
        resp = self.client.post(f"/brands/{brand_id}/products/new", data={"name": f"{name}-產品"},
                                 follow_redirects=False)
        product_id = resp.headers["location"].split("/products/")[1].split("?")[0]
        return brand_id, product_id, f"{name}-產品"

    def test_delete_page_blocked_while_active(self):
        brand_id, product_id, _name = self._new_brand_and_product("未封存產品路由")
        resp = self.client.get(f"/brands/{brand_id}/products/{product_id}/delete",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/delete", resp.headers["location"])  # 轉回產品頁，不是刪除頁本身

        resp = self.client.post(f"/brands/{brand_id}/products/{product_id}/delete",
                                 data={"confirm_name": "亂打"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNotNone(repo.get_product(main.conn, brand_id, product_id))

    def test_wrong_name_does_not_delete(self):
        brand_id, product_id, name = self._new_brand_and_product("打錯名字產品")
        self.client.post(f"/brands/{brand_id}/products/{product_id}/archive",
                          follow_redirects=False)

        resp = self.client.post(f"/brands/{brand_id}/products/{product_id}/delete",
                                 data={"confirm_name": "打錯了"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("跟產品名稱不一樣", resp.text)
        self.assertIsNotNone(repo.get_product(main.conn, brand_id, product_id))

    def test_correct_name_deletes_and_snapshots_backup(self):
        brand_id, product_id, name = self._new_brand_and_product("成功刪除產品")
        self.client.post(f"/brands/{brand_id}/products/{product_id}/archive",
                          follow_redirects=False)

        backup_dir = Path(os.environ["BRAND_OS_BACKUP_DIR"])
        before_snapshots = list(backup_dir.glob(f"before-delete-{product_id}-*.db")) \
            if backup_dir.exists() else []
        self.assertEqual(before_snapshots, [])

        resp = self.client.post(f"/brands/{brand_id}/products/{product_id}/delete",
                                 data={"confirm_name": name}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(repo.get_product(main.conn, brand_id, product_id))

        after_snapshots = list(backup_dir.glob(f"before-delete-{product_id}-*.db"))
        self.assertEqual(len(after_snapshots), 1)

        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'product' AND action = 'delete' "
            "AND entity_id = ?", (product_id,)).fetchone()
        self.assertIsNotNone(row)

    def test_archive_then_restore_via_routes(self):
        brand_id, product_id, _name = self._new_brand_and_product("封存恢復路由產品")
        self.client.post(f"/brands/{brand_id}/products/{product_id}/archive",
                          follow_redirects=False)
        self.assertEqual(repo.get_product(main.conn, brand_id, product_id)["status"], "archived")

        self.client.post(f"/brands/{brand_id}/products/{product_id}/archive",
                          follow_redirects=False)
        self.assertEqual(repo.get_product(main.conn, brand_id, product_id)["status"], "active")


if __name__ == "__main__":
    unittest.main()
