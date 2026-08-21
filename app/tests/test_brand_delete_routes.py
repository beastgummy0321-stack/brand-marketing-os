# -*- coding: utf-8 -*-
"""app/tests/test_brand_delete_routes.py — 永久刪除品牌 JSON API（`routes_library.py`
`brand_delete_api()`）。

repository 層已驗過刪除本身乾不乾淨（見 test_brand_delete.py），這裡守路由層特有的
保護，比照決策 0020 產品先例（test_product_delete_routes.py）：未封存被擋、名稱打錯
不放行、刪除前會在 backups 資料夾留一份快照，外加品牌獨有的一步——素材圖檔資料夾
（決策 0008）跟著一起刪。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# 先備好暫存 DB 與 backups 目錄的環境變數，才能 import app.main。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_brand_delete_routes_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import settings as core_settings  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

_SEQ = [0]
ACTOR = "測試員"


class BrandDeleteRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._asset_tmpdir = tempfile.TemporaryDirectory(prefix="brand_os_brand_delete_assets_")
        core_settings.set_setting(main.conn, creative_assets.SETTING_KEY, self._asset_tmpdir.name)
        self.addCleanup(self._asset_tmpdir.cleanup)

    def _new_brand(self, prefix: str):
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        brand_id = repo.create_brand(main.conn, name=name, client_name=None, actor=ACTOR)["id"]
        return brand_id, name

    def test_delete_blocked_while_active(self):
        brand_id, _name = self._new_brand("未封存品牌路由")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": "亂打"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("先把品牌封存", resp.json()["error"])
        self.assertIsNotNone(repo.get_brand(main.conn, brand_id))

    def test_wrong_name_does_not_delete(self):
        brand_id, name = self._new_brand("打錯名字品牌")
        repo.update_brand(main.conn, brand_id, name=name, client_name=None,
                           status="archived", actor=ACTOR)

        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": "打錯了"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("跟品牌名稱不一樣", resp.json()["error"])
        self.assertIsNotNone(repo.get_brand(main.conn, brand_id))

    def test_correct_name_deletes_snapshots_backup_and_removes_asset_folder(self):
        brand_id, name = self._new_brand("成功刪除品牌")
        repo.update_brand(main.conn, brand_id, name=name, client_name=None,
                           status="archived", actor=ACTOR)

        asset_folder = Path(self._asset_tmpdir.name) / brand_id
        asset_folder.mkdir(parents=True)
        (asset_folder / "留著的圖.png").write_bytes(b"fake")
        self.assertTrue(asset_folder.is_dir())

        backup_dir = Path(os.environ["BRAND_OS_BACKUP_DIR"])
        before_snapshots = list(backup_dir.glob(f"before-delete-{brand_id}-*.db")) \
            if backup_dir.exists() else []
        self.assertEqual(before_snapshots, [])

        resp = self.client.post(
            f"/api/library/brands/{brand_id}/delete", json={"confirm_name": name},
        )
        self.assertEqual(resp.status_code, 200)
        message = resp.json()["message"]
        self.assertIn(name, message)
        self.assertIn("backups/", message)
        self.assertIsNone(repo.get_brand(main.conn, brand_id))
        self.assertFalse(asset_folder.exists(), "素材圖檔資料夾應該跟著品牌一起刪掉")

        after_snapshots = list(backup_dir.glob(f"before-delete-{brand_id}-*.db"))
        self.assertEqual(len(after_snapshots), 1)

        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'brand' AND action = 'delete' "
            "AND entity_id = ?", (brand_id,)).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
