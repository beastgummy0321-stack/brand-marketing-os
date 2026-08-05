# -*- coding: utf-8 -*-
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
import os
import shutil
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_checklist_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import checklist  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

main.reopen_connection()


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


def _wait_progress(client, url, timeout=5.0):
    """票 M3：進度頁改背景執行緒後，?run=1 不再同步等完；短輪詢模擬瀏覽器 meta refresh，
    等到真的轉址（303）或逾時為止（FakeProvider 幾乎瞬間完成，正常情況幾毫秒內就會轉址）。"""
    deadline = time.time() + timeout
    resp = client.get(url, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, follow_redirects=False)
    return resp


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _live_cycle(self, start_offset_days=-10):
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        start = (date.today() + timedelta(days=start_offset_days)).isoformat()
        end = (date.today() + timedelta(days=start_offset_days + 13)).isoformat()
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'LIVE', start_date = ?, end_date = ?"
            " WHERE id = ?", (start, end, cycle_id))
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
            "INSERT INTO finding (id, brand_id, campaign_cycle_id, finding_type, target_type,"
            " target_id, severity, code, message, confidence_penalty, source, resolved, created_at)"
            " VALUES ('fnd_test', ?, ?, 'compliance', 'variant', 'cvr_x', 'warn', 'banned_word',"
            " '命中「療效」', 0, 'rule_scan', 0, '2026-08-01T00:00:00Z')",
            (self.bid, cycle_id))
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
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/checklist")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Pixel 已安裝並確認轉換事件正常觸發", page.text)
        self.assertIn("到達頁的訊息跟這期廣告一致", page.text)

    def test_toggle_one_time_item_via_route(self):
        cycle_id = self._live_cycle()
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{cycle_id}/checklist/one-time/pixel_confirmed",
            data={"checked": "1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(checklist.one_time_status(main.conn, self.bid)[0]["checked"])

        resp = self.client.post(
            f"/brands/{self.bid}/ads/{cycle_id}/checklist/one-time/pixel_confirmed",
            data={"checked": "0"}, follow_redirects=False)
        self.assertFalse(checklist.one_time_status(main.conn, self.bid)[0]["checked"])

    def test_toggle_cycle_item_via_route(self):
        cycle_id = self._live_cycle()
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{cycle_id}/checklist/cycle/budget_matches_structure",
            data={"checked": "1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        items = checklist.cycle_status(main.conn, self.bid, cycle_id)
        self.assertTrue(next(i for i in items if i["key"] == "budget_matches_structure")["checked"])

    def test_unfinished_checklist_does_not_block_performance_page(self):
        cycle_id = self._live_cycle(start_offset_days=-4)
        ads_performance.import_csv(main.conn, self.bid, cycle_id, GOOD_CSV, actor=ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/performance")
        self.assertEqual(page.status_code, 200)


class PixelGuidePageTest(_Base):
    def test_page_links_to_official_docs(self):
        page = self.client.get(f"/brands/{self.bid}/ads/pixel-guide")
        self.assertEqual(page.status_code, 200)
        self.assertIn("help.shopify.com", page.text)
        self.assertIn("easystore.co", page.text)
        self.assertIn("cyberbiz.io", page.text)

    def test_checklist_page_links_to_guide(self):
        cycle_id = self._live_cycle()
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/checklist")
        self.assertIn(f"/brands/{self.bid}/ads/pixel-guide", page.text)


class _BaseHandoffTest(_Base):
    """比照 test_ads_handoff.py 的走法，走到有交接包可看的狀態。"""

    def setUp(self):
        super().setUp()
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

        self._orig_plan, self._orig_creative = ads_plan.PROVIDER, ads_creative.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]
        reply = json.dumps({"variants": [
            {"cell_id": cell_id, "variant_type": "hook", "content": "每天第一杯，別再將就",
             "rationale": "", "creative_angle_number": 16, "on_camera": False,
             "cut_type": "pain_visualized", "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt", "format": "text_focus",
                             "selling_point": "quality"}},
        ]}, ensure_ascii=False)
        ads_creative.PROVIDER = FakeProvider(response=_fake(reply))
        _wait_progress(self.client,
                       f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                         follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff/build",
                         follow_redirects=False)

    def tearDown(self):
        ads_plan.PROVIDER, ads_creative.PROVIDER = self._orig_plan, self._orig_creative


class HandoffExtrasTest(_BaseHandoffTest):
    def test_extras_include_structure_conversion_event_and_attribution(self):
        extras = ads_handoff.build_extras(main.conn, self.bid, self.cycle_id)
        self.assertIn("structure", extras)
        self.assertTrue(extras["structure"].groups)
        self.assertIn("購買", extras["conversion_event"])
        self.assertIn("7 天", extras["attribution_window_setting"])
        self.assertIn("使用現有貼文", extras["post_coop_note"])
        self.assertEqual(extras["checklist"]["total"], 4)

    def test_handoff_page_shows_extras(self):
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff")
        self.assertEqual(page.status_code, 200)
        self.assertIn("帳戶結構怎麼開", page.text)
        self.assertIn("轉換事件", page.text)
        self.assertIn("歸因視窗", page.text)
        self.assertIn("使用現有貼文", page.text)
        self.assertIn("投放前檢查清單完成度", page.text)

    def test_completeness_reflects_checked_items(self):
        checklist.set_one_time(main.conn, self.bid, "pixel_confirmed", True, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/handoff")
        self.assertIn("1 / 4", page.text)


class ReadingRetroReminderTest(_BaseHandoffTest):
    def test_unchecked_items_are_flagged_after_judging(self):
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("投放前檢查清單還有沒勾的項目", page.text)
        self.assertIn("Pixel 已安裝並確認轉換事件正常觸發", page.text)

    def test_no_reminder_once_everything_is_checked(self):
        for item in checklist.ONE_TIME_ITEMS:
            checklist.set_one_time(main.conn, self.bid, item, True, ACTOR)
        for item in checklist.CYCLE_ITEMS:
            checklist.set_cycle_item(main.conn, self.bid, self.cycle_id, item, True, ACTOR)
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertNotIn("投放前檢查清單還有沒勾的項目", page.text)

    def test_no_reminder_before_judging_even_if_unchecked(self):
        """成效判讀「回溯」提醒——還沒判讀過就不該冒出這句提示。"""
        ads_performance.import_csv(main.conn, self.bid, self.cycle_id, GOOD_CSV, actor=ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertNotIn("投放前檢查清單還有沒勾的項目", page.text)


if __name__ == "__main__":
    unittest.main()
