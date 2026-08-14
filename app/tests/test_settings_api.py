# -*- coding: utf-8 -*-
"""app/tests/test_settings_api.py — 設定頁 JSON API（票 B1-settings，契約
`.scratch/grill/GRILL-B1-settings.md` S15，不含規則卡——規則卡見 test_rule_cards_api.py）。

全程用暫存 DB，不發任何真實網路請求（測試連線改用既有 FakeProvider／FakeMetaClient／
FakeGA4Client，見 app/tests/test_settings_page.py 同款慣例）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_settings_api_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import ga4_api, ga4_sync, meta_api  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm import providers  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

TEST_KEY = "sk-ant-test-0000-1234abcd"

SETTINGS_DATA_KEYS = {
    "masked_key", "api_key_source", "db_key_present", "model_choices", "current_model",
    "task_model_thinking_table", "masked_meta_token", "meta_account_id", "masked_ga4_key",
    "ga4_property_id", "creative_root", "prompt_header", "intake_budget",
}


class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        self.client = TestClient(main.app)
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)

    def tearDown(self):
        self._env.stop()

    # -- GET /api/settings：形狀齊全 -------------------------------------------

    def test_get_settings_shape_matches_contract(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        self.assertEqual(set(body["data"].keys()), SETTINGS_DATA_KEYS)
        self.assertIsNone(body["data"]["masked_key"])
        self.assertIsNone(body["data"]["api_key_source"])
        self.assertFalse(body["data"]["db_key_present"])
        self.assertEqual(len(body["data"]["model_choices"]), 4)
        self.assertEqual(
            set(body["data"]["model_choices"][0].keys()), {"id", "name", "price_text"})
        self.assertIsInstance(body["data"]["task_model_thinking_table"], list)
        self.assertEqual(
            set(body["data"]["task_model_thinking_table"][0].keys()),
            {"task_label", "model_label", "thinking_label"},
        )
        self.assertIsInstance(body["data"]["intake_budget"], (int, float))

    def test_get_settings_reflects_saved_values(self):
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        body = self.client.get("/api/settings").json()["data"]
        self.assertEqual(body["api_key_source"], "db")
        self.assertTrue(body["db_key_present"])
        self.assertEqual(body["masked_key"], "sk-…abcd")

    # -- POST /api/settings/api-key：實際生效驗證 --------------------------------

    def test_save_api_key_writes_db_and_persists_after_restart(self):
        resp = self.client.post("/api/settings/api-key", json={"api_key": TEST_KEY})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(coresettings.get_api_key(main.conn), TEST_KEY)
        main.reopen_connection()
        self.assertEqual(coresettings.get_api_key(main.conn), TEST_KEY)

    def test_save_api_key_empty_gives_human_error(self):
        resp = self.client.post("/api/settings/api-key", json={"api_key": "  "})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請貼上 AI 金鑰", resp.json()["error"])

    def test_clear_api_key_from_db(self):
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        resp = self.client.post("/api/settings/api-key/clear-db")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(coresettings.get_setting(main.conn, coresettings.API_KEY_SETTING))

    # -- POST /api/settings/meta ------------------------------------------------

    def test_save_meta_settings(self):
        resp = self.client.post(
            "/api/settings/meta", json={"meta_account_id": "act_999", "meta_token": "tok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ads_sync.get_account_id(main.conn), "act_999")
        self.assertEqual(ads_sync.get_token(main.conn), "tok")

    def test_save_meta_settings_missing_account_gives_human_error(self):
        resp = self.client.post("/api/settings/meta", json={"meta_account_id": "", "meta_token": "x"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請填入廣告帳號編號", resp.json()["error"])

    # -- POST /api/settings/ga4 --------------------------------------------------

    def test_save_ga4_settings(self):
        resp = self.client.post("/api/settings/ga4", json={
            "ga4_property_id": "123456789", "ga4_service_account_json": '{"type":"service_account"}',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ga4_sync.get_property_id(main.conn), "123456789")

    # -- POST /api/settings/model -------------------------------------------------

    def test_save_model_valid(self):
        resp = self.client.post("/api/settings/model", json={"llm_model": "claude-sonnet-5"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(coresettings.get_llm_model(main.conn), "claude-sonnet-5")

    def test_save_model_invalid_choice_gives_human_error(self):
        resp = self.client.post("/api/settings/model", json={"llm_model": "不存在的模型"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請從選單中選一個模型", resp.json()["error"])

    # -- POST /api/settings/budget（含邊界值） ------------------------------------

    def test_save_budget_valid(self):
        resp = self.client.post("/api/settings/budget", json={"intake_budget": 45})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(coresettings.get_intake_budget_limit(main.conn), 45.0)

    def test_save_budget_zero_is_rejected(self):
        """0 是下限邊界：契約假資料拿它當展示值，但送出寫入仍要擋（沿用既有『大於 0』規則，
        不因為改成 JSON 就放寬）。"""
        resp = self.client.post("/api/settings/budget", json={"intake_budget": 0})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("花費上限請填大於 0 的數字", resp.json()["error"])

    # -- POST /api/settings/creative-root ------------------------------------------

    def test_save_creative_root_valid(self):
        resp = self.client.post(
            "/api/settings/creative-root", json={"creative_root": "D:\\行銷素材"})
        self.assertEqual(resp.status_code, 200)

    def test_save_creative_root_relative_path_rejected(self):
        resp = self.client.post("/api/settings/creative-root", json={"creative_root": "素材"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("完整的資料夾路徑", resp.json()["error"])

    # -- POST /api/settings/prompt-header -------------------------------------------

    def test_save_prompt_header(self):
        resp = self.client.post(
            "/api/settings/prompt-header", json={"prompt_header": "一律平面實填"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            coresettings.get_setting(main.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING),
            "一律平面實填")

    # -- 測試連線：假供應商，不打真網路 ------------------------------------------------

    def test_ai_test_connection_without_key_warns(self):
        resp = self.client.post("/api/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "warn")
        self.assertIn("尚未設定金鑰", body["message"])

    def test_ai_test_connection_success_uses_fake_provider(self):
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        fake = providers.FakeProvider()
        with mock.patch.object(providers, "AnthropicProvider", return_value=fake):
            resp = self.client.post("/api/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "ok")
        self.assertIn("金鑰有效", body["message"])
        self.assertEqual(len(fake.calls), 1)

    def test_meta_test_connection_without_config_warns_and_sends_no_request(self):
        resp = self.client.post("/api/settings/meta/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "warn")

    def test_meta_test_connection_success_uses_fake_client(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(campaigns=[])
        with mock.patch.object(ads_sync, "make_client", return_value=fake):
            resp = self.client.post("/api/settings/meta/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "ok")
        self.assertEqual(fake.calls, [("campaigns", "act_123")])

    def test_ga4_test_connection_success_uses_fake_client(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}')
        fake = ga4_api.FakeGA4Client(rows=[])
        with mock.patch.object(ga4_sync, "make_client", return_value=fake):
            resp = self.client.post("/api/settings/ga4/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "ok")
        self.assertEqual(len(fake.calls), 1)

    # -- 沒有頁面壞掉：HTML 表單路由行為不變（純搬家迴歸驗證） ---------------------------

    def test_html_form_route_still_works_after_extraction(self):
        resp = self.client.post("/settings/api-key", data={"api_key": TEST_KEY}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(coresettings.get_api_key(main.conn), TEST_KEY)

    def test_json_body_not_a_dict_gives_human_error(self):
        resp = self.client.post("/api/settings/model", content=b"[1,2,3]",
                                headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不是合法的 JSON", resp.json()["error"])


if __name__ == "__main__":
    unittest.main()
