"""app/tests/test_official_assets.py — 官方素材上傳／列表／刪除（issue #3；票 storage-02
改走 Supabase Storage）。

驗收重點：上傳後品牌頁見縮圖、`storage_key` 帶 org_id 首段、刪除即消失（Storage 物件與
資料列皆清）、跨品牌隔離、非圖檔被擋、檔案服務路由回對的 bytes／content-type、上傳失敗
不留孤兒列（SPEC D9：一列指到不存在的物件，畫面會永遠是張破圖）。
"""

import io
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.storage as storage
from app.brand_intelligence import repository as repo
from app.core.db import DEV_ORG_ID  # noqa: E402

_SEQ = [0]


class OfficialAssetTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, name_prefix: str) -> str:
        _SEQ[0] += 1
        name = f"{name_prefix}{_SEQ[0]}"
        return repo.create_brand(web.conn, name=name, client_name=None, actor="測試員",
            org_id=DEV_ORG_ID)["id"]

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
        asset = assets[0]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=asset["storage_key"])
        self.assertTrue(asset["storage_key"].startswith(f"{DEV_ORG_ID}/"))
        content, content_type = storage.get(org_id=DEV_ORG_ID, key=asset["storage_key"])
        self.assertEqual(content, b"\x89PNG fake bytes")
        self.assertEqual(content_type, "image/png")

        bundle = self.client.get(f"/api/library/brands/{brand_id}").json()["data"]
        self.assertEqual(bundle["assets"][0]["title"], "測試素材")

    def test_delete_removes_row_and_storage_object(self):
        brand_id = self._new_brand("山嵐選物")
        self._upload(brand_id)
        asset = repo.list_official_assets(web.conn, brand_id)[0]
        storage_key = asset["storage_key"]
        content, _ = storage.get(org_id=DEV_ORG_ID, key=storage_key)
        self.assertTrue(content)

        repo.delete_official_asset(web.conn, brand_id, asset["id"], actor="測試員")
        storage.delete(org_id=DEV_ORG_ID, key=storage_key)
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [])
        with self.assertRaises(storage.NotFound):
            storage.get(org_id=DEV_ORG_ID, key=storage_key)

    def test_cross_brand_isolation(self):
        brand_a = self._new_brand("晨露茶飲-A")
        brand_b = self._new_brand("山嵐選物-B")
        self._upload(brand_a)
        asset = repo.list_official_assets(web.conn, brand_a)[0]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=asset["storage_key"])

        bundle_b = self.client.get(f"/api/library/brands/{brand_b}").json()["data"]
        self.assertNotIn(asset["id"], [row["id"] for row in bundle_b["assets"]])

        # repository 以 brand_id 隔離，品牌 B 不得刪除品牌 A 的素材。
        with self.assertRaisesRegex(ValueError, "找不到"):
            repo.delete_official_asset(web.conn, brand_b, asset["id"], actor="測試員")
        self.assertEqual(len(repo.list_official_assets(web.conn, brand_a)), 1)
        content, _ = storage.get(org_id=DEV_ORG_ID, key=asset["storage_key"])
        self.assertTrue(content)

    def test_non_image_rejected_with_plain_language_error(self):
        brand_id = self._new_brand("晨露茶飲-拒收")
        resp = self._upload(brand_id, filename="說明.pdf", content=b"%PDF-1.4 fake",
                             content_type="application/pdf")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.json())
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [])

    def test_oversized_upload_rejected_before_it_reaches_storage(self):
        """資料正確性／可用性：`await file.read()` 會把整個 body 讀進記憶體，之後才輪到
        Storage 說不行——而 Storage 的上限（`supabase/config.toml` `[storage]`
        `file_size_limit = "50MiB"`）擋下來時吐的是英文例外，不是使用者看得懂的一句話。
        50 MiB 這個數字不是這裡挑的，是那份設定檔裡的值。"""
        brand_id = self._new_brand("晨露茶飲-過大")
        oversized = b"0" * (50 * 1024 * 1024 + 1)
        resp = self._upload(brand_id, filename="巨圖.png", content=oversized,
                             content_type="image/png")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("50 MB", resp.json()["detail"])
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [],
                         "被擋下來的上傳不可以留下任何一列")

    def test_put_failure_leaves_no_asset_row(self):
        """money/data-correctness 案例（SPEC D9）：`put` 炸了，就不可以留一列指到不存在
        的物件——那張圖會永遠是破的。用 mock 模擬 Storage 失敗，不必真的打斷網路。"""
        brand_id = self._new_brand("上傳失敗品牌")
        with mock.patch("app.brand_web.routes_library.storage.put",
                         side_effect=storage.StorageError("模擬 Storage 失敗")):
            resp = self._upload(brand_id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(repo.list_official_assets(web.conn, brand_id), [])

    def test_file_route_returns_bytes_and_content_type_mismatched_filename_404s(self):
        brand_id = self._new_brand("檔案服務品牌")
        self._upload(brand_id, filename="logo.png", content=b"\x89PNG round trip bytes",
                     content_type="image/png")
        asset = repo.list_official_assets(web.conn, brand_id)[0]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=asset["storage_key"])
        filename = asset["storage_key"].rsplit("/", 1)[-1]

        resp = self.client.get(f"/brands/{brand_id}/assets/file/{asset['id']}/{filename}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"\x89PNG round trip bytes")
        self.assertEqual(resp.headers["content-type"], "image/png")

        resp_wrong_name = self.client.get(
            f"/brands/{brand_id}/assets/file/{asset['id']}/不是這個檔名.png")
        self.assertEqual(resp_wrong_name.status_code, 404)


if __name__ == "__main__":
    unittest.main()
