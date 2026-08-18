# -*- coding: utf-8 -*-
"""app/tests/test_guide_pages_visual_refresh.py — 票 02-tutorial-pages-visual-refresh：
Pixel／GA4／顧客口碑蒐集三張教學頁套新設計系統 CSS token，內容與結構不變。

驗收對應 .scratch/glossary-tutorial-refresh/issues/02-tutorial-pages-visual-refresh.md：
1. 三頁套用 guide_refresh.css（新 token）。
2. 三頁文字內容、連結不變。
3. 三頁仍在 Jinja（走既有 TemplateResponse，非 React）。
4. 三頁仍嵌在各自原本的流程入口，沒有新增獨立導覽（本測試不驗證「沒有新入口」——
   那是負向斷言，交給人工核對路由表；這裡只驗證三頁本身的輸出）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_guide_refresh_")
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-invalid-test-key"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class GuidePagesVisualRefreshTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露烘焙",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _assert_wired(self, resp, must_contain):
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<link rel="stylesheet" href="/static/guide_refresh.css">', resp.text)
        self.assertIn('<div class="guide-refresh">', resp.text)
        for phrase in must_contain:
            self.assertIn(phrase, resp.text)

    def test_pixel_guide_wired_to_new_tokens_content_unchanged(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/pixel-guide")
        self._assert_wired(resp, [
            "Pixel 安裝教學", "help.shopify.com", "easystore.co", "cyberbiz.io",
            "Pixel 只需要裝一次，不是每期廣告都要重裝。",
        ])

    def test_ga4_guide_wired_to_new_tokens_content_unchanged(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/ga4-guide")
        self._assert_wired(resp, [
            "GA4 服務帳戶設定教學", "cloud.google.com/iam/docs/service-accounts-create",
            "熟悉 Google Cloud",
        ])

    def test_customer_voice_guide_wired_to_new_tokens_content_unchanged(self):
        resp = self.client.get(f"/brands/{self.bid}/customer-voice/guide")
        self._assert_wired(resp, [
            "去哪找顧客原話", "蝦皮商品評論", "具體情境", "好用+1",
        ])

    def test_guide_refresh_css_served_with_expected_tokens(self):
        """新 CSS 檔要能被 /static 掛載讀到，且色彩／字體數值抄自 tokens.css，不是另立新值。"""
        resp = self.client.get("/static/guide_refresh.css")
        self.assertEqual(resp.status_code, 200)
        css = resp.text
        self.assertIn(".guide-refresh {", css)
        self.assertIn("--accent: #0369a1;", css)  # tokens.css --color-primary
        self.assertIn('--font-sans: "Inter"', css)  # tokens.css --font-sans
        self.assertIn("--radius-md: 0.5rem;", css)  # tokens.css --radius-md

    def test_other_console_pages_do_not_pick_up_guide_refresh_scope(self):
        """確認換皮只掛在三張教學頁，不是動了 app.css 全站 token（爆炸半徑檢查）。"""
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("guide_refresh.css", resp.text)
        self.assertNotIn('class="guide-refresh"', resp.text)


if __name__ == "__main__":
    unittest.main()
