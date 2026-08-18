# -*- coding: utf-8 -*-
"""app/tests/test_brand_edit_industry.py — 品牌編輯頁的業種欄位（code-review 補票，ADR 0014）。

`set_brand_industry()` 本身已有 repository 層測試（test_dashboard_campaign_calendar_wiring.py），
這裡補的是 HTTP 表單這一段——沒有這段，brand.industry 永遠是 NULL，節日相關性比對形同虛設。
沿用 test_settings_hub.py 的暫存 DB／TestClient 慣例：真實 SQLite，不 mock。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_brand_edit_industry_")

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


class BrandEditIndustryFieldTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構業種茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_edit_page_shows_industry_dropdown(self):
        resp = self.client.get(f"/brands/{self.bid}/edit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("業種", resp.text)
        self.assertIn("食品飲料", resp.text)

    def test_post_valid_industry_saves_and_reflects_on_get(self):
        resp = self.client.post(f"/brands/{self.bid}/edit", data={
            "name": "虛構業種茶行", "status": "active", "industry": "food_beverage",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(bi_repo.get_brand(main.conn, self.bid)["industry"], "food_beverage")
        resp = self.client.get(f"/brands/{self.bid}/edit")
        self.assertIn('value="food_beverage" selected', resp.text.replace("\n", " "))

    def test_post_invalid_industry_rejected_with_error(self):
        resp = self.client.post(f"/brands/{self.bid}/edit", data={
            "name": "虛構業種茶行", "status": "active", "industry": "not_a_real_industry",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請選擇有效的業種", resp.text)
        self.assertIsNone(bi_repo.get_brand(main.conn, self.bid)["industry"])

    def test_blank_industry_stays_unset(self):
        resp = self.client.post(f"/brands/{self.bid}/edit", data={
            "name": "虛構業種茶行", "status": "active", "industry": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(bi_repo.get_brand(main.conn, self.bid)["industry"])


if __name__ == "__main__":
    unittest.main()
