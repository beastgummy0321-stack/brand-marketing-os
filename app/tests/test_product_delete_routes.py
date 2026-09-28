"""app/tests/test_product_delete_routes.py — 產品封存／刪除的路由層（決策 0020）。

repository 層已驗過刪除本身乾不乾淨（見 test_product_delete.py），這裡守路由層特有的兩道
保護：未封存被畫面與後端一起擋、名稱打錯不放行。

（ADR 0027 決策 5：刪除前的 sqlite 檔案快照備份已隨整個 `app/core/backup.py`
模組退場——Supabase 自己做備份，這裡不再驗「backups/ 快照」這件事。）
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.core.db import DEV_ORG_ID  # noqa: E402

_SEQ = [0]
ACTOR = "測試者"


class ProductDeleteRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand_and_product(self, prefix: str):
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        brand_id = repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR,
            org_id=DEV_ORG_ID)["id"]
        product_id = repo.create_product(
            web.conn, brand_id, name=f"{name}-產品", actor=ACTOR
        )["id"]
        return brand_id, product_id, f"{name}-產品"

    def test_delete_page_blocked_while_active(self):
        brand_id, product_id, _name = self._new_brand_and_product("未封存產品路由")
        resp = self.client.post(
            f"/api/products/brands/{brand_id}/products/{product_id}/delete",
            json={"confirm_name": "亂打"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("先把產品封存", resp.json()["error"])
        self.assertIsNotNone(repo.get_product(web.conn, brand_id, product_id))

    def test_wrong_name_does_not_delete(self):
        brand_id, product_id, name = self._new_brand_and_product("打錯名字產品")
        self.client.post(f"/api/products/brands/{brand_id}/products/{product_id}/archive")

        resp = self.client.post(
            f"/api/products/brands/{brand_id}/products/{product_id}/delete",
            json={"confirm_name": "打錯了"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("跟產品名稱不一樣", resp.json()["error"])
        self.assertIsNotNone(repo.get_product(web.conn, brand_id, product_id))

    def test_correct_name_deletes(self):
        brand_id, product_id, name = self._new_brand_and_product("成功刪除產品")
        self.client.post(f"/api/products/brands/{brand_id}/products/{product_id}/archive")

        resp = self.client.post(
            f"/api/products/brands/{brand_id}/products/{product_id}/delete",
            json={"confirm_name": name},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(repo.get_product(web.conn, brand_id, product_id))

        row = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'product' AND action = 'delete' "
            "AND entity_id = %s", (product_id,)).fetchone()
        self.assertIsNotNone(row)

    def test_archive_then_restore_via_routes(self):
        brand_id, product_id, _name = self._new_brand_and_product("封存恢復路由產品")
        self.client.post(f"/api/products/brands/{brand_id}/products/{product_id}/archive")
        self.assertEqual(repo.get_product(web.conn, brand_id, product_id)["status"], "archived")

        self.client.post(f"/api/products/brands/{brand_id}/products/{product_id}/archive")
        self.assertEqual(repo.get_product(web.conn, brand_id, product_id)["status"], "active")

    def test_restore_refused_with_409_while_active_same_name_exists(self):
        """F36-I10 (drill-6 #16): archive A, add a new active A (allowed), then restoring the
        old one via the route is a 409 「已有同名產品」 and the old row stays archived."""
        brand_id, old_id, name = self._new_brand_and_product("同名恢復路由產品")
        resp = self.client.post(f"/api/products/brands/{brand_id}/products/{old_id}/archive")
        self.assertEqual(resp.status_code, 204)
        new_id = repo.create_product(web.conn, brand_id, name=name, actor=ACTOR)["id"]
        self.assertNotEqual(new_id, old_id)

        resp = self.client.post(f"/api/products/brands/{brand_id}/products/{old_id}/archive")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("已有同名產品", resp.json()["error"])
        self.assertEqual(repo.get_product(web.conn, brand_id, old_id)["status"], "archived")
        self.assertEqual(repo.get_product(web.conn, brand_id, new_id)["status"], "active")


if __name__ == "__main__":
    unittest.main()
