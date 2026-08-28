"""app/tests/test_settings_api.py — 設定頁 JSON API（票 B1-settings，契約
`.scratch/grill/GRILL-B1-settings.md` S15，不含規則卡——規則卡見 test_rule_cards_api.py）。

全程用暫存 DB，不發任何真實網路請求（測試連線改用既有 FakeProvider）。

外殼切片（2026-08-28）：Meta／GA4 連線設定的欄位與端點隨 `app/ads/` 一起刪掉，
相關案例一併移除。ProviderHumanErrorTest 是從已刪除的 test_settings_page.py 搬過來的
AnthropicProvider／pricing 直接單元測試（不經 HTTP 路由，票 T4 A4 刪 Jinja 頁面時
這幾條測試本來就不碰模板，只是恰好住在同一個檔案）。
"""

import os
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.core import db as coredb
from app.core import settings as coresettings
from app.identity import repository as identity_repo
from app.llm import pricing, providers

from .identity_test_helpers import mint_hs256

TEST_KEY = "sk-ant-test-0000-1234abcd"

SETTINGS_DATA_KEYS = {
    "masked_key", "api_key_source", "db_key_present", "model_choices", "current_model",
    "task_model_thinking_table", "creative_root", "prompt_header", "intake_budget",
    "ai_key_source", "ai_cap_applies", "ai_monthly_spend", "ai_monthly_cost_limit", "is_owner",
}


class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
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
        # 票 04-1a：預設沒設過 ai_key_source → 'platform'（操作者付錢），上限是硬性關卡，
        # 這個月還沒花錢，上限用系統預設值。dev token 固定是 org_dev 的 owner（見
        # app/identity/__init__.py _dev_actor），is_owner 應該是 True。
        self.assertEqual(body["data"]["ai_key_source"], "platform")
        self.assertTrue(body["data"]["ai_cap_applies"])
        self.assertEqual(body["data"]["ai_monthly_spend"], 0)
        self.assertEqual(
            body["data"]["ai_monthly_cost_limit"], coresettings.DEFAULT_AI_MONTHLY_COST_LIMIT)
        self.assertTrue(body["data"]["is_owner"])

    def test_get_settings_reflects_saved_values(self):
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        body = self.client.get("/api/settings").json()["data"]
        self.assertEqual(body["api_key_source"], "db")
        self.assertTrue(body["db_key_present"])
        self.assertEqual(body["masked_key"], "sk-…abcd")

    # -- POST /api/settings/api-key：實際生效驗證 --------------------------------

    def test_save_api_key_writes_db_and_persists_after_restart(self):
        """ADR 0027：不再有「重開連線」這回事了（連線池按 request 借連線，不是
        全程共用一條）——改成從一條全新借來的連線讀回，證明真的落庫了，不是只留在
        寫入那個 request 的連線快取裡（同樣的持久性主張，換了機制去驗）。"""
        resp = self.client.post("/api/settings/api-key", json={"api_key": TEST_KEY})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(coresettings.get_api_key(web.conn, org_id=coredb.DEV_ORG_ID), TEST_KEY)
        with coredb.connection() as fresh:
            self.assertEqual(coresettings.get_api_key(fresh, org_id=coredb.DEV_ORG_ID), TEST_KEY)

    def test_save_api_key_empty_gives_human_error(self):
        resp = self.client.post("/api/settings/api-key", json={"api_key": "  "})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請貼上 AI 金鑰", resp.json()["error"])

    def test_clear_api_key_from_db(self):
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        resp = self.client.post("/api/settings/api-key/clear-db")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(coresettings.get_setting(
            web.conn, coresettings.API_KEY_SETTING, org_id=coredb.DEV_ORG_ID))

    # -- POST /api/settings/model -------------------------------------------------

    def test_save_model_valid(self):
        resp = self.client.post("/api/settings/model", json={"llm_model": "claude-sonnet-5"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            coresettings.get_llm_model(web.conn, org_id=coredb.DEV_ORG_ID), "claude-sonnet-5")

    def test_save_model_invalid_choice_gives_human_error(self):
        resp = self.client.post("/api/settings/model", json={"llm_model": "不存在的模型"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請從選單中選一個模型", resp.json()["error"])

    # -- POST /api/settings/budget（含邊界值） ------------------------------------

    def test_save_budget_valid(self):
        resp = self.client.post("/api/settings/budget", json={"intake_budget": 45})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            coresettings.get_intake_budget_limit(web.conn, org_id=coredb.DEV_ORG_ID), 45.0)

    def test_save_budget_zero_is_rejected(self):
        """0 是下限邊界：契約假資料拿它當展示值，但送出寫入仍要擋（沿用既有『大於 0』規則，
        不因為改成 JSON 就放寬）。"""
        resp = self.client.post("/api/settings/budget", json={"intake_budget": 0})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("花費上限請填大於 0 的數字", resp.json()["error"])

    # -- POST /api/settings/creative-root ------------------------------------------

    @unittest.skipUnless(os.name == "nt", "驗證邏輯用平台原生 pathlib.Path 判斷是否為絕對路徑"
                          "（保留現存的 test_creative_assets.py 用真實 tmpdir 路徑做跨平台驗證），"
                          "這條硬寫死 Windows 磁碟機代號字串，只在 Windows 上才是絕對路徑")
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
            coresettings.get_setting(
                web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, org_id=coredb.DEV_ORG_ID),
            "一律平面實填")

    # -- 測試連線：假供應商，不打真網路 ------------------------------------------------

    def test_ai_test_connection_without_key_warns(self):
        resp = self.client.post("/api/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "warn")
        self.assertIn("尚未設定金鑰", body["message"])

    def test_ai_test_connection_success_uses_fake_provider(self):
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        fake = providers.FakeProvider()
        with mock.patch.object(providers, "AnthropicProvider", return_value=fake):
            resp = self.client.post("/api/settings/test-connection")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["kind"], "ok")
        self.assertIn("金鑰有效", body["message"])
        self.assertEqual(len(fake.calls), 1)

    # -- 票 T4 A4：HTML 表單路由與 GET /settings 頁面已刪除（React /settings 頁只打
    # /api/settings/*），下面補回從 test_settings_page.py 搬過來、原本只在舊頁面測過的
    # 業務行為缺口。金鑰優先序／清除不動環境變數本身已由 test_settings.py 的
    # SettingsTest.test_api_key_priority／test_clear_api_key_from_db 覆蓋（app.core.settings
    # 底層），這裡只補 _masked_key／API 回應層還沒測過的部分。

    def test_get_settings_reports_env_source_and_masks_env_key(self):
        """環境變數優先於 DB 且來源誠實回報；env 金鑰本身也要遮罩，不能原樣外流
        （原 test_settings_page.py::test_env_key_takes_priority_and_page_says_so）。"""
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        os.environ["ANTHROPIC_API_KEY"] = "env-only-value-not-shown"
        try:
            body = self.client.get("/api/settings").json()["data"]
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertEqual(body["api_key_source"], "env")
        self.assertTrue(body["db_key_present"])  # DB 仍有舊金鑰，清除路徑仍該可用
        self.assertEqual(body["masked_key"], "…hown")  # 遮罩後只露末四碼
        self.assertNotIn("env-only-value-not-shown", str(body))

    # -- 票 04-1a：AI 月費上限（組織每月，D4-2／D4-3）------------------------------

    def test_ai_monthly_cost_limit_owner_can_save(self):
        resp = self.client.post(
            "/api/settings/ai-monthly-cost-limit", json={"ai_monthly_cost_limit": 350})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            self.client.get("/api/settings").json()["data"]["ai_monthly_cost_limit"], 350)

    def test_ai_monthly_cost_limit_rejects_non_positive(self):
        resp = self.client.post(
            "/api/settings/ai-monthly-cost-limit", json={"ai_monthly_cost_limit": 0})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("大於 0", resp.json()["error"])

    def test_ai_monthly_cost_limit_requires_owner(self):
        """比照 test_identity_orgs.py::test_rename_requires_owner 同一套：member 角色不能
        調整這個上限——這是操作者的錢包保護閥，不是品牌層設定。"""
        member_id = uuid4()
        member_token = mint_hs256(
            sub=str(member_id), email=f"member-{member_id.hex[:8]}@example.com")
        identity_repo.create_user(web.conn, member_id, f"member-{member_id.hex[:8]}@example.com")
        identity_repo.create_membership(web.conn, coredb.DEV_ORG_ID, member_id, "member")
        web.conn.commit()
        resp = self.client.post(
            "/api/settings/ai-monthly-cost-limit",
            json={"ai_monthly_cost_limit": 999},
            headers={"Authorization": f"Bearer {member_token}", "X-Org-Id": coredb.DEV_ORG_ID},
        )
        self.assertEqual(resp.status_code, 403)

    def test_ai_key_source_own_tier_reports_advisory_cap(self):
        """'own' 層（票 04-1a D4-3）：cap_applies 變 False，api_key_source 誠實回報實體
        存放位置＝'db'（該層刻意不看環境變數，見 resolve_ai_credentials() 說明）。"""
        coresettings.set_setting(
            web.conn, coresettings.AI_KEY_SOURCE_SETTING, "own", org_id=coredb.DEV_ORG_ID)
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        os.environ["ANTHROPIC_API_KEY"] = "operator-env-key-should-not-leak-to-own-tier"
        try:
            body = self.client.get("/api/settings").json()["data"]
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        self.assertEqual(body["ai_key_source"], "own")
        self.assertFalse(body["ai_cap_applies"])
        self.assertEqual(body["api_key_source"], "db")
        self.assertEqual(
            coresettings.get_api_key(web.conn, org_id=coredb.DEV_ORG_ID), TEST_KEY)

    def test_ai_test_connection_failure_returns_danger_kind(self):
        """金鑰錯誤：danger kind + 人話訊息原樣透出（原 test_test_connection_key_error_shows_human_message）。"""
        coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, TEST_KEY, org_id=coredb.DEV_ORG_ID)
        fake = providers.FakeProvider(exception=providers.ProviderError("金鑰錯誤：測試訊息。"))
        with mock.patch.object(providers, "AnthropicProvider", return_value=fake):
            resp = self.client.post("/api/settings/test-connection")
        body = resp.json()
        self.assertEqual(body["kind"], "danger")
        self.assertIn("金鑰錯誤", body["message"])

    def test_save_prompt_header_can_be_saved_empty(self):
        """留白代表整組複製時不加開頭那一行，不是輸入錯誤（原
        test_prompt_header_can_be_saved_empty）。"""
        coresettings.set_setting(web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, "舊的開頭", org_id=coredb.DEV_ORG_ID)
        resp = self.client.post("/api/settings/prompt-header", json={"prompt_header": "  "})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            coresettings.get_setting(
                web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, org_id=coredb.DEV_ORG_ID), "")

    def test_save_budget_non_numeric_and_negative_rejected(self):
        """0 之外的無效輸入（非數字／負數）也要擋（原 test_budget_validation_and_save）。"""
        for bad in ("abc", -5):
            resp = self.client.post("/api/settings/budget", json={"intake_budget": bad})
            self.assertEqual(resp.status_code, 400, bad)
            self.assertIn("花費上限請填大於 0 的數字", resp.json()["error"])

    def test_json_body_not_a_dict_gives_human_error(self):
        resp = self.client.post("/api/settings/model", content=b"[1,2,3]",
                                headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不是合法的 JSON", resp.json()["error"])

    # -- AnthropicProvider／pricing 直接單元測試，不經 HTTP 路由（原本住在
    # test_settings_page.py，跟 Jinja 設定頁沒有關係，票 T4 A4 刪頁面時原樣搬過來；
    # 留在本 class 裡才吃得到 setUp 對 ANTHROPIC_API_KEY 的環境變數隔離）。

    def test_provider_without_key_raises_human_error(self):
        """AnthropicProvider 在缺金鑰時於發出請求前就拋人話錯誤，不碰網路。"""
        with self.assertRaises(providers.ProviderError) as cm:
            providers.AnthropicProvider().complete(
                model="claude-opus-5", system=None,
                messages=[{"role": "user", "content": "hi"}], max_tokens=1,
                org_id=coredb.DEV_ORG_ID,
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
                    org_id=coredb.DEV_ORG_ID,
                )
        message = str(cm.exception)
        self.assertIn("金鑰錯誤", message)
        for jargon in ("request_id", "invalid x-api-key", "401", "{"):
            self.assertNotIn(jargon, message)

    def test_pricing_covers_all_menu_models(self):
        for model_id, _name in main.MODEL_CHOICES:
            self.assertGreater(pricing.calculate_cost(model_id, 1000, 1000), 0)


if __name__ == "__main__":
    unittest.main()
