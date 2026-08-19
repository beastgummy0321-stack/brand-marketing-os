# -*- coding: utf-8 -*-
"""品牌風格偏好採 app_setting namespaced key，且明確空值不回退。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import repository as ads_repo
from app.ads import style_preference, theme_repository
from app.brand_intelligence import repository as bi
from app.core import db, settings
from app.creative import theme_engine as creative_theme_engine


class StylePreferenceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self.tmpdir.name) / "test.db")
        self.previous_web_conn = web.conn
        web.conn = self.conn
        self.client = TestClient(main.app)
        self.one = bi.create_brand(self.conn, name="甲", client_name=None, actor="tester")
        self.two = bi.create_brand(self.conn, name="乙", client_name=None, actor="tester")
        settings.set_setting(self.conn, settings.IMAGE_PROMPT_HEADER_SETTING, "舊全域開頭")

    def tearDown(self):
        web.conn = self.previous_web_conn
        self.conn.close()
        self.tmpdir.cleanup()

    def test_default_and_brand_isolation(self):
        self.assertEqual(style_preference.get_text(self.conn, self.one["id"]), "舊全域開頭")
        style_preference.set_text(self.conn, self.one["id"], "甲風格")
        self.assertEqual(style_preference.get_text(self.conn, self.one["id"]), "甲風格")
        self.assertEqual(style_preference.get_text(self.conn, self.two["id"]), "舊全域開頭")

    def test_empty_value_omits_style_segment(self):
        style_preference.set_text(self.conn, self.one["id"], "")
        self.assertEqual(style_preference.get_text(self.conn, self.one["id"]), "")

    def test_http_put_get_and_copy_endpoint_use_brand_value(self):
        base = f"/api/settings/brands/{self.one['id']}/style-preference"
        self.assertEqual(self.client.put(base, json={"text": "甲牌手繪質感"}).status_code, 200)
        self.assertEqual(self.client.get(base).json(), {"text": "甲牌手繪質感"})
        self.assertEqual(self.client.get(
            f"/api/settings/brands/{self.two['id']}/style-preference").json()["text"], "舊全域開頭")

        product = bi.create_product(self.conn, self.one["id"], name="測試商品", actor="tester")
        cycle = ads_repo.create_cycle(self.conn, self.one["id"], product_ids=[product["id"]],
                                      pain_value=5, objective="sales", actor="tester")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at) VALUES ('exc_style', ?, ?, ?)",
            (cycle["id"], self.one["id"], db.now_iso()),
        )
        self.conn.commit()
        theme = theme_repository.create_theme(
            self.conn, self.one["id"], campaign_cycle_id=cycle["id"], experiment_cell_id="exc_style",
            format_key="single_image", name="風格測試", folder_code="STYL", actor="tester",
            components=[{"component_type": "image_prompt", "content": "一杯咖啡", "sequence": 1}],
        )
        copied = self.client.get(
            f"/api/ads/brands/{self.one['id']}/ads/{cycle['id']}/themes/{theme['id']}/image-prompts/copy")
        self.assertEqual(copied.status_code, 200)
        self.assertIn("甲牌手繪質感", copied.json()["groups"][0]["content"])

    def test_generated_prompt_receives_style_and_empty_value_omits_it(self):
        brief = SimpleNamespace(
            brand={"name": "甲"}, plan={"summary": "測試"}, cell={"creative_angle": "晨間"},
            brand_context="已確認資料", offer=None, methodology="", rejection_constraints=[],
            customer_voice="", existing_themes_summary=[], fingerprint_vocabulary="指紋詞彙",
        )
        plan = {"image_prompt": {"count": 1}, "body": {"count": 1, "char_budget": 20},
                "title": {"count": 1, "char_budget": 20}, "description": {"count": 1, "char_budget": 20}}
        prompt = creative_theme_engine.build_single_image_prompt(
            brief, plan, object(), style_preference="甲牌手繪質感")
        self.assertIn("甲牌手繪質感", prompt)
        empty = creative_theme_engine.build_single_image_prompt(brief, plan, object(), style_preference="")
        self.assertNotIn("品牌圖片風格偏好", empty)
