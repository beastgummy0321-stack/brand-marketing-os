# -*- coding: utf-8 -*-
"""app/tests/test_brand_delete_routes.py — 永久刪除品牌 JSON API（`routes_library.py`
`brand_delete_api()`）。

repository 層已驗過刪除本身乾不乾淨（見 test_brand_delete.py），這裡守路由層特有的
保護，比照決策 0020 產品先例（test_product_delete_routes.py）：未封存被擋、名稱打錯
不放行，外加品牌獨有的一步——素材圖檔資料夾（決策 0008）跟著一起刪。

（ADR 0027 決策 5：刪除前的 sqlite 檔案快照備份已隨整個 `app/core/backup.py`
模組退場——Supabase 自己做備份，這裡不再驗「backups/ 快照」這件事。）
"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.core import creative_assets
from app.core import settings as core_settings

ACTOR = "測試員"
_SEQ = [0]


class BrandDeleteRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._asset_tmpdir = tempfile.TemporaryDirectory(prefix="brand_os_brand_delete_assets_")
        core_settings.set_setting(web.conn, creative_assets.SETTING_KEY, self._asset_tmpdir.name)
        self.addCleanup(self._asset_tmpdir.cleanup)

    def _new_brand(self, prefix: str):
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        brand_id = repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR)["id"]
        return brand_id, name

    def test_delete_blocked_while_active(self):
        brand_id, _name = self._new_brand("未封存品牌路由")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": "亂打"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("先把品牌封存", resp.json()["error"])
        self.assertIsNotNone(repo.get_brand(web.conn, brand_id))

    def test_wrong_name_does_not_delete(self):
        brand_id, name = self._new_brand("打錯名字品牌")
        repo.update_brand(web.conn, brand_id, name=name, client_name=None,
                           status="archived", actor=ACTOR)

        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": "打錯了"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("跟品牌名稱不一樣", resp.json()["error"])
        self.assertIsNotNone(repo.get_brand(web.conn, brand_id))

    def test_correct_name_deletes_and_removes_asset_folder(self):
        brand_id, name = self._new_brand("成功刪除品牌")
        repo.update_brand(web.conn, brand_id, name=name, client_name=None,
                           status="archived", actor=ACTOR)

        asset_folder = Path(self._asset_tmpdir.name) / brand_id
        asset_folder.mkdir(parents=True)
        (asset_folder / "留著的圖.png").write_bytes(b"fake")
        self.assertTrue(asset_folder.is_dir())

        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": name},
        )
        self.assertEqual(resp.status_code, 200)
        message = resp.json()["message"]
        self.assertIn(name, message)
        self.assertIsNone(repo.get_brand(web.conn, brand_id))
        self.assertFalse(asset_folder.exists(), "素材圖檔資料夾應該跟著品牌一起刪掉")

        row = web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'brand' AND action = 'delete' "
            "AND entity_id = %s", (brand_id,)).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
