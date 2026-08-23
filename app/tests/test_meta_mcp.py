# -*- coding: utf-8 -*-
"""app/tests/test_meta_mcp.py — 票 M1-01：Meta 官方 Ads MCP 一鍵建（暫停）＋發布。

一律用假 MCP client（monkeypatch `meta_mcp._client`／`meta_mcp._upload_image`），不發任何
真實網路請求——真連線驗收由使用者手做（票面「怎麼算過」第 3 點）。品牌名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_meta_mcp_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import meta_mcp  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402

ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}
_PLAN_OPTIONS = {
    "options": [
        {
            "is_recommended": True, "summary": "測試打法", "audience": _AUDIENCE,
            "angles": [{"title": "早上第一杯", "message": "訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
        {
            "is_recommended": False, "summary": "備用方案", "audience": _AUDIENCE,
            "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
    ]
}

ACCOUNT_ID = "368741390000000"
PAGE_ID = "page_test_123"

_ACCOUNTS_OK = {"ad_accounts": [{
    "ad_account_id": ACCOUNT_ID, "ad_account_name": "測試廣告帳號", "business_id": "",
    "business_name": "", "is_ads_mcp_enabled": True, "is_ads_mcp_disabled_reason": None,
    "account_status": "1", "is_queryable": True, "not_queryable_reason": None,
    "has_payment_method": True, "currency": "TWD", "min_daily_budget_cents": 100,
}], "next_cursor": None}

_PAGES_OK = {"pages": [{"page_id": PAGE_ID, "page_name": "測試粉專", "leadgen_tos_accepted": True}]}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class _FakeClient:
    """假 MCP client：依工具名回固定成功結果，可覆寫或指定某個工具拋例外。
    每次呼叫都記錄下來，供測試驗證有沒有打到、打了幾次。"""

    def __init__(self, *, fail_on: str = None, exc: Exception = None,
                overrides: dict = None, fail_once_on: str = None):
        self.calls = []
        self.fail_on = fail_on
        self.fail_once_on = fail_once_on  # 只讓這個工具「第一次」被呼叫時失敗，之後正常
        self._fail_once_triggered = False
        self.exc = exc or RuntimeError("mock Meta 連線失敗")
        self.overrides = overrides or {}
        self._seq = {"campaign": 0, "adset": 0, "creative": 0, "ad": 0}

    def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        if self.fail_once_on and name == self.fail_once_on and not self._fail_once_triggered:
            self._fail_once_triggered = True
            raise self.exc
        if self.fail_on and name == self.fail_on:
            raise self.exc
        if name in self.overrides:
            value = self.overrides[name]
            return value(arguments) if callable(value) else value
        if name == "ads_get_ad_accounts":
            return _ACCOUNTS_OK
        if name == "ads_get_ad_account_pages":
            return _PAGES_OK
        if name == "ads_create_campaign":
            self._seq["campaign"] += 1
            return {"campaign_id": f"cmp_{self._seq['campaign']}", "status": "PAUSED"}
        if name == "ads_create_ad_set":
            self._seq["adset"] += 1
            return {"ad_set_id": f"adset_{self._seq['adset']}", "status": "PAUSED"}
        if name == "ads_create_creative":
            self._seq["creative"] += 1
            return {"creative_id": f"cre_{self._seq['creative']}", "account_id": ACCOUNT_ID}
        if name == "ads_create_ad":
            self._seq["ad"] += 1
            return {"ad_id": f"ad_{self._seq['ad']}", "status": "PAUSED"}
        if name == "ads_activate_entity":
            return {"result": json.dumps({"ad_account_id": ACCOUNT_ID, "entity_id": "x",
                                          "entity_type": "ad", "status": "ACTIVE",
                                          "success": True})}
        return {}


class _BaseMetaMcpTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")

        self._orig_env = {k: os.environ.get(k) for k in
                          ("META_MCP_TOKEN", "META_AD_ACCOUNT_ID", "META_PAGE_ID")}
        os.environ["META_MCP_TOKEN"] = "test-token"
        os.environ["META_AD_ACCOUNT_ID"] = ACCOUNT_ID
        os.environ["META_PAGE_ID"] = PAGE_ID

        self._orig_client = meta_mcp._client
        self._orig_upload = meta_mcp._upload_image
        self.fake_client = _FakeClient()
        meta_mcp._client = self.fake_client
        meta_mcp._upload_image = lambda account_id, image_path: "hash_" + image_path.name

        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（MCP 票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        # 交接包的到達網址來自品牌自有渠道的官網（handoff._default_destination）；
        # 沒登記官網時 destination_url 是空字串——真人實測發現的情境（票二：preflight
        # 擋這個），CreatePreflightTest 專門測那個情境，其餘測試都先登記好官網。
        bi_repo.create_channel(main.conn, self.bid, channel_type="website", name="官網",
                               identifier="https://example.test", actor=ACTOR)

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))

    def tearDown(self):
        meta_mcp._client = self._orig_client
        meta_mcp._upload_image = self._orig_upload
        ads_plan.PROVIDER = self._orig_plan
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _open_cycle(self) -> str:
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        cycle_id = resp.json()["cycle_id"]
        ok, err = ads_plan.generate_options(main.conn, self.bid, cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/plan/approve")
        return cycle_id

    def _cell_id(self, cycle_id: str) -> str:
        return main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (cycle_id,)).fetchone()["id"]

    def _adopt_theme(self, cycle_id: str, cell_id: str, *, angle: str, with_image: bool) -> dict:
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name=f"{angle}主題",
            folder_code=new_id("code")[-4:], actor=ACTOR,
            components=[
                {"component_type": "title", "content": f"{angle}主打句"},
                {"component_type": "body", "content": f"{angle}內文"},
                {"component_type": "image_prompt", "content": f"{angle}的畫面"},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)
        if with_image:
            folder = creative_assets.theme_dir(
                main.conn, self.bid, cycle_id, theme_engine.theme_folder_name(theme))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        return theme

    def _build_one_package(self, *, with_image: bool = True) -> tuple:
        """回傳 (cycle_id, package)：整條路徑準備好一份 ready 且尚無 mapping 的交接包。"""
        cycle_id = self._open_cycle()
        cell_id = self._cell_id(cycle_id)
        self._adopt_theme(cycle_id, cell_id, angle="早上第一杯", with_image=with_image)
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/build")
        package = ads_handoff.list_packages(main.conn, self.bid, cycle_id)[0]
        return cycle_id, package

    def _mapping_for(self, package_id: str):
        return main.conn.execute(
            "SELECT * FROM external_ad_mapping WHERE publishing_package_id = ?",
            (package_id,)).fetchone()

    def _cycle_status(self, cycle_id: str) -> str:
        return ads_repo.get_cycle(main.conn, self.bid, cycle_id)["status"]

    def _authorization_count(self, package_id: str) -> int:
        row = main.conn.execute(
            "SELECT COUNT(*) AS n FROM activation_authorization"
            " WHERE brand_id = ? AND scope_type = 'campaign_activation' AND scope_ref = ?",
            (self.bid, package_id)).fetchone()
        return row["n"]


class CreatePreflightTest(_BaseMetaMcpTest):
    def _remove_website_channel(self) -> None:
        for channel in bi_repo.list_channels(main.conn, self.bid):
            if channel["channel_type"] == "website":
                bi_repo.delete_channel(main.conn, self.bid, channel["id"], actor=ACTOR)

    def test_empty_destination_url_returns_reason_without_calling_client(self):
        """真人實測（brd_01M0NN73K30QW2QK2CR8F0DBG7／ccy_01M0NQZ006A9BFXFCKQGCHCXRB）：
        沒登記官網的品牌，status='ready' 的包 destination_url 是空字串，Meta 對圖片廣告
        缺 link_url 直接拒絕。preflight 要在打 Meta 之前擋下，不是等 Meta 拒絕才知道。
        （品牌真的沒有官網——欄位本身空、品牌自有渠道也補不到，兩邊都空才算擋下。）"""
        self._remove_website_channel()
        cycle_id, package = self._build_one_package()
        main.conn.execute("UPDATE publishing_package SET destination_url = '' WHERE id = ?",
                          (package["id"],))
        main.conn.commit()

        result = meta_mcp.create_package(main.conn, self.bid, cycle_id, package["id"],
                                         actor=ACTOR)
        self.assertFalse(result["ok"])
        self.assertIn("到達網址", result["reason"])
        self.assertEqual(self.fake_client.calls, [])
        self.assertIsNone(self._mapping_for(package["id"]))

    def test_stale_empty_destination_falls_back_to_website_channel_and_persists(self):
        """票追加：使用者先產交接包、後來才補登記官網——build_packages() 不會回頭幫已經
        產出的包補這一欄，欄位仍是舊的空字串，但品牌自有渠道已經有官網了。create_package()
        現場補算、成功時把解出來的網址寫回 publishing_package，交接頁才跟著顯示。"""
        cycle_id, package = self._build_one_package()
        main.conn.execute("UPDATE publishing_package SET destination_url = '' WHERE id = ?",
                          (package["id"],))
        main.conn.commit()

        result = meta_mcp.create_package(main.conn, self.bid, cycle_id, package["id"],
                                         actor=ACTOR)
        self.assertTrue(result["ok"], result)

        creative_calls = [c for c in self.fake_client.calls if c[0] == "ads_create_creative"]
        self.assertEqual(len(creative_calls), 1)
        expected_link = ("https://example.test?"
                         + ads_handoff.utm_query(json.loads(package["utm_json"] or "{}")))
        self.assertEqual(creative_calls[0][1]["link_url"], expected_link)

        row = main.conn.execute("SELECT destination_url FROM publishing_package WHERE id = ?",
                                (package["id"],)).fetchone()
        self.assertEqual(row["destination_url"], "https://example.test")


class CreatePackageTest(_BaseMetaMcpTest):
    def test_a_writes_mapping_with_four_ids_confirmed(self):
        cycle_id, package = self._build_one_package()
        result = meta_mcp.create_package(main.conn, self.bid, cycle_id, package["id"],
                                         actor=ACTOR)
        self.assertTrue(result["ok"], result)
        meta_ids = result["meta_ids"]
        self.assertEqual(meta_ids["meta_campaign_id"], "cmp_1")
        self.assertEqual(meta_ids["meta_adset_id"], "adset_1")
        self.assertEqual(meta_ids["meta_ad_id"], "ad_1")
        self.assertEqual(meta_ids["meta_creative_id"], "cre_1")

        mapping = self._mapping_for(package["id"])
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["claim_status"], "confirmed")
        self.assertEqual(mapping["meta_campaign_id"], "cmp_1")
        self.assertEqual(mapping["meta_adset_id"], "adset_1")
        self.assertEqual(mapping["meta_ad_id"], "ad_1")

        # ADR 0019 第 7 條：money moment 是發布，不是建立——Meta 端還暫停著，本系統
        # 也不該切 LIVE、不該建投放授權（那些留給 activate_cycle() 真的開啟成功後才做）。
        self.assertNotEqual(self._cycle_status(cycle_id), "LIVE")
        self.assertEqual(self._authorization_count(package["id"]), 0)
        self.assertEqual(mapping["meta_creative_id"], "cre_1")

    def test_b_missing_image_returns_reason_without_calling_client(self):
        cycle_id, package = self._build_one_package(with_image=False)
        result = meta_mcp.create_package(main.conn, self.bid, cycle_id, package["id"],
                                         actor=ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "這個主題還沒放圖")
        self.assertEqual(self.fake_client.calls, [])
        self.assertIsNone(self._mapping_for(package["id"]))

    def test_c_second_package_in_same_cycle_reuses_first_campaign(self):
        cycle_id = self._open_cycle()
        cell_1 = self._cell_id(cycle_id)
        self._adopt_theme(cycle_id, cell_1, angle="切角一", with_image=True)
        cell_2_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
            (cell_2_id, cycle_id, self.bid, "測試受眾", "切角二", now_iso()))
        main.conn.commit()
        self._adopt_theme(cycle_id, cell_2_id, angle="切角二", with_image=True)

        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/build")
        packages = ads_handoff.list_packages(main.conn, self.bid, cycle_id)
        self.assertEqual(len(packages), 2)

        first = meta_mcp.create_package(main.conn, self.bid, cycle_id, packages[0]["id"],
                                        actor=ACTOR)
        second = meta_mcp.create_package(main.conn, self.bid, cycle_id, packages[1]["id"],
                                         actor=ACTOR)
        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        self.assertEqual(first["meta_ids"]["meta_campaign_id"],
                         second["meta_ids"]["meta_campaign_id"])
        campaign_calls = [c for c in self.fake_client.calls if c[0] == "ads_create_campaign"]
        self.assertEqual(len(campaign_calls), 1)

    def test_d_client_exception_returns_not_ok_without_new_mapping_row(self):
        cycle_id, package = self._build_one_package()
        self.fake_client.fail_on = "ads_create_ad_set"
        result = meta_mcp.create_package(main.conn, self.bid, cycle_id, package["id"],
                                         actor=ACTOR)
        self.assertFalse(result["ok"])
        self.assertIn("reason", result)
        self.assertIsNone(self._mapping_for(package["id"]))


class CreateAllRouteTest(_BaseMetaMcpTest):
    def test_b_second_package_reuses_campaign_after_first_fails_at_creative(self):
        """真人實測發現的第二個問題：第一包 campaign 建成功、素材建失敗（缺到達網址那類
        錯誤）——這個結果從沒寫進 DB（authorize_and_map 沒被呼叫），第二包的
        `_ensure_campaign()` DB 查詢因此查不到，會另建一個 campaign。create-all 路由
        要把第一包（不論成功或失敗）帶出來的 campaign_id 接力傳給下一包。"""
        cycle_id = self._open_cycle()
        cell_1 = self._cell_id(cycle_id)
        self._adopt_theme(cycle_id, cell_1, angle="切角一", with_image=True)
        cell_2_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
            (cell_2_id, cycle_id, self.bid, "測試受眾", "切角二", now_iso()))
        main.conn.commit()
        self._adopt_theme(cycle_id, cell_2_id, angle="切角二", with_image=True)
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/build")
        packages = ads_handoff.list_packages(main.conn, self.bid, cycle_id)
        self.assertEqual(len(packages), 2)

        self.fake_client.fail_once_on = "ads_create_creative"
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/create-all")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(len(body["failed"]), 1)

        campaign_calls = [c for c in self.fake_client.calls if c[0] == "ads_create_campaign"]
        self.assertEqual(len(campaign_calls), 1)

        succeeded = ads_handoff.list_packages(main.conn, self.bid, cycle_id)
        mapped = [p for p in succeeded if p.get("mapping")]
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["mapping"]["meta_campaign_id"], "cmp_1")

    def test_e_create_all_skips_packages_that_already_have_mapping(self):
        cycle_id, ready_package = self._build_one_package()
        cell_2_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id,"
            " audience, creative_angle, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
            (cell_2_id, cycle_id, self.bid, "測試受眾", "已手填包", now_iso()))
        main.conn.commit()
        self._adopt_theme(cycle_id, cell_2_id, angle="已手填包", with_image=True)
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/build")

        packages = ads_handoff.list_packages(main.conn, self.bid, cycle_id)
        self.assertEqual(len(packages), 2)
        manually_filled = next(p for p in packages if p["id"] != ready_package["id"])
        self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/handoff/{manually_filled['id']}/activate",
            json={"meta_campaign_id": "手填_23851234567890123"})

        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/create-all")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["failed"], [])

        # 手填過的那包沒有被重新處理：adset/ad/creative 仍是手填當時的空值。
        manual_mapping = self._mapping_for(manually_filled["id"])
        self.assertEqual(manual_mapping["meta_campaign_id"], "手填_23851234567890123")
        self.assertIsNone(manual_mapping["meta_adset_id"])


class PublishAllRouteTest(_BaseMetaMcpTest):
    def test_f_publish_all_before_create_all_is_400(self):
        cycle_id, _package = self._build_one_package()
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/publish-all")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_publish_all_activates_after_create_all(self):
        cycle_id, package = self._build_one_package()
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/create-all")
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/publish-all")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["activated"], 1)
        self.assertEqual(body["failed"], [])
        activate_calls = [c for c in self.fake_client.calls if c[0] == "ads_activate_entity"]
        self.assertEqual(len(activate_calls), 3)  # campaign + ad_set + ad

        # 現在才是花錢那一刻（ADR 0019 第 7 條）：切 LIVE、每個真的開啟成功的包各一筆授權。
        self.assertEqual(self._cycle_status(cycle_id), "LIVE")
        self.assertEqual(self._authorization_count(package["id"]), 1)

    def test_publish_all_twice_does_not_duplicate_authorization(self):
        """連按兩次「發布全部」：第二次不再呼叫 Meta、不重複寫授權列。"""
        cycle_id, package = self._build_one_package()
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/create-all")
        self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/publish-all")
        n_calls = len(self.fake_client.calls)
        body = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/handoff/publish-all").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["activated"], 0)
        self.assertEqual(len(self.fake_client.calls), n_calls)
        self.assertEqual(self._authorization_count(package["id"]), 1)


if __name__ == "__main__":
    unittest.main()
