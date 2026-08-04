# -*- coding: utf-8 -*-
"""app/tests/test_settings_page.py — 設定頁（/settings）與 providers 接設定的行為。

見 docs/design/07-settings-and-intake-contract.md §1、§3。
全程用暫存 DB（BRAND_OS_DB 指到 tempdir），不發任何真實網路請求。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_settings_page_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import ga4_api, ga4_sync, meta_api  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm import pricing, providers  # noqa: E402
from app.tools import capacity_check as cc  # noqa: E402

# 若 app.main 在本檔之前就被別的模組 import 過，重開連線確保連到本檔的暫存 DB。
main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

TEST_KEY = "sk-ant-test-0000-1234abcd"


class SettingsPageTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        self.client = TestClient(main.app)
        # 隔離環境變數：這幾條測試只看 DB 設定
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)

    def tearDown(self):
        self._env.stop()

    def test_settings_page_renders(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        for text in ("AI 金鑰", "測試連線", "使用的模型", "花費上限",
                     "Claude Opus 5", "Claude Sonnet 5", "Claude Haiku 4.5", "Claude Fable 5",
                     "US$5", "US$3", "US$1", "US$10",
                     # 票 #27：任務 →（模型、思考等級）對照表要可視
                     "各任務的預設模型與思考等級", "檔期規劃（出方案）", "素材生成（整批）",
                     "超高", "極高"):
            self.assertIn(text, resp.text)
        # 預設花費上限（DEFAULT_BUDGET=30）預填在欄位裡
        self.assertIn('value="30"', resp.text)

    def test_api_key_saved_masked_and_persists_after_restart(self):
        resp = self.client.post("/settings/api-key", data={"api_key": TEST_KEY},
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

        page = self.client.get("/settings").text
        self.assertNotIn(TEST_KEY, page)          # 畫面永不顯示完整金鑰
        self.assertIn("sk-…abcd", page)           # 遮罩：sk-…末四碼
        self.assertIn("更換資料庫裡的金鑰", page)
        self.assertIn("目前使用中的金鑰來自資料庫", page)  # 無環境變數時誠實標示來源（票 M4）
        self.assertIn("清除資料庫裡的金鑰", page)         # 有 DB 金鑰時才出現清除路徑

        # 模擬重啟：重建連線後金鑰仍在（真的落地在 DB 檔案）
        main.reopen_connection()
        page = TestClient(main.app).get("/settings").text
        self.assertIn("sk-…abcd", page)
        self.assertNotIn(TEST_KEY, page)

    def test_api_key_empty_shows_error(self):
        resp = self.client.post("/settings/api-key", data={"api_key": "  "})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請貼上 AI 金鑰。", resp.text)

    # -- 票 M4：環境變數優先＋誠實提示來源＋清除 DB 金鑰的明確路徑 -------------------

    def test_env_key_takes_priority_and_page_says_so(self):
        """環境變數優先於 DB；設定頁誠實顯示「目前使用中的金鑰來自環境變數」，
        而不是無聲地繼續用 DB 裡的舊金鑰（修憲落地 M4）。"""
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        os.environ["ANTHROPIC_API_KEY"] = "env-only-value-not-shown"
        try:
            self.assertEqual(coresettings.get_api_key(main.conn), "env-only-value-not-shown")
            page = self.client.get("/settings").text
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertIn("目前使用中的金鑰來自", page)
        self.assertIn("環境變數", page)
        self.assertNotIn("env-only-value-not-shown", page)  # 環境變數的值也不外顯
        # DB 裡仍有舊金鑰時，清除路徑仍要在畫面上（即便目前用的是環境變數）
        self.assertIn('action="/settings/api-key/clear-db"', page)

    def test_no_key_anywhere_shows_no_clear_button(self):
        page = self.client.get("/settings").text
        self.assertNotIn('action="/settings/api-key/clear-db"', page)

    def test_clear_db_key_deletes_db_value_and_redirects(self):
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        resp = self.client.post("/settings/api-key/clear-db", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)  # PRG：POST 後轉址，不是就地渲染
        self.assertIsNone(coresettings.get_setting(main.conn, coresettings.API_KEY_SETTING))

        page = self.client.get(resp.headers["location"]).text
        self.assertIn("已清除資料庫裡的金鑰", page)
        self.assertNotIn('action="/settings/api-key/clear-db"', page)  # 清掉後按鈕消失

    def test_clear_db_key_does_not_affect_env_key(self):
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        os.environ["ANTHROPIC_API_KEY"] = "env-only-value-not-shown"
        try:
            resp = self.client.post("/settings/api-key/clear-db", follow_redirects=False)
            self.assertEqual(resp.status_code, 303)
            self.assertEqual(coresettings.get_api_key(main.conn), "env-only-value-not-shown")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_model_saved_and_used_by_resolve_model(self):
        resp = self.client.post("/settings/model", data={"llm_model": "claude-sonnet-5"},
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(coresettings.get_llm_model(main.conn), "claude-sonnet-5")
        # providers.resolve_model 走同一條優先順序（DB 設定生效）
        self.assertEqual(providers.resolve_model(conn=main.conn), "claude-sonnet-5")
        # 選單外的值被擋下
        resp = self.client.post("/settings/model", data={"llm_model": "不存在的模型"})
        self.assertEqual(resp.status_code, 400)

    def test_budget_validation_and_save(self):
        for bad in ("abc", "-5", "0", ""):
            resp = self.client.post("/settings/budget", data={"intake_budget": bad})
            self.assertEqual(resp.status_code, 400, bad)
            self.assertIn("花費上限請填大於 0 的數字", resp.text)
        # 驗證失敗回填原輸入
        resp = self.client.post("/settings/budget", data={"intake_budget": "abc"})
        self.assertIn('value="abc"', resp.text)

        resp = self.client.post("/settings/budget", data={"intake_budget": "45"},
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(coresettings.get_intake_budget_limit(main.conn), 45.0)

    def test_test_connection_without_key_gives_human_message(self):
        """無金鑰時不發請求，直接回人話提示（07 §3；本輪驗收指定路徑）。"""
        resp = self.client.post("/settings/test-connection")
        self.assertEqual(resp.status_code, 200)  # 303 轉回設定頁後渲染
        self.assertIn("尚未設定金鑰", resp.text)

    def test_test_connection_success_shows_human_message(self):
        """有金鑰且供應商回應正常：路由層要顯示「金鑰有效」（D線修正：原本這一態只在
        providers 層做過單元測試，沒打過 /settings/test-connection 這條路由）。"""
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        fake = providers.FakeProvider()
        with mock.patch.object(providers, "AnthropicProvider", return_value=fake):
            resp = self.client.post("/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("金鑰有效", resp.text)
        self.assertEqual(len(fake.calls), 1)

    def test_test_connection_key_error_shows_human_message(self):
        """金鑰錯誤：路由層要把 ProviderError 的人話訊息原樣顯示，不夾帶術語（同上，
        原本這一態也只在 providers 層做過單元測試）。"""
        coresettings.set_setting(main.conn, coresettings.API_KEY_SETTING, TEST_KEY)
        fake = providers.FakeProvider(exception=providers.ProviderError(
            "金鑰錯誤：AI 服務不接受這把金鑰。請確認複製時有沒有少字，或到 Anthropic 重新產生一把。"))
        with mock.patch.object(providers, "AnthropicProvider", return_value=fake):
            resp = self.client.post("/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("金鑰錯誤", resp.text)

    def test_provider_without_key_raises_human_error(self):
        """AnthropicProvider 在缺金鑰時於發出請求前就拋人話錯誤，不碰網路。"""
        with self.assertRaises(providers.ProviderError) as cm:
            providers.AnthropicProvider().complete(
                model="claude-opus-5", system=None,
                messages=[{"role": "user", "content": "hi"}], max_tokens=1,
            )
        message = str(cm.exception)
        self.assertIn("尚未設定 AI 金鑰", message)
        self.assertNotIn("ANTHROPIC_API_KEY", message)  # 不出現環境變數名（07 §3 規則 3）

    def test_provider_401_becomes_human_message(self):
        """金鑰錯誤（401）要轉成人話，不得把供應商原始 JSON／request id 帶出來（§12）。"""
        import anthropic
        import httpx

        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(
            401, request=request,
            json={"type": "error",
                  "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                  "request_id": "req_test_123"},
        )
        exc_401 = anthropic.APIStatusError("Error code: 401", response=response,
                                           body=response.json())
        fake_client = mock.Mock()
        fake_client.with_options.return_value = fake_client
        fake_client.messages.create.side_effect = exc_401
        with mock.patch.object(coresettings, "get_api_key", return_value="sk-fake"), \
             mock.patch.object(anthropic, "Anthropic", return_value=fake_client):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.AnthropicProvider().complete(
                    model="claude-opus-5", system=None,
                    messages=[{"role": "user", "content": "hi"}], max_tokens=1,
                )
        message = str(cm.exception)
        self.assertIn("金鑰錯誤", message)
        for jargon in ("request_id", "invalid x-api-key", "401", "{"):
            self.assertNotIn(jargon, message)

    def test_pricing_covers_all_menu_models(self):
        for model_id, _name in main.MODEL_CHOICES:
            self.assertGreater(pricing.calculate_cost(model_id, 1000, 1000), 0)

    # -- 票 #48：5 分區收斂、0 主要按鈕、容量合規 --------------------------------

    def test_settings_page_has_five_sections_no_primary_button_and_passes_capacity(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.text.count('class="settings-section"'), 5)
        self.assertNotIn("btn-primary", resp.text)  # 全站首個 0 主要按鈕的表單頁（§7.6）
        counts = cc.check_html(resp.text)
        self.assertEqual(cc.violations("/settings", counts), [])

    # -- 票 #48：Meta 測試連線 ---------------------------------------------------

    def test_meta_test_connection_without_config_warns_and_sends_no_request(self):
        resp = self.client.post("/settings/meta/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("尚未設定 Meta 連線", resp.text)

    def test_meta_test_connection_success(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(campaigns=[])
        with mock.patch.object(ads_sync, "make_client", return_value=fake):
            resp = self.client.post("/settings/meta/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("連線正常", resp.text)
        self.assertEqual(fake.calls, [("campaigns", "act_123")])

    def test_meta_test_connection_failure_shows_human_error(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(error=meta_api.MetaApiError(
            "Meta 拒絕了這次連線，通常是金鑰失效或權限被收回。請到「設定」頁重新產生一組唯讀金鑰。"))
        with mock.patch.object(ads_sync, "make_client", return_value=fake):
            resp = self.client.post("/settings/meta/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Meta 拒絕了這次連線", resp.text)

    # -- 票 #48：GA4 測試連線 -----------------------------------------------------

    def test_ga4_test_connection_without_config_warns_and_sends_no_request(self):
        resp = self.client.post("/settings/ga4/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("尚未設定 GA4 連線", resp.text)

    def test_ga4_test_connection_success(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}')
        fake = ga4_api.FakeGA4Client(rows=[])
        with mock.patch.object(ga4_sync, "make_client", return_value=fake):
            resp = self.client.post("/settings/ga4/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("連線正常", resp.text)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][0], "source_medium")

    def test_ga4_test_connection_failure_shows_human_error(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}')
        fake = ga4_api.FakeGA4Client(error=ga4_api.GA4ApiError(
            "連不上 GA4，可能是網路問題或金鑰權限不足。稍後再試一次。"))
        with mock.patch.object(ga4_sync, "make_client", return_value=fake):
            resp = self.client.post("/settings/ga4/test-connection")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("連不上 GA4", resp.text)


if __name__ == "__main__":
    unittest.main()
