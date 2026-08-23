# -*- coding: utf-8 -*-
"""app/tests/test_ads_qa_autocheck.py — 票 Q1-01：上線前 QA 五項提醒改真的打 Meta 查。

一律用假 MCP client（monkeypatch `meta_mcp.call_tool`——`qa_autocheck.py` 只認這支公開
別名，不是 `meta_mcp._client`），不發任何真實網路請求；到達頁探測另外 monkeypatch
`qa_autocheck._probe_url`，同一個理由。品牌名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_qa_autocheck_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import meta_mcp  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import qa_autocheck  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
ACCOUNT_ID = "368741390000000"

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}
_PLAN_OPTIONS = {
    "options": [
        {"is_recommended": True, "summary": "測試打法", "audience": _AUDIENCE,
         "angles": [{"title": "早上第一杯", "message": "訊息", "why": "", "product_id": None}],
         "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
        {"is_recommended": False, "summary": "備用方案", "audience": _AUDIENCE,
         "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
         "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
    ]
}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


class _FakeCallTool:
    """假 `meta_mcp.call_tool`：依工具名回固定值或呼叫覆寫函式；可指定某工具直接拋例外，
    驗證「錯誤不穿牆」——每次呼叫都記錄下來，供測試驗證有沒有打到、打了幾次。"""

    def __init__(self):
        self.calls = []
        self.overrides: dict = {}
        self.fail_on: set = set()

    def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        if name in self.fail_on:
            raise meta_mcp.MetaMcpError(f"假裝 {name} 掛了")
        if name in self.overrides:
            value = self.overrides[name]
            return value(arguments) if callable(value) else value
        return {}


class _BaseQaAutoCheckTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._orig_account_env = os.environ.get("META_AD_ACCOUNT_ID")
        os.environ["META_AD_ACCOUNT_ID"] = ACCOUNT_ID

        self._orig_call_tool = meta_mcp.call_tool
        self.fake = _FakeCallTool()
        meta_mcp.call_tool = self.fake
        qa_autocheck._cache.clear()

        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（QA 票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        bi_repo.create_channel(main.conn, self.bid, channel_type="website", name="官網",
                               identifier="https://example.test", actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")
        cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="早上第一杯主題", folder_code="H1N0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": "每天第一杯，別再將就",
                 "fingerprint_json": {"angle": "pain", "tone": "blunt",
                                      "format": "text_focus", "selling_point": "quality"}},
                {"component_type": "body", "content": "三分鐘沖一杯好咖啡。",
                 "fingerprint_json": {"angle": "benefit", "tone": "warm",
                                      "format": "text_focus", "selling_point": "convenience"}},
                {"component_type": "image_prompt",
                 "content": "A warm morning desk with a pour-over set",
                 "fingerprint_json": {"angle": "scene", "tone": "warm",
                                      "format": "single_image", "selling_point": "quality"}},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)
        ads_handoff.build_packages(main.conn, self.bid, self.cycle_id, ACTOR)
        self.package = ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)[0]

    def tearDown(self):
        meta_mcp.call_tool = self._orig_call_tool
        ads_plan.PROVIDER = self._orig_plan
        qa_autocheck._cache.clear()
        if self._orig_account_env is None:
            os.environ.pop("META_AD_ACCOUNT_ID", None)
        else:
            os.environ["META_AD_ACCOUNT_ID"] = self._orig_account_env

    def _adset(self, **overrides) -> dict:
        base = {"id": "adset_1", "name": self.package["adset_name"], "campaign_id": "cmp_1",
               "daily_budget": f"NT${round(self.package['daily_budget']):,} TWD",
               "targeting": {"excluded_custom_audiences": ["cust_1"]}}
        base.update(overrides)
        return base

    def _entities_returning(self, adsets: list):
        """`ads_get_ad_entities` 一律回這批 adset（level=campaign 沒特別覆寫時回空陣列）。"""
        def _handler(args):
            if args.get("level") == "adset":
                return {"ad_entities": json.dumps(adsets)}
            return {"ad_entities": "[]"}
        return _handler

    def _results(self) -> list:
        return qa_autocheck.results(main.conn, self.bid, self.cycle_id)

    def _item(self, key: str) -> dict:
        return next(i for i in self._results() if i["key"] == key)


class PixelCheckTest(_BaseQaAutoCheckTest):
    def test_pass_when_active_dataset_fired_within_7_days(self):
        recent = (date.today() - timedelta(days=1)).isoformat() + "T09:00:00+0800"
        self.fake.overrides["ads_get_datasets"] = {"datasets": [
            {"dataset_id": "px1", "is_active": True, "last_fired_time": recent}]}
        item = self._item("qa_pixel_installed")
        self.assertTrue(item["available"])
        self.assertTrue(item["passed"])
        self.assertFalse(item["checked"])  # 決策 1：驗過就不用勾，checked 欄位維持原狀

    def test_fails_when_no_dataset_fired_within_7_days(self):
        stale = (date.today() - timedelta(days=30)).isoformat() + "T09:00:00+0800"
        self.fake.overrides["ads_get_datasets"] = {"datasets": [
            {"dataset_id": "px1", "is_active": True, "last_fired_time": stale}]}
        item = self._item("qa_pixel_installed")
        self.assertTrue(item["available"])
        self.assertFalse(item["passed"])

    def test_dedupes_duplicate_dataset_rows_taking_the_freshest(self):
        """票面 Gotcha：同一個 dataset_id 出現兩次，一筆是 epoch 0、一筆是真的最近時間——
        要取最新那筆，不能被排在前面的 epoch 0 蓋過去。"""
        recent = (date.today() - timedelta(days=1)).isoformat() + "T09:00:00+0800"
        self.fake.overrides["ads_get_datasets"] = {"datasets": [
            {"dataset_id": "px1", "is_active": True, "last_fired_time": "1969-12-31T16:00:00-0800"},
            {"dataset_id": "px1", "is_active": True, "last_fired_time": recent}]}
        item = self._item("qa_pixel_installed")
        self.assertTrue(item["passed"])

    def test_unavailable_when_datasets_read_fails(self):
        self.fake.fail_on.add("ads_get_datasets")
        item = self._item("qa_pixel_installed")
        self.assertFalse(item["available"])
        self.assertIsNone(item["passed"])


class AudienceExclusionCheckTest(_BaseQaAutoCheckTest):
    def test_pass_when_matched_adset_has_exclusions(self):
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([self._adset()])
        item = self._item("qa_audience_exclusion")
        self.assertTrue(item["available"])
        self.assertTrue(item["passed"])

    def test_fails_when_matched_adset_has_no_exclusions(self):
        adset = self._adset(targeting={"excluded_custom_audiences": []})
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([adset])
        item = self._item("qa_audience_exclusion")
        self.assertTrue(item["available"])
        self.assertFalse(item["passed"])
        self.assertIn(self.package["adset_name"], item["note"])

    def test_unavailable_when_no_adset_matches(self):
        adset = self._adset(name="跟這期套件完全對不上的名字")
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([adset])
        item = self._item("qa_audience_exclusion")
        self.assertFalse(item["available"])
        self.assertIsNone(item["passed"])


class EmqCheckTest(_BaseQaAutoCheckTest):
    def _with_active_dataset(self):
        self.fake.overrides["ads_get_datasets"] = {"datasets": [
            {"dataset_id": "px1", "is_active": True,
             "last_fired_time": date.today().isoformat() + "T09:00:00+0800"}]}

    def test_pass_when_any_event_has_composite_score(self):
        self._with_active_dataset()
        self.fake.overrides["ads_get_dataset_quality"] = {"web": [
            {"event_name": "Purchase", "event_match_quality": {"composite_score": 6.2}}]}
        item = self._item("qa_capi_emq_quality")
        self.assertTrue(item["available"])
        self.assertTrue(item["passed"])
        self.assertNotIn("6.2", item["note"])  # 決策 2：分數本身不印

    def test_fails_when_no_event_has_composite_score(self):
        self._with_active_dataset()
        self.fake.overrides["ads_get_dataset_quality"] = {"web": [
            {"event_name": "Purchase", "event_match_quality": {}}]}
        item = self._item("qa_capi_emq_quality")
        self.assertTrue(item["available"])
        self.assertFalse(item["passed"])

    def test_unavailable_when_quality_read_fails(self):
        self._with_active_dataset()
        self.fake.fail_on.add("ads_get_dataset_quality")
        item = self._item("qa_capi_emq_quality")
        self.assertFalse(item["available"])
        self.assertIsNone(item["passed"])


class BudgetCheckTest(_BaseQaAutoCheckTest):
    def test_pass_when_meta_budget_matches_baseline(self):
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([self._adset()])
        item = self._item("qa_budget_line_review")
        self.assertTrue(item["available"])
        self.assertTrue(item["passed"])

    def test_fails_when_meta_budget_differs_from_baseline(self):
        adset = self._adset(daily_budget="NT$999,999 TWD")
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([adset])
        item = self._item("qa_budget_line_review")
        self.assertTrue(item["available"])
        self.assertFalse(item["passed"])
        self.assertIn("999,999", item["note"])
        self.assertIn(self.package["adset_name"], item["note"])

    def test_falls_back_to_campaign_daily_budget_when_adset_has_none(self):
        """票面規則：廣告組沒有自己的日預算＝活動層 CBO 扛預算，要退回查活動的。"""
        adset = self._adset()
        del adset["daily_budget"]
        baseline = round(self.package["daily_budget"])

        def _handler(args):
            if args.get("level") == "adset":
                return {"ad_entities": json.dumps([adset])}
            self.assertEqual(args.get("level"), "campaign")
            return {"ad_entities": json.dumps([{"id": "cmp_1", "daily_budget": f"NT${baseline:,} TWD"}])}

        self.fake.overrides["ads_get_ad_entities"] = _handler
        item = self._item("qa_budget_line_review")
        self.assertTrue(item["passed"])


class LandingPageCheckTest(_BaseQaAutoCheckTest):
    def setUp(self):
        super().setUp()
        self._orig_probe = qa_autocheck._probe_url

    def tearDown(self):
        qa_autocheck._probe_url = self._orig_probe
        super().tearDown()

    def test_pass_when_all_urls_probe_ok(self):
        qa_autocheck._probe_url = lambda url: True
        item = self._item("qa_landing_page_click_test")
        self.assertTrue(item["available"])
        self.assertTrue(item["passed"])

    def test_fails_when_a_url_probe_fails(self):
        qa_autocheck._probe_url = lambda url: False
        item = self._item("qa_landing_page_click_test")
        self.assertTrue(item["available"])
        self.assertFalse(item["passed"])

    def test_unavailable_when_no_packages_yet(self):
        other = self.client.post(f"/api/campaigns/{self.bid}",
                                 json={"product_ids": [], "budget": 5000, "objective": "awareness"})
        other_cycle = other.json()["cycle_id"]
        item = next(i for i in qa_autocheck.results(main.conn, self.bid, other_cycle)
                   if i["key"] == "qa_landing_page_click_test")
        self.assertFalse(item["available"])


class CacheAndCheckedStateTest(_BaseQaAutoCheckTest):
    def test_results_are_cached_for_60_seconds(self):
        self.fake.overrides["ads_get_datasets"] = {"datasets": []}
        self._results()
        calls_after_first = len(self.fake.calls)
        self._results()
        self.assertEqual(len(self.fake.calls), calls_after_first,
                         "60 秒快取內第二次呼叫不該再打 Meta")

    def test_checked_reflects_manual_tick_even_when_cached(self):
        """`checked` 是使用者自行勾選狀態，不進 60 秒快取——即使 Meta 讀取結果被快取住，
        使用者按了勾選之後馬上要看得到最新狀態。"""
        from app.ads import checklist as ads_checklist
        self.fake.overrides["ads_get_datasets"] = {"datasets": []}
        self.assertFalse(self._item("qa_pixel_installed")["checked"])
        ads_checklist.set_qa_launch_item(main.conn, self.bid, "qa_pixel_installed", True, ACTOR)
        self.assertTrue(self._item("qa_pixel_installed")["checked"])


class ReadinessMergeTest(_BaseQaAutoCheckTest):
    def test_qa_launch_item_passes_when_system_verified_even_if_not_manually_checked(self):
        """票面「Scoring ring」：qa_launch 項目的 passed 改成
        `checked or (available and passed)`——系統驗過就算過，不用使用者另外勾。

        合併邏輯現在住在路由層（routes_campaigns_handoff_api.py:readiness()），不是
        `handoff.readiness_ring()`——後者維持原本「純聚合既有狀態，不重算判定邏輯」的
        docstring 契約，也因此不會反過來 import qa_autocheck（依賴方向只有
        qa_autocheck → handoff 一條，不繞回去）。這裡兩段都測：直呼 readiness_ring()
        證明它沒被動過，打 /readiness 路由證明合併後的結果真的變了。"""
        recent = date.today().isoformat() + "T09:00:00+0800"
        self.fake.overrides["ads_get_datasets"] = {"datasets": [
            {"dataset_id": "px1", "is_active": True, "last_fired_time": recent}]}
        self.fake.overrides["ads_get_ad_entities"] = self._entities_returning([self._adset()])
        self.fake.overrides["ads_get_dataset_quality"] = {"web": [
            {"event_name": "Purchase", "event_match_quality": {"composite_score": 6.2}}]}
        qa_autocheck._cache.clear()

        bare = ads_handoff.readiness_ring(main.conn, self.bid, self.cycle_id)
        bare_pixel = next(i for i in bare["items"] if i["key"] == "qa_pixel_installed")
        self.assertFalse(bare_pixel["passed"], "沒被合併過的 readiness_ring() 應該只看 checked")

        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/readiness")
        self.assertEqual(resp.status_code, 200)
        merged = resp.json()["data"]
        merged_pixel = next(i for i in merged["items"] if i["key"] == "qa_pixel_installed")
        self.assertTrue(merged_pixel["passed"])
        self.assertEqual(merged["passed"], sum(1 for i in merged["items"] if i["passed"]))


if __name__ == "__main__":
    unittest.main()
