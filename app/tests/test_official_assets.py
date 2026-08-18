# -*- coding: utf-8 -*-
"""app/tests/test_official_assets.py — 官方素材上傳／列表／刪除（issue #3）。

驗收重點：上傳後品牌頁見縮圖、刪除即消失（檔案與資料列皆清）、跨品牌隔離、非圖檔被擋。
"""

import atexit
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_assets_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

_SEQ = [0]


class OfficialAssetTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, name_prefix: str) -> str:
        _SEQ[0] += 1
        name = f"{name_prefix}{_SEQ[0]}"
        resp = self.client.post("/brands/new", data={"name": name, "client_name": ""},
                                 follow_redirects=False)
        assert resp.status_code == 303
        return resp.headers["location"].split("/brands/")[1].split("?")[0]

    def _upload(self, brand_id: str, *, filename="logo.png", content=b"\x89PNG fake bytes",
                content_type="image/png", asset_kind="logo", title="測試素材"):
        return self.client.post(
            f"/brands/{brand_id}/assets/new",
            data={"asset_kind": asset_kind, "product_id": "", "title": title},
            files={"file": (filename, io.BytesIO(content), content_type)},
            follow_redirects=False,
        )

    def test_upload_shows_thumbnail_on_brand_page(self):
        brand_id = self._new_brand("晨露茶飲")
        resp = self._upload(brand_id)
        self.assertEqual(resp.status_code, 303)

        assets = repo.list_official_assets(main.conn, brand_id)
        self.assertEqual(len(assets), 1)
        self.assertTrue(Path(assets[0]["file_path"]).exists())

        page = self.client.get(f"/brands/{brand_id}/hub/assets")
        self.assertIn(f"/brands/{brand_id}/assets/file/{assets[0]['id']}/", page.text)
        self.assertIn("測試素材", page.text)

    def test_delete_removes_row_and_file(self):
        brand_id = self._new_brand("山嵐選物")
        self._upload(brand_id)
        asset = repo.list_official_assets(main.conn, brand_id)[0]
        file_path = Path(asset["file_path"])
        self.assertTrue(file_path.exists())

        resp = self.client.post(f"/brands/{brand_id}/assets/{asset['id']}/delete",
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(repo.list_official_assets(main.conn, brand_id), [])
        self.assertFalse(file_path.exists())

    def test_cross_brand_isolation(self):
        brand_a = self._new_brand("晨露茶飲-A")
        brand_b = self._new_brand("山嵐選物-B")
        self._upload(brand_a)
        asset = repo.list_official_assets(main.conn, brand_a)[0]

        # 品牌 B 的素材子頁看不到品牌 A 的素材
        page_b = self.client.get(f"/brands/{brand_b}/hub/assets")
        self.assertNotIn(asset["id"], page_b.text)

        # 用品牌 B 的網址刪品牌 A 的素材 -> 404
        resp = self.client.post(f"/brands/{brand_b}/assets/{asset['id']}/delete")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(len(repo.list_official_assets(main.conn, brand_a)), 1)

        # 用品牌 B 的網址讀品牌 A 的檔案 -> 404
        filename = Path(asset["file_path"]).name
        resp = self.client.get(f"/brands/{brand_b}/assets/file/{asset['id']}/{filename}")
        self.assertEqual(resp.status_code, 404)

        # 品牌 A 自己讀得到
        resp = self.client.get(f"/brands/{brand_a}/assets/file/{asset['id']}/{filename}")
        self.assertEqual(resp.status_code, 200)

    def test_non_image_rejected_with_plain_language_error(self):
        brand_id = self._new_brand("晨露茶飲-拒收")
        resp = self._upload(brand_id, filename="說明.pdf", content=b"%PDF-1.4 fake",
                             content_type="application/pdf")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不是支援的圖片格式", resp.text)
        self.assertEqual(repo.list_official_assets(main.conn, brand_id), [])


if __name__ == "__main__":
    unittest.main()
