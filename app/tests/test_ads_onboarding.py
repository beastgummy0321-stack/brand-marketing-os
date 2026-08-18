# -*- coding: utf-8 -*-
"""app/tests/test_ads_onboarding.py — 廣告分支票 15：校準期、提醒卡、差異視圖。

ADHD 設計輸入方向三的驗收：第一期先講明預期、投放後不沉默、第二期起不再重看全部設定。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_onb_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import onboarding  # noqa: E402
from app.ads import performance as ads_perf  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402



def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class _BaseOnboardingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _open(self, amount="10000", objective="sales", mode="real"):
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": amount, "objective": objective,
                                      "mode": mode},
                                follow_redirects=False)
        return resp.headers["location"].split("/ads/")[1].split("?")[0]


class CalibrationTest(_BaseOnboardingTest):
    def test_first_real_cycle_is_a_calibration_cycle(self):
        cycle_id = self._open()
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"],
                         "calibration")

    def test_second_cycle_is_a_normal_one(self):
        self._open()
        second = self._open()
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, second)["phase"], "normal")

    def test_simulation_does_not_consume_the_calibration_slot(self):
        """模擬期不算真的跑過——第一期真檔期還是要當校準期。"""
        self.client.post(f"/brands/{self.bid}/ads/new",
                         data={"custom_amount": "5000", "objective": "sales",
                               "mode": "simulation"}, follow_redirects=False)
        real = self._open()
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, real)["phase"], "calibration")

    def test_forecast_gives_a_range_not_a_single_number(self):
        cycle_id = self._open(amount="20000")
        forecast = onboarding.calibration_forecast(main.conn, self.bid, cycle_id)
        self.assertIsNotNone(forecast)
        self.assertLess(forecast["clicks_low"], forecast["clicks_high"])
        self.assertLessEqual(forecast["conversions_low"], forecast["conversions_high"])
        self.assertIn("產業通例值", forecast["basis_note"])

    def test_no_forecast_for_a_normal_cycle(self):
        self._open()
        second = self._open()
        self.assertIsNone(onboarding.calibration_forecast(main.conn, self.bid, second))

    def test_page_says_the_first_cycle_is_for_calibration(self):
        cycle_id = self._open()
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn("先講清楚這期大概會是什麼樣", page.text)
        self.assertIn("校準", page.text)
        self.assertIn("粗估範圍（未經校準）", page.text)

    def test_in_forecast_tells_whether_reality_matched_the_promise(self):
        forecast = {"conversions_low": 5, "conversions_high": 20,
                    "clicks_low": 0, "clicks_high": 0, "basis_note": ""}
        self.assertTrue(onboarding.in_forecast(forecast, {"conversions": 10}))
        self.assertFalse(onboarding.in_forecast(forecast, {"conversions": 1}))
        self.assertIsNone(onboarding.in_forecast(None, {"conversions": 10}))


class ReminderTest(_BaseOnboardingTest):
    def _live_cycle(self, start_offset_days=-10):
        cycle_id = self._open()
        start = (date.today() + timedelta(days=start_offset_days)).isoformat()
        end = (date.today() + timedelta(days=start_offset_days + 13)).isoformat()
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'LIVE', start_date = ?, end_date = ?"
            " WHERE id = ?", (start, end, cycle_id))
        main.conn.commit()
        onboarding.create_reminders(main.conn, self.bid, cycle_id)
        return cycle_id

    def test_four_reminders_are_created(self):
        """票 #38 新增第 4 筆 final_settlement（期末＋14 天最終結算）。"""
        cycle_id = self._live_cycle()
        rows = main.conn.execute(
            "SELECT kind FROM interrupt WHERE campaign_cycle_id = ? AND category = 'cycle_reminder'",
            (cycle_id,)).fetchall()
        self.assertEqual({r["kind"] for r in rows},
                         {"day3_look_dont_touch", "day7_report", "cycle_end", "final_settlement"})

    def test_creating_twice_does_not_duplicate(self):
        """同去重鍵二次排入只留一筆（決策 0026：assert 自檢）。"""
        cycle_id = self._live_cycle()
        onboarding.create_reminders(main.conn, self.bid, cycle_id)
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM interrupt WHERE campaign_cycle_id = ? AND category = 'cycle_reminder'",
            (cycle_id,)).fetchone()["c"]
        self.assertEqual(count, 4)

    def test_final_settlement_reminder_is_due_14_days_after_cycle_end(self):
        """票 #38：期末＋14 天才會浮出，治貨到付款棄單退款遲滯（決策 0025 判讀節奏第 5 點）。"""
        cycle_id = self._live_cycle(start_offset_days=-10)  # end_date = today - 10 + 13 = today+3
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        end = date.fromisoformat(cycle["end_date"])

        due_before = onboarding.due_reminders(
            main.conn, self.bid, today=(end + timedelta(days=13)).isoformat())
        self.assertNotIn("final_settlement", {d["kind"] for d in due_before})

        due_after = onboarding.due_reminders(
            main.conn, self.bid, today=(end + timedelta(days=14)).isoformat())
        self.assertIn("final_settlement", {d["kind"] for d in due_after})

    def test_final_settlement_action_url_goes_to_finalize_flow(self):
        cycle_id = self._live_cycle()
        row = main.conn.execute(
            "SELECT action_url FROM interrupt WHERE campaign_cycle_id = ? AND kind = 'final_settlement'",
            (cycle_id,)).fetchone()
        self.assertTrue(row["action_url"].endswith("/reading/progress?final=1"))

    def test_only_due_reminders_surface(self):
        """第 3 天的提醒不該在第 1 天就跳出來。"""
        self._live_cycle(start_offset_days=-1)
        due = onboarding.due_reminders(main.conn, self.bid)
        self.assertEqual(due, [])

    def test_day3_reminder_says_look_dont_touch(self):
        self._live_cycle(start_offset_days=-4)
        due = onboarding.due_reminders(main.conn, self.bid)
        kinds = [d["kind"] for d in due]
        self.assertIn("day3_look_dont_touch", kinds)
        message = [d["message"] for d in due if d["kind"] == "day3_look_dont_touch"][0]
        self.assertIn("先觀察、不調整設定", message)

    def test_dismissed_reminders_stay_dismissed(self):
        cycle_id = self._live_cycle(start_offset_days=-8)
        due = onboarding.due_reminders(main.conn, self.bid)
        self.assertTrue(due)
        resp = self.client.post(
            f"/brands/{self.bid}/ads/reminders/{due[0]['id']}/dismiss",
            follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        remaining = [d["id"] for d in onboarding.due_reminders(main.conn, self.bid)]
        self.assertNotIn(due[0]["id"], remaining)

    def test_reminders_appear_on_the_home_page_todo_list(self):
        self._live_cycle(start_offset_days=-8)
        page = self.client.get("/")
        self.assertIn("今天要處理的事", page.text)
        self.assertIn("虛構晨光咖啡", page.text)

    def test_closed_cycles_do_not_nag(self):
        cycle_id = self._live_cycle(start_offset_days=-20)
        main.conn.execute("UPDATE campaign_cycle SET status = 'CLOSED' WHERE id = ?",
                          (cycle_id,))
        main.conn.commit()
        self.assertEqual(onboarding.due_reminders(main.conn, self.bid), [])


class DiffViewTest(_BaseOnboardingTest):
    def test_no_diff_for_the_first_cycle(self):
        cycle_id = self._open()
        self.assertIsNone(onboarding.diff_with_previous(main.conn, self.bid, cycle_id))

    def test_shows_what_changed_and_folds_what_did_not(self):
        self._open(amount="10000", objective="sales")
        second = self._open(amount="12000", objective="sales")
        diff = onboarding.diff_with_previous(main.conn, self.bid, second)
        changed = {item["label"] for item in diff["changed"]}
        same = {item["label"] for item in diff["same"]}
        self.assertIn("總預算", changed)
        self.assertIn("本期目標", same)

    def test_identical_cycles_have_nothing_changed(self):
        self._open(amount="10000", objective="sales")
        second = self._open(amount="10000", objective="sales")
        self.assertEqual(onboarding.diff_with_previous(main.conn, self.bid, second)["changed"],
                         [])

    def test_simulation_is_not_used_as_the_comparison_baseline(self):
        """模擬期不是真的跑過，不該拿來當「上一期」比較。"""
        self.client.post(f"/brands/{self.bid}/ads/new",
                         data={"custom_amount": "5000", "objective": "sales",
                               "mode": "simulation"}, follow_redirects=False)
        real = self._open(amount="10000")
        self.assertIsNone(onboarding.diff_with_previous(main.conn, self.bid, real))

    def test_page_folds_the_unchanged_items(self):
        self._open(amount="10000", objective="sales")
        second = self._open(amount="12000", objective="sales")
        page = self.client.get(f"/brands/{self.bid}/ads/{second}")
        self.assertIn("跟上期比，這期改了什麼", page.text)
        self.assertIn("項與上期相同", page.text)


if __name__ == "__main__":
    unittest.main()


class BaselineCircularityTest(_BaseOnboardingTest):
    """截圖驗收抓到的 bug：基準不能包含當期，否則是循環論證。"""

    def test_first_cycle_forecast_admits_it_has_no_history(self):
        from app.ads import performance as perf
        from app.ads import reading

        cycle_id = self._open(amount="18000")
        perf.import_manual(main.conn, self.bid, cycle_id,
                           {"spend": 17400, "impressions": 142000, "clicks": 1980,
                            "conversions": 21, "revenue": 20790}, actor=ACTOR)
        perf.save_derived_metrics(main.conn, self.bid, cycle_id)

        forecast = onboarding.calibration_forecast(main.conn, self.bid, cycle_id)
        self.assertIn("產業通例值", forecast["basis_note"])
        self.assertEqual(reading.brand_baseline(main.conn, self.bid,
                                                exclude_cycle_id=cycle_id), {})

    def test_baseline_without_exclusion_would_include_the_current_cycle(self):
        """證明排除參數確實有作用（不傳就會把當期算進去）。"""
        from app.ads import performance as perf
        from app.ads import reading

        cycle_id = self._open(amount="18000")
        perf.import_manual(main.conn, self.bid, cycle_id, {"spend": 10000, "clicks": 500,
                                                           "impressions": 50000},
                           actor=ACTOR)
        perf.save_derived_metrics(main.conn, self.bid, cycle_id)
        self.assertTrue(reading.brand_baseline(main.conn, self.bid))
        self.assertEqual(reading.brand_baseline(main.conn, self.bid,
                                                exclude_cycle_id=cycle_id), {})


class ForecastSnapshotTest(_BaseOnboardingTest):
    """票 F1（決策 0039 第 14 條）：開期當下把校準區間寫死存快照，對帳只讀快照不重算。"""

    def test_calibration_cycle_stores_a_forecast_snapshot(self):
        cycle_id = self._open(amount="20000")
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        forecast = ads_repo.derived_plan(cycle).get("forecast")
        self.assertIsNotNone(forecast)
        for key in ("clicks_low", "clicks_high", "conversions_low", "conversions_high",
                    "basis_note"):
            self.assertIn(key, forecast)

    def test_normal_cycle_does_not_store_a_forecast_and_does_not_error(self):
        self._open()
        second = self._open()  # 第二期＝normal，非校準期
        cycle = ads_repo.get_cycle(main.conn, self.bid, second)
        self.assertNotIn("forecast", ads_repo.derived_plan(cycle))

    def test_forecast_snapshot_helper_reads_the_stored_value(self):
        cycle_id = self._open(amount="20000")
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        snapshot = onboarding.forecast_snapshot(cycle)
        self.assertIsNotNone(snapshot)
        self.assertLess(snapshot["clicks_low"], snapshot["clicks_high"])

    def test_forecast_snapshot_helper_is_none_when_nothing_was_stored(self):
        self._open()
        second = self._open()
        cycle = ads_repo.get_cycle(main.conn, self.bid, second)
        self.assertIsNone(onboarding.forecast_snapshot(cycle))

    def test_page_reads_the_snapshot_not_a_live_recalculation(self):
        """顯示值＝快照值：竄改快照成跟即時重算不同的值，頁面要顯示竄改後的快照，
        證明沒有事後重算（rubric②）。"""
        cycle_id = self._open(amount="20000")
        live = onboarding.calibration_forecast(main.conn, self.bid, cycle_id)
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        plan = ads_repo.derived_plan(cycle)
        plan["forecast"] = {**live, "clicks_low": live["clicks_low"] + 999,
                            "clicks_high": live["clicks_high"] + 1999}
        main.conn.execute("UPDATE campaign_cycle SET derived_plan_json = ? WHERE id = ?",
                          (json.dumps(plan, ensure_ascii=False), cycle_id))
        main.conn.commit()

        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn("{:,}".format(live["clicks_low"] + 999), page.text)

    def test_legacy_cycle_without_a_snapshot_honestly_admits_it(self):
        """本票上線前開的校準期沒存過快照：老實顯示「本期未存預告」，不補算（rubric③）。"""
        cycle_id = self._open(amount="20000")
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        plan = ads_repo.derived_plan(cycle)
        plan.pop("forecast", None)
        main.conn.execute("UPDATE campaign_cycle SET derived_plan_json = ? WHERE id = ?",
                          (json.dumps(plan, ensure_ascii=False), cycle_id))
        main.conn.commit()

        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn("先講清楚這期大概會是什麼樣", page.text)  # 校準期卡片仍出現
        self.assertIn("本期未存預告", page.text)


class ForecastGapTest(unittest.TestCase):
    """票 F5（決策 0039 第 16 條）：區間外時機械式拆解是哪一環拖累，程式算不猜（rubric④）。"""

    FORECAST = {"clicks_low": 1000, "clicks_high": 2000,
                "conversions_low": 20, "conversions_high": 60, "basis_note": ""}

    def test_within_range(self):
        gap = onboarding.forecast_gap(self.FORECAST, {"clicks": 1500, "conversions": 30})
        self.assertEqual(gap, {"direction": "within", "segment": None})

    def test_above_range_is_a_conservative_forecast_not_a_miss(self):
        gap = onboarding.forecast_gap(self.FORECAST, {"clicks": 3000, "conversions": 100})
        self.assertEqual(gap, {"direction": "above", "segment": None})

    def test_below_range_blames_clicks_when_clicks_also_fell_short(self):
        gap = onboarding.forecast_gap(self.FORECAST, {"clicks": 500, "conversions": 5})
        self.assertEqual(gap, {"direction": "below", "segment": "clicks"})

    def test_below_range_blames_conversion_rate_when_clicks_were_on_target(self):
        """點擊量落在區間內，成交筆數卻不夠——拖累的是轉換率不是點擊量。"""
        gap = onboarding.forecast_gap(self.FORECAST, {"clicks": 1500, "conversions": 5})
        self.assertEqual(gap, {"direction": "below", "segment": "conversion_rate"})


class PredictionSettlementTest(_BaseOnboardingTest):
    """票 F5（決策 0039 第 13–16 條）：兌現預言卡兩個出口——判讀頁①塊判讀結論卡內
    （`/performance`）、第二期檔期內頁頂部常駐卡（`/ads/{cycle_id}`）。"""

    def _judge(self, cycle_id, *, clicks, conversions, spend=20000):
        orig = ads_reading.PROVIDER
        ads_reading.PROVIDER = FakeProvider(response=_fake('{"text": "判讀說明"}'))
        try:
            ads_perf.import_manual(
                main.conn, self.bid, cycle_id,
                {"spend": spend, "impressions": max(clicks, 1) * 10,
                 "clicks": clicks, "conversions": conversions}, actor=ACTOR)
            ok, err = ads_reading.run(main.conn, self.bid, cycle_id, ACTOR)
            self.assertTrue(ok, err)
        finally:
            ads_reading.PROVIDER = orig

    def test_within_range_renders_on_both_outlets(self):
        first = self._open(amount="20000")
        forecast = onboarding.calibration_forecast(main.conn, self.bid, first)
        mid_clicks = (forecast["clicks_low"] + forecast["clicks_high"]) // 2
        mid_conversions = (forecast["conversions_low"] + forecast["conversions_high"]) // 2
        self._judge(first, clicks=mid_clicks, conversions=mid_conversions)

        reading_page = self.client.get(f"/brands/{self.bid}/ads/{first}/performance")
        self.assertIn("兌現預言", reading_page.text)
        self.assertIn("落在預告範圍內", reading_page.text)

        second = self._open(amount="20000")
        cycle_page = self.client.get(f"/brands/{self.bid}/ads/{second}")
        self.assertIn("上期預告兌現了嗎", cycle_page.text)
        self.assertIn("兌現了：落在預告範圍內", cycle_page.text)

    def test_above_range_is_labeled_conservative_forecast(self):
        first = self._open(amount="20000")
        forecast = onboarding.calibration_forecast(main.conn, self.bid, first)
        self._judge(first, clicks=forecast["clicks_high"] * 3,
                   conversions=forecast["conversions_high"] + 50)
        second = self._open(amount="20000")
        page = self.client.get(f"/brands/{self.bid}/ads/{second}")
        self.assertIn("超標達成：預測偏保守", page.text)

    def test_below_range_shows_the_three_part_narrative(self):
        """承認→拆解→下期已用自身數據（決策 0039 第 16 條②）。"""
        first = self._open(amount="20000")
        self._judge(first, clicks=1, conversions=0)
        second = self._open(amount="20000")
        page = self.client.get(f"/brands/{self.bid}/ads/{second}")
        self.assertIn("沒兌現：實際低於預告下限", page.text)
        detail_body = page.text[page.text.index("上期預告兌現了嗎"):]
        self.assertIn("實際成交比預告的下限還少", detail_body)
        self.assertIn("每次點擊的成本比預期高", detail_body)  # 這組資料點擊量也不足，歸咎 CPC
        self.assertIn("下一期的預估基準已經改用這個品牌自己的實際數據", detail_body)

    def test_third_cycle_has_no_settlement_card(self):
        """上期無快照就不出卡，不補算（rubric②）：第三期的上一期是第二期（normal，
        沒存過快照），不會跨過去拿第一期（校準期）的快照。"""
        first = self._open(amount="20000")
        self._judge(first, clicks=1500, conversions=30)
        self._open(amount="20000")
        third = self._open(amount="20000")
        page = self.client.get(f"/brands/{self.bid}/ads/{third}")
        self.assertNotIn("上期預告兌現了嗎", page.text)

    def test_unjudged_calibration_cycle_has_no_settlement_on_reading_page(self):
        """有快照但還沒判讀過（一筆成效資料都沒有）：出口(a)不出卡，不拿零筆資料充數。"""
        cycle_id = self._open(amount="20000")
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}/performance")
        self.assertNotIn("兌現預言", page.text)
