"""app/tests/test_intake_api.py — 品牌建檔 JSON API：建品牌、重新建檔、照片上傳、草稿整包。

見 app/intake/routes_api.py。F42-I14 拆掉舊階段（初掃印象、AI 問答、花費側欄、交接包）的路由
與它們的測試；預填掃描在 test_intake_prefill.py。不發任何真實網路請求；品牌名一律虛構。
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-api-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app import storage  # noqa: E402
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.intake import ai as intake_ai  # noqa: E402
from app.intake import state  # noqa: E402

_SEQ = [0]


# A JPEG frame header (1x1): photo uploads are checked by content and header (F47 Contract A).
_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffc0000b080001000101011100ffd9")
# A 1x1 PNG with a valid IHDR: uploads are checked by content and header (F47 Contract A).
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x00\x00\x00\x00:~\x9bU\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
       b"H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)  # 這個模組自己有一份 schema，要重新掛一次背景 task
        # 隔離環境變數：金鑰只看 DB 設定（沒設＝沒金鑰，跟 test_intake.py 同風格）
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = intake_ai.read_url
        intake_ai.read_url = lambda url: (False, "", "網站 10 秒內沒有回應")

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        intake_ai.read_url = self._orig_fetch
        self._envpatch.stop()

    def _brand_name(self) -> str:
        _SEQ[0] += 1
        return f"虛構建檔API測試品牌{_SEQ[0]}"

    def _create_full(self) -> str:
        """建立一個有草稿、要跑初掃（第 2 步）的品牌，回傳 brand_id。F42-I04 起只有網址或
        照片才會掃，描述本身不算，所以這裡帶一個網址（fetch_url 在 setUp 已換成讀不到）。"""
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "description": "一句測試用的品牌描述文字。",
            "urls": "https://example.com/about",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        return body["brand_id"]


# ---------------------------------------------------------------------------
# 2026-09-14：草稿永遠建立——三欄皆空只是沒東西可掃，第 3／4／5 步跟掃描無關
# （S4.9 時代「陽春路徑不建草稿」的假設已不成立，見 F05-I15）
# ---------------------------------------------------------------------------

class QuickPathTest(_Base):
    def test_json_only_name_still_creates_draft_at_step_3(self):
        name = self._brand_name()
        resp = self.client.post("/api/intake/brands", data={"brand_name": name})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        draft = state.get_draft(body["brand_id"])
        self.assertIsNotNone(draft)
        self.assertEqual(draft["step"], 3)
        self.assertTrue(draft["scan_done"])
        self.assertEqual(draft["cost_items"], [])
        # 品牌真的建了
        draft_resp = self.client.get(f"/api/intake/brands/{body['brand_id']}/draft")
        self.assertEqual(draft_resp.status_code, 200)

    def test_new_brand_has_coordinate_vocabulary(self):
        # Drill 5: the ads delivery plan needs the vocabulary; nothing else seeds it for a new brand.
        from app.core.db import connection
        bid = self._create_full()
        with connection() as conn:
            dims = {r["dimension"] for r in conn.execute(
                "SELECT DISTINCT dimension FROM brand_coordinate WHERE brand_id = %s", (bid,)).fetchall()}
        self.assertEqual(dims, {"audience", "pain", "angle", "hook", "proof", "offer", "format"})

    def test_json_with_description_creates_draft(self):
        bid = self._create_full()
        self.assertIsNotNone(state.get_draft(bid))



    def test_missing_name_json_errors(self):
        resp = self.client.post("/api/intake/brands", data={"brand_name": ""})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測，guard 本身才是重點

    def test_bad_url_format_rejected(self):
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "urls": "not-a-url",
        })
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_restart_still_creates_draft_at_step_3_when_no_new_data(self):
        bid = self._create_full()
        state.complete_draft(state.get_draft(bid))  # 完成這一輪，之後才能重新建檔
        resp = self.client.post(f"/api/intake/brands/{bid}/restart", data={})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["quick"])
        restarted = state.get_draft(bid)
        self.assertIsNotNone(restarted)
        self.assertEqual(restarted["step"], 3)

    def test_restart_blocked_when_draft_already_running(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/restart",
                                 data={"description": "第二輪"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        self.assertTrue(body.get("already_running"))


# ---------------------------------------------------------------------------
# 照片預先上傳（POST /api/intake/photos）
# ---------------------------------------------------------------------------

class PhotoUploadTest(_Base):
    def test_upload_then_reference_token_in_start(self):
        import io
        up = self.client.post("/api/intake/photos",
                              files={"photo": ("t.jpg", io.BytesIO(_JPEG), "image/jpeg")})
        self.assertEqual(up.status_code, 200)
        body = up.json()
        self.assertEqual(set(body.keys()), {"token", "name", "size_mb"})
        storage_key = state.get_pending_photos(body["token"])[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=storage_key)
        name = self._brand_name()
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": name, "photo_tokens": body["token"],
        })
        self.assertFalse(resp.json()["quick"])  # 照片路徑仍從初掃步（第 2 步）開始
        draft = state.get_draft(resp.json()["brand_id"])
        self.assertEqual(draft["step"], 2)
        self.assertEqual(len(draft["photos"]), 1)
        self.assertEqual(draft["photos"][0]["name"], "t.jpg")

    def test_upload_stores_object_under_callers_org_id(self):
        """票 storage-03：物件 key 第一段必須是呼叫者的 org_id——租戶邊界檢查
        （proven red once：暫時把斷言換成別的 org 前綴，看它真的失敗，再改回來）。"""
        import io
        up = self.client.post("/api/intake/photos",
                              files={"photo": ("t.jpg", io.BytesIO(_JPEG), "image/jpeg")})
        self.assertEqual(up.status_code, 200)
        token = up.json()["token"]
        storage_key = state.get_pending_photos(token)[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=storage_key)
        self.assertTrue(storage_key.startswith(f"{DEV_ORG_ID}/"))

    def test_get_photo_returns_bytes_and_unregistered_filename_404s(self):
        import io
        content = PNG + b"fake-png-bytes"
        up = self.client.post("/api/intake/photos",
                              files={"photo": ("p.png", io.BytesIO(content), "image/png")})
        self.assertEqual(up.status_code, 200)
        token = up.json()["token"]
        storage_key = state.get_pending_photos(token)[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=storage_key)
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "photo_tokens": token,
        })
        brand_id = resp.json()["brand_id"]

        got = self.client.get(f"/brands/{brand_id}/intake/photos/p.png")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, content)

        missing = self.client.get(f"/brands/{brand_id}/intake/photos/nope.png")
        self.assertEqual(missing.status_code, 404)

    def test_bad_extension_rejected(self):
        import io
        resp = self.client.post("/api/intake/photos",
                                files={"photo": ("t.exe", io.BytesIO(b"x" * 10), "application/octet-stream")})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_content_decides_not_the_file_name(self):
        """F47 Contract A: a text file named .jpg and a 0-byte file are refused with the user
        sentence; a real PNG named .jpg is accepted and stored as PNG."""
        import io
        resp = self.client.post("/api/intake/photos",
                                files={"photo": ("text.jpg", io.BytesIO(b"just text"), "image/jpeg")})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "「text.jpg」的內容不是JPEG、PNG 或 WebP 圖片，請換一張。"})
        resp = self.client.post("/api/intake/photos",
                                files={"photo": ("empty.jpg", io.BytesIO(b""), "image/jpeg")})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "「empty.jpg」是空的檔案，請換一個。"})

        png = PNG
        resp = self.client.post("/api/intake/photos",
                                files={"photo": ("photo.jpg", io.BytesIO(png), "image/jpeg")})
        self.assertEqual(resp.status_code, 200, resp.text)
        key = state.get_pending_photos(resp.json()["token"])[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=key)
        self.assertEqual(storage.get(org_id=DEV_ORG_ID, key=key), (png, "image/png"))


# ---------------------------------------------------------------------------
# 草稿整包（GET .../draft）：欄位對照前端契約
# ---------------------------------------------------------------------------

class DraftShapeTest(_Base):
    def test_shape_matches_frontend_contract_keys(self):
        bid = self._create_full()
        data = self.client.get(f"/api/intake/brands/{bid}/draft").json()["data"]
        # F42-I14: the retired stage's fields (impressions, Q&A, handoff, paste, cost rail) are gone.
        expected = {
            "id", "brand_id", "brand_name", "step", "completed",
            "description", "urls", "photos", "scan_done",
        }
        self.assertEqual(set(data.keys()), expected)
        self.assertEqual(data["step"], 2)
        self.assertFalse(data["completed"])

    def test_completed_draft_still_reads(self):
        """A finished brand re-entering the onboarding reads its latest completed draft."""
        bid = self._create_full()
        state.complete_draft(state.get_draft(bid))
        resp = self.client.get(f"/api/intake/brands/{bid}/draft")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["completed"])

    def test_retired_routes_are_gone(self):
        bid = self._create_full()
        for method, path in (("post", "scan/start"), ("get", "scan/status"), ("post", "scan/skip"),
                             ("post", "question/start"), ("get", "truth-card"),
                             ("post", "paste/validate"), ("get", "research-reports"),
                             ("post", "budget"), ("post", "skip-remaining-ai"),
                             ("get", "offerings"), ("post", "research/start")):
            resp = getattr(self.client, method)(f"/api/intake/brands/{bid}/{path}")
            self.assertIn(resp.status_code, (404, 405), f"{method} {path}")


if __name__ == "__main__":
    unittest.main()
