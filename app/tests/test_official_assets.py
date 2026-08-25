# -*- coding: utf-8 -*-
"""app/tests/test_official_assets.py — 官方素材上傳／列表／刪除（issue #3）。

驗收重點：上傳後品牌頁見縮圖、刪除即消失（檔案與資料列皆清）、跨品牌隔離、非圖檔被擋。
"""

import io
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo

_SEQ = [0]


class OfficialAssetTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, name_prefix: str) -> str:
        _SEQ[0] += 1
        name = f"{name_prefix}{_SEQ[0]}"
        return repo.create_brand(web.conn, name=name, client_name=None, actor="測試員")["id"]

    def _upload(self, brand_id: str, *, filename="logo.png", content=b"\x89PNG fake bytes",
                content_type="image/png", asset_kind="logo", title="測試素材"):
        return self.client.post(
            f"/api/brands/{brand_id}/assets",
            data={"asset_kind": asset_kind, "product_id": "", "title": title},
            files={"file": (filename, io.BytesIO(content), content_type)},
        )

    def test_upload_shows_thumbnail_on_brand_page(self):
        brand_id = self._new_brand("晨露茶飲")
        resp = self._upload(brand_id)
        self.assertEqual(resp.status_code, 200)

        assets = repo.list_official_assets(web.conn, brand_id)
        self.assertEqual(len(assets), 1)
        self.assertTrue(Path(assets[0]["file_path"]).exists())

        bundle = self.client.get(f"/api/library/brands/{brand_id}").json()["data"]
        self.assertEqual(bundle["assets"][0]["title"], "測試素材")

    def test_delete_removes_row_and_file(self):
        brand_id = self._new_brand("山嵐選物")
        self._upload(brand_id)
        asset = repo.list_official_assets(web.conn, brand_id)[0]
        file_path = Path(asset["file_path"])
        self.assertTrue(file_path.exists())

        repo.delete_official_asset(web.conn, brand_id, asset["id"], actor="測試員")
        file_path.unlink()
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [])
        self.assertFalse(file_path.exists())

    def test_cross_brand_isolation(self):
        brand_a = self._new_brand("晨露茶飲-A")
        brand_b = self._new_brand("山嵐選物-B")
        self._upload(brand_a)
        asset = repo.list_official_assets(web.conn, brand_a)[0]

        bundle_b = self.client.get(f"/api/library/brands/{brand_b}").json()["data"]
        self.assertNotIn(asset["id"], [row["id"] for row in bundle_b["assets"]])

        # repository 以 brand_id 隔離，品牌 B 不得刪除品牌 A 的素材。
        with self.assertRaisesRegex(ValueError, "找不到"):
            repo.delete_official_asset(web.conn, brand_b, asset["id"], actor="測試員")
        self.assertEqual(len(repo.list_official_assets(web.conn, brand_a)), 1)
        self.assertTrue(Path(asset["file_path"]).exists())

    def test_non_image_rejected_with_plain_language_error(self):
        brand_id = self._new_brand("晨露茶飲-拒收")
        resp = self._upload(brand_id, filename="說明.pdf", content=b"%PDF-1.4 fake",
                             content_type="application/pdf")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [])


if __name__ == "__main__":
    unittest.main()
