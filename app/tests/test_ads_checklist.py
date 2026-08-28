"""app/tests/test_ads_checklist.py — 生成管線票 10（GitHub issue #20）：投放前檢查清單、
交接包擴充（CBO/ABO、轉換事件、歸因視窗、貼文協同）、Pixel 教學頁。

重點：
1. 一次性（品牌層）項目跨檔期共用同一列，通過即存；出現「花錢零轉換」異常訊號時重新標示。
2. 每期必看項目各自一列，不繼承上一期狀態。
3. 兩類都不擋流程——沒勾完，交接包、判讀該走的路照走。
4. 交接包顯示 CBO/ABO 底案、轉換事件、歸因視窗、貼文協同指引、檢查清單完成度。
5. 判讀完成後，還有沒勾的清單項目會回頭提醒。
"""

import atexit
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_checklist_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import (
    checklist,  # noqa: E402
    reading,  # noqa: E402
)
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

ZERO_CONVERSION_CSV = (
    "報告開始,花費金額,曝光次數,連結點擊次數,購買次數\n"
    "2026-08-01,5000,10000,200,0\n"
)
GOOD_CSV = (
    "報告開始,花費金額,曝光次數,連結點擊次數,購買次數,購買轉換價值\n"
    "2026-08-01,10000,20000,400,10,80000\n"
)

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}
_PLAN_OPTIONS = {"options": [
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
]}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")




class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def _live_cycle(self, start_offset_days=-10):
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        cycle_id = resp.json()["cycle_id"]
        start = (date.today() + timedelta(days=start_offset_days)).isoformat()
        end = (date.today() + timedelta(days=start_offset_days + 13)).isoformat()
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'LIVE', start_date = %s, end_date = %s"
            " WHERE id = %s", (start, end, cycle_id))
        main.conn.commit()
        return cycle_id


class OneTimeItemTest(_Base):
    def test_defaults_to_unchecked(self):
        items = checklist.one_time_status(main.conn, self.bid)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["checked"])

    def test_checking_persists_and_records_actor(self):
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        items = checklist.one_time_status(main.conn, self.bid)
        self.assertTrue(items[0]["checked"])
        self.assertEqual(items[0]["checked_by"], ACTOR)

    def test_carries_over_across_cycles(self):
        """一次性項目通過即存：開了新檔期，勾選狀態還在。"""
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        self._live_cycle()
        self._live_cycle(start_offset_days=-20)
        items = checklist.one_time_status(main.conn, self.bid)
        self.assertTrue(items[0]["checked"])

    def test_rejects_unknown_item_key(self):
        with self.assertRaises(ValueError):
            checklist.set_one_time(main.conn, self.bid, "not_a_real_item", True, ACTOR)

    def test_zero_conversion_spend_flags_the_checked_item(self):
        """異常訊號：已勾選過，但最新一期花了錢卻零轉換——重新標示提醒，不是靜靜過關。"""
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        cycle_id = self._live_cycle(start_offset_days=-4)
        ads_performance.import_csv(main.conn, self.bid, cycle_id, ZERO_CONVERSION_CSV, actor=ACTOR)

        items = checklist.one_time_status(main.conn, self.bid)
        self.assertTrue(items[0]["flagged"])
        self.assertIn("轉換掛零", items[0]["flagged_reason"])

    def test_unchecked_item_is_not_flagged_even_with_anomaly(self):
        """沒勾過的項目本來就顯示「還沒確認」，不需要疊加異常旗標製造混淆。"""
        cycle_id = self._live_cycle(start_offset_days=-4)
        ads_performance.import_csv(main.conn, self.bid, cycle_id, ZERO_CONVERSION_CSV, actor=ACTOR)
        items = checklist.one_time_status(main.conn, self.bid)
        self.assertFalse(items[0]["checked"])
        self.assertFalse(items[0]["flagged"])

    def test_no_anomaly_when_conversions_present(self):
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        cycle_id = self._live_cycle(start_offset_days=-4)
        ads_performance.import_csv(main.conn, self.bid, cycle_id, GOOD_CSV, actor=ACTOR)
        items = checklist.one_time_status(main.conn, self.bid)
        self.assertFalse(items[0]["flagged"])


class CycleItemTest(_Base):
    def test_defaults_to_unchecked_per_cycle(self):
        cycle_id = self._live_cycle()
        items = checklist.cycle_status(main.conn, self.bid, cycle_id)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(not i["checked"] for i in items))

    def test_does_not_carry_over_to_a_new_cycle(self):
        cycle_a = self._live_cycle()
        checklist.set_cycle_item(main.conn, self.bid, cycle_a, "landing_page_consistent",
                                 True, ACTOR)
        cycle_b = self._live_cycle(start_offset_days=-20)
        items_b = checklist.cycle_status(main.conn, self.bid, cycle_b)
        self.assertFalse(next(i for i in items_b if i["key"] == "landing_page_consistent")["checked"])

        items_a = checklist.cycle_status(main.conn, self.bid, cycle_a)
        self.assertTrue(next(i for i in items_a if i["key"] == "landing_page_consistent")["checked"])

    def test_red_flag_hint_reflects_finding_count(self):
        cycle_id = self._live_cycle()
        main.conn.execute(
            "INSERT INTO finding (id, org_id, brand_id, campaign_cycle_id, finding_type,"
            " target_type, target_id, severity, code, message, confidence_penalty, source,"
            " resolved, created_at)"
            " VALUES ('fnd_test', %s, %s, %s, 'compliance', 'variant', 'cvr_x', 'warn',"
            " 'banned_word', '命中「療效」', 0, 'rule_scan', false, '2026-08-01T00:00:00Z')",
            (main.coredb.DEV_ORG_ID, self.bid, cycle_id))
        main.conn.commit()
        items = checklist.cycle_status(main.conn, self.bid, cycle_id)
        hint = next(i for i in items if i["key"] == "red_flag_scan_reviewed")["hint"]
        self.assertIn("1 處", hint)

    def test_rejects_unknown_item_key(self):
        cycle_id = self._live_cycle()
        with self.assertRaises(ValueError):
            checklist.set_cycle_item(main.conn, self.bid, cycle_id, "not_real", True, ACTOR)


class CompletenessTest(_Base):
    def test_counts_both_categories(self):
        cycle_id = self._live_cycle()
        result = checklist.completeness(main.conn, self.bid, cycle_id)
        self.assertEqual(result["total"], 4)  # 1 一次性 + 3 每期必看
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["pct"], 0)
        self.assertEqual(len(result["unchecked_labels"]), 4)

    def test_pct_updates_as_items_are_checked(self):
        cycle_id = self._live_cycle()
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        checklist.set_cycle_item(main.conn, self.bid, cycle_id, "landing_page_consistent",
                                 True, ACTOR)
        result = checklist.completeness(main.conn, self.bid, cycle_id)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["pct"], 50)


class RoutesDoNotBlockTest(_Base):
    """驗收：兩類清單都不擋流程——沒勾完，其他頁面與動作照常可用。"""

    def test_checklist_page_renders(self):
        cycle_id = self._live_cycle()
        resp = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}/checklist")
        self.assertEqual(resp.status_code, 200)
        labels = [i["label"] for i in resp.json()["data"]]
        self.assertIn("Pixel 已安裝並確認轉換事件正常觸發", labels)
        self.assertIn("到達頁的訊息跟這期廣告一致", labels)

    def test_toggle_one_time_item_via_route(self):
        cycle_id = self._live_cycle()
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/checklist/one-time/pixel_confirmed")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(checklist.one_time_status(main.conn, self.bid)[0]["checked"])

        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/checklist/one-time/pixel_confirmed")
        self.assertFalse(checklist.one_time_status(main.conn, self.bid)[0]["checked"])

    def test_toggle_cycle_item_via_route(self):
        cycle_id = self._live_cycle()
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/checklist/cycle/budget_matches_structure")
        self.assertEqual(resp.status_code, 204)
        items = checklist.cycle_status(main.conn, self.bid, cycle_id)
        self.assertTrue(next(i for i in items if i["key"] == "budget_matches_structure")["checked"])

    def test_unfinished_checklist_does_not_block_performance_page(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        ads_performance.import_csv(main.conn, self.bid, cycle_id, GOOD_CSV, actor=ACTOR)
        resp = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}/performance")
        self.assertEqual(resp.status_code, 200)


class _BaseHandoffTest(_Base):
    """比照 test_ads_handoff.py 的走法，走到有交接包可看的狀態。"""

    def setUp(self):
        super().setUp()
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")
        cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchone()["id"]

        # 票 02-repoint-creative-readers：素材資料源改主題表，不再經 LLM 生成管線
        # （generate() 仍寫 creative_variant，但已沒有任何讀取路徑會看它），直接建一顆
        # 已採用主題，內容比照原本假回覆的那則 hook。
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id, experiment_cell_id=cell_id,
            format_key="text_focus", name="早上第一杯主題", folder_code="H1N0", actor=ACTOR,
            components=[
                {"component_type": "title", "content": "每天第一杯，別再將就",
                 "fingerprint_json": {"angle": "pain", "tone": "blunt",
                                      "format": "text_focus", "selling_point": "quality"}},
            ],
        )
        theme_repo.adopt_theme(main.conn, self.bid, theme["id"], actor=ACTOR)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/build")

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan


class HandoffExtrasTest(_BaseHandoffTest):
    def test_extras_include_structure_conversion_event_and_attribution(self):
        extras = ads_handoff.build_extras(main.conn, self.bid, self.cycle_id)
        self.assertIn("structure", extras)
        self.assertTrue(extras["structure"].groups)
        self.assertIn("購買", extras["conversion_event"])
        self.assertIn("7 天", extras["attribution_window_setting"])
        self.assertIn("使用現有貼文", extras["post_coop_note"])
        self.assertEqual(extras["checklist"]["total"], 4)

    def test_completeness_reflects_checked_items(self):
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        extras = ads_handoff.build_extras(main.conn, self.bid, self.cycle_id)
        self.assertEqual(extras["checklist"]["checked"], 1)
        self.assertEqual(extras["checklist"]["total"], 4)


class QaLaunchReminderTest(_Base):
    """上線授權頁 QA 五項提醒（票 01，決策 0016）：品牌層級、提醒不擋流程。"""

    def test_fresh_brand_all_five_unconfirmed(self):
        items = checklist.qa_launch_status(main.conn, self.bid)
        self.assertEqual(len(items), 5)
        self.assertTrue(all(not i["checked"] for i in items))

    def test_confirming_one_item_persists_and_records_actor_without_affecting_others(self):
        checklist.set_qa_launch_item(main.conn, self.bid, "qa_pixel_installed", True, ACTOR)
        items = checklist.qa_launch_status(main.conn, self.bid)
        pixel_item = next(i for i in items if i["key"] == "qa_pixel_installed")
        self.assertTrue(pixel_item["checked"])
        self.assertEqual(pixel_item["checked_by"], ACTOR)
        others = [i for i in items if i["key"] != "qa_pixel_installed"]
        self.assertTrue(all(not i["checked"] for i in others))

    def test_confirmed_item_carries_over_to_a_new_cycle(self):
        """票上的驗收：同品牌下次上線授權時已確認項目不再顯示警示——品牌層持久化，不是逐檔期。"""
        checklist.set_qa_launch_item(main.conn, self.bid, "qa_budget_line_review", True, ACTOR)
        self._live_cycle()
        self._live_cycle(start_offset_days=-20)
        item = next(i for i in checklist.qa_launch_status(main.conn, self.bid)
                    if i["key"] == "qa_budget_line_review")
        self.assertTrue(item["checked"])

    def test_summary_unconfirmed_count_updates(self):
        summary = checklist.qa_launch_summary(main.conn, self.bid)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["unconfirmed"], 5)
        checklist.set_qa_launch_item(main.conn, self.bid, "qa_pixel_installed", True, ACTOR)
        summary = checklist.qa_launch_summary(main.conn, self.bid)
        self.assertEqual(summary["unconfirmed"], 4)

    def test_rejects_unknown_item_key(self):
        with self.assertRaises(ValueError):
            checklist.set_qa_launch_item(main.conn, self.bid, "not_a_real_item", True, ACTOR)


class QaLaunchHandoffPageTest(_BaseHandoffTest):
    def test_confirm_one_item_via_route_updates_count(self):
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/qa-launch/qa_pixel_installed")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(checklist.qa_launch_summary(main.conn, self.bid)["unconfirmed"], 4)

    def test_confirming_all_five_shows_success_banner(self):
        for key in checklist.QA_LAUNCH_ITEMS:
            resp = self.client.post(
                f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/qa-launch/{key}")
            self.assertEqual(resp.status_code, 204)
        self.assertEqual(checklist.qa_launch_summary(main.conn, self.bid)["unconfirmed"], 0)

    def test_activation_succeeds_regardless_of_qa_confirmation_state(self):
        """票上的驗收：授權上線按鈕的可點擊性完全不受檢查清單狀態影響——這裡故意一項都不勾。"""
        package_id = ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)[0]["id"]
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/{package_id}/activate",
            json={"meta_campaign_id": "23851234567890123"})
        self.assertEqual(resp.status_code, 204)
        mapping = ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)[0]["mapping"]
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["meta_campaign_id"], "23851234567890123")


class QaLaunchSettingsHubTest(_BaseHandoffTest):
    """票 02-qa-reminder-reset（決策 0016 第三節）：設定中心「廣告層面」分類的「上線前
    提醒」小節——確認過的項目在這裡可以重新打開，清掉確認紀錄，上線授權頁恢復顯示警示。"""

    def test_reopen_in_settings_clears_confirmation_and_handoff_shows_warning_again(self):
        """票上的驗收：確認過的項目在設定中心重新打開後，上線授權頁恢復顯示警示。"""
        checklist.set_qa_launch_item(main.conn, self.bid, "qa_pixel_installed", True, ACTOR)
        self.assertEqual(checklist.qa_launch_summary(main.conn, self.bid)["unconfirmed"], 4)

        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/qa-launch/qa_pixel_installed")
        self.assertEqual(resp.status_code, 204)

        item = next(i for i in checklist.qa_launch_status(main.conn, self.bid)
                   if i["key"] == "qa_pixel_installed")
        self.assertFalse(item["checked"])

        self.assertEqual(checklist.qa_launch_summary(main.conn, self.bid)["unconfirmed"], 5)

    def test_confirming_via_settings_updates_handoff_unconfirmed_count(self):
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/qa-launch/qa_budget_line_review")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(checklist.qa_launch_summary(main.conn, self.bid)["unconfirmed"], 4)

    def test_unknown_item_key_does_not_change_any_item(self):
        before = checklist.qa_launch_status(main.conn, self.bid)
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/qa-launch/not_a_real_item")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(checklist.qa_launch_status(main.conn, self.bid), before)


class ReadingRetroReminderTest(_BaseHandoffTest):
    def test_unchecked_items_are_flagged_after_judging(self):
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertIsNotNone(resp.json()["data"]["reading"])
        unchecked = checklist.completeness(main.conn, self.bid, self.cycle_id)["unchecked_labels"]
        self.assertIn("Pixel 已安裝並確認轉換事件正常觸發", unchecked)

    def test_no_reminder_once_everything_is_checked(self):
        for item in checklist.ONE_TIME_ITEMS:
            checklist.set_one_time(main.conn, self.bid, item, True, ACTOR)
        for item in checklist.CYCLE_ITEMS:
            checklist.set_cycle_item(main.conn, self.bid, self.cycle_id, item, True, ACTOR)
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertIsNotNone(resp.json()["data"]["reading"])
        self.assertEqual(
            checklist.completeness(main.conn, self.bid, self.cycle_id)["unchecked_labels"], [])

    def test_no_reminder_before_judging_even_if_unchecked(self):
        """成效判讀「回溯」提醒——還沒判讀過就不該冒出這句提示。"""
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertIsNone(resp.json()["data"]["reading"])
        self.assertTrue(
            checklist.completeness(main.conn, self.bid, self.cycle_id)["unchecked_labels"])


if __name__ == "__main__":
    unittest.main()
