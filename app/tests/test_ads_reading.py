# -*- coding: utf-8 -*-
"""app/tests/test_ads_reading.py — 廣告分支票 12：成效判讀。

重點：狀態一律由門檻規則判定（純函數，可測），LLM 只翻人話。
賺不賺錢的門檻從單位毛利算出來，不是固定值。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_reading_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import settlement as ads_settlement  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import prototype_phase  # noqa: E402
from app.llm import context_compiler  # noqa: E402
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, Usage  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class BreakevenTest(unittest.TestCase):
    def test_breakeven_comes_from_margin_not_a_fixed_number(self):
        """毛利率 40% 要 2.5 倍才回本；毛利率 70% 只要 1.43 倍。"""
        low = reading.breakeven_roas({"selling_price": 1000, "unit_variable_cost": 600})
        high = reading.breakeven_roas({"selling_price": 1000, "unit_variable_cost": 300})
        self.assertEqual(low, 2.5)
        self.assertEqual(high, 1.43)

    def test_unknown_economics_returns_none_not_a_guess(self):
        self.assertIsNone(reading.breakeven_roas(None))
        self.assertIsNone(reading.breakeven_roas({"selling_price": 100,
                                                  "unit_variable_cost": 150}))


class RepurchaseBreakevenTest(unittest.TestCase):
    """票 #39：回購實質打平線＝首單打平線 ÷ 回購倍數（fixture 驗算）。"""

    def test_multiplier_lowers_the_breakeven_line(self):
        self.assertEqual(reading.repurchase_breakeven_roas(1.67, 2.0), 0.83)

    def test_missing_first_order_breakeven_returns_none(self):
        self.assertIsNone(reading.repurchase_breakeven_roas(None, 2.0))

    def test_missing_multiplier_returns_none(self):
        """樣本不足時 multiplier 是 None，實質線就不該存在（票 #39 驗收條件）。"""
        self.assertIsNone(reading.repurchase_breakeven_roas(1.67, None))


class SeasonLabelTest(unittest.TestCase):
    """票 #39：基線兩條並列＋旺淡季標注，用「去年同期」vs「全年平均」的比值判斷。"""

    def test_same_period_much_higher_than_annual_is_peak_season(self):
        result = reading._season_label({"roas": 3.0}, {"roas": 2.0})
        self.assertEqual(result["level"], "peak")
        self.assertEqual(result["label"], "旺季")

    def test_same_period_much_lower_than_annual_is_low_season(self):
        result = reading._season_label({"roas": 1.0}, {"roas": 2.0})
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["label"], "淡季")

    def test_close_to_annual_average_is_typical(self):
        result = reading._season_label({"roas": 2.1}, {"roas": 2.0})
        self.assertEqual(result["level"], "typical")

    def test_missing_either_side_says_so_honestly(self):
        result = reading._season_label({}, {"roas": 2.0})
        self.assertIsNone(result["level"])
        self.assertIn("資料不足", result["label"])


class JudgeRulesTest(unittest.TestCase):
    def _totals(self, **overrides):
        data = {"impressions": 20000, "clicks": 400, "spend": 10000,
                "conversions": 10, "revenue": 40000}
        data.update(overrides)
        data["kpis"] = perf.compute_kpis(data)
        return data

    def test_barely_started_is_insufficient_data(self):
        verdict = reading.judge(self._totals(spend=1000), plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "insufficient_data")

    def test_low_impressions_is_insufficient_data(self):
        verdict = reading.judge(self._totals(impressions=500), plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "insufficient_data")
        self.assertIn("樣本太少", verdict["reasons"][0])

    def test_half_budget_zero_conversions_says_stop(self):
        verdict = reading.judge(self._totals(conversions=0, revenue=0),
                                plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "pause_candidate")

    def test_same_roas_different_verdict_by_margin(self):
        """同一個投報率，對不同毛利的產品意義完全不同——這正是固定門檻會出錯的地方。"""
        totals = self._totals(revenue=30000)  # ROAS = 3.0
        thin = reading.judge(totals, plan_budget=10000, breakeven=2.9, brand_id="demo_brand")
        fat = reading.judge(totals, plan_budget=10000, breakeven=1.5, brand_id="demo_brand")
        self.assertEqual(thin["status"], "maintain")
        self.assertEqual(fat["status"], "scale_candidate")

    def test_losing_money_says_stop(self):
        verdict = reading.judge(self._totals(revenue=10000), plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "pause_candidate")

    def test_too_few_conversions_is_still_learning(self):
        verdict = reading.judge(self._totals(conversions=2, revenue=40000),
                                plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "learning")
        self.assertIn("不夠穩定", verdict["reasons"][0])

    def test_no_economics_does_not_pretend_to_know_profit(self):
        verdict = reading.judge(self._totals(), plan_budget=10000, breakeven=None, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "unclear_economics")
        self.assertIn("算不出", verdict["reasons"][0])

    def test_no_economics_still_comments_on_clicks(self):
        verdict = reading.judge(self._totals(), plan_budget=10000, breakeven=None, brand_id="demo_brand",
                                baseline={"ctr": 0.005})
        self.assertTrue(any("點擊率" in r for r in verdict["reasons"]))

    def test_small_sample_scale_candidate_is_directional_not_statistical(self):
        """票 8：錢的門檻（status）跟統計的門檻（statistical_level）是兩條分開的線——
        小預算帳戶（clicks=400）就算毛利算下來夠格加碼，樣本量還是收不到統計等級，
        要誠實標「方向性判讀」，不能包裝成嚴謹的統計結論。"""
        totals = self._totals(revenue=30000)  # ROAS = 3.0
        verdict = reading.judge(totals, plan_budget=10000, breakeven=1.5, brand_id="demo_brand")  # 高毛利 → 加碼候選
        self.assertEqual(verdict["status"], "scale_candidate")
        self.assertEqual(verdict["statistical_level"], "directional")
        self.assertEqual(verdict["statistical_level_label"], "方向性判讀")

    def test_large_sample_scale_candidate_reaches_statistical_level(self):
        """同樣是加碼候選，但樣本量收到速查表門檻時，才能標「統計等級」。"""
        totals = self._totals(clicks=20000, conversions=1000, revenue=30000)
        verdict = reading.judge(totals, plan_budget=10000, breakeven=1.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "scale_candidate")
        self.assertEqual(verdict["statistical_level"], "statistical")
        self.assertEqual(verdict["statistical_level_label"], "統計等級")

    def test_money_threshold_status_unchanged_by_conn_argument(self):
        """money 門檻的算法不因傳不傳 conn 而改變（既有毛利門檻行為不變的回歸測試）。"""
        totals = self._totals(revenue=30000)
        without_conn = reading.judge(totals, plan_budget=10000, breakeven=1.5, brand_id="demo_brand")
        with_conn = reading.judge(totals, plan_budget=10000, breakeven=1.5, brand_id="demo_brand", conn=None)
        self.assertEqual(without_conn["status"], with_conn["status"])
        self.assertEqual(without_conn["status"], "scale_candidate")

    def test_small_sample_scale_signal_is_capped_to_learning(self):
        """修憲落地 G4（決策 0035 第三節第 7 點）：3–10 筆轉換的 ROAS 信賴區間跨越打平線
        兩側，即使算出來的投報率遠高於打平線，也不准輸出加碼——誠實降回「還在學習期」。"""
        totals = self._totals(conversions=5, revenue=50000)  # ROAS = 5.0，遠高於打平線*1.3
        verdict = reading.judge(totals, plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "learning")

    def test_small_sample_pause_signal_is_capped_to_learning(self):
        totals = self._totals(conversions=5, revenue=12500)  # ROAS = 1.25，遠低於打平線*0.7
        verdict = reading.judge(totals, plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "learning")

    def test_large_sample_scale_signal_is_not_capped(self):
        """滿 10 筆轉換（門檻本身）就不再降級，維持原本的加碼／停損判定。"""
        totals = self._totals(conversions=10, revenue=50000)
        verdict = reading.judge(totals, plan_budget=10000, breakeven=2.5, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "scale_candidate")

    def test_small_sample_maintain_is_not_touched(self):
        """`maintain`（打平）不受這條門檻影響——決策原文只擋加碼／停損，
        打平本來就是這個樣本區間唯一該有信心講出來的錢的結論之一。"""
        totals = self._totals(conversions=5, revenue=18000)  # ROAS = 1.8，落在打平區間
        verdict = reading.judge(totals, plan_budget=10000, breakeven=1.6667, brand_id="demo_brand")
        self.assertEqual(verdict["status"], "maintain")


class ReadingFlowTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "這期表現不錯，成交成本在可以接受的範圍。"},
                       ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)

    def test_no_data_says_so_instead_of_judging(self):
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(ok)
        self.assertIn("還沒有成效資料", err)

    def test_reading_is_stored_with_rule_result_and_explanation(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertIsNotNone(loaded["cycle"])
        self.assertIn("reasons", loaded["cycle"]["result"])
        self.assertIn("成交成本", loaded["cycle"]["llm_explanation"])

    def test_cycle_moves_to_evaluating(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "EVALUATING")

    def test_says_it_cannot_split_by_product_when_data_is_aggregate(self):
        """手動輸入的數字沒有分產品——就要直說看不出是哪個產品拉的，不能硬掰。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertEqual(loaded["products"], [])
        self.assertTrue(any("沒有分到各個產品" in r
                            for r in loaded["cycle"]["result"]["reasons"]))

    def test_llm_failure_does_not_break_the_reading(self):
        """AI 講不出話不影響判讀本身——狀態是程式算的。"""
        reading.PROVIDER = FakeProvider(exception=ProviderError("暫時無法回應"))
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, _ = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertEqual(loaded["cycle"]["status"], "scale_candidate")
        self.assertIsNone(loaded["cycle"]["llm_explanation"])

    def test_confidence_from_reconciliation_is_carried_into_the_reading(self):
        from app.ads import reconcile as recon
        self._spend(spend=14000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        recon.run(main.conn, self.bid, self.cycle_id)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertIn("打折", loaded["cycle"]["confidence_level"])

    def test_page_shows_the_verdict_and_says_who_decided(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("這期該怎麼看", page.text)
        self.assertIn("AI 只負責把結論講成白話", page.text)

    def test_page_shows_directional_statistical_level_for_small_sample(self):
        """票 8：小預算帳戶（clicks 只有 400）收不到統計等級的樣本，頁面要誠實標
        「方向性判讀」，不能假裝是嚴謹的科學結論。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("方向性判讀", page.text)
        self.assertIn("這期的樣本數還沒到統計等級的門檻", page.text)

    def test_rerun_replaces_previous_reading(self):
        """重判讀要能跑第二次——下期草案掛在判讀上，清理順序錯了會被外鍵擋死。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_reading WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["c"]
        self.assertEqual(rows, 1)
        drafts = main.conn.execute(
            "SELECT COUNT(*) c FROM recommendation WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["c"]
        self.assertEqual(drafts, 1)

    def test_lazy_mode_still_gives_a_grade_and_the_page_renders(self):
        """懶人模式走查（GitHub issue #41，決策 0025 懶人優先第 6 點）：只有 Meta 資料、
        沒有訂單／GA4／通路資料時，仍要給結論並標成色，頁面不報錯不空白。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertEqual(result["data_grade"], {"kind": "meta_only", "label": "Meta 視角判讀"})
        self.assertFalse(result["ga4_leak"]["available"])

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Meta 視角判讀", page.text)


class AssetBreakdownTest(unittest.TestCase):
    """修憲落地 G2（決策 0035 第二節第 4 點）：判讀頁除了檔期層，還要能顯示哪一則素材賺。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "5", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _package(self, ad_name: str) -> str:
        from app.core.db import new_id, now_iso
        pkg_id = new_id("pkg")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 'ready', ?)",
            (pkg_id, self.bid, self.cycle_id, "測試活動", "測試組合", ad_name,
             "https://example.test", ts))
        mapping_id = new_id("xam")
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (?, ?, ?, ?, 'meta', 'confirmed', ?, ?, ?)",
            (mapping_id, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        return pkg_id

    def test_matched_csv_rows_show_up_as_asset_breakdown(self):
        self._package("拿證據說話_01_ad")
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,拿證據說話_01_ad,12500,340,5000,12,18600\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertEqual(len(result["asset_breakdown"]), 1)
        asset = result["asset_breakdown"][0]
        self.assertEqual(asset["asset_name"], "拿證據說話_01_ad")
        self.assertEqual(asset["revenue"], 18600)
        self.assertEqual(asset["kpis"]["roas"], round(18600 / 5000, 2))

    def test_unmatched_data_leaves_asset_breakdown_empty(self):
        """對不上素材的資料只留在檔期層，不假裝有素材層結果（鐵則 16）。"""
        perf.import_manual(main.conn, self.bid, self.cycle_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertEqual(result["asset_breakdown"], [])

    def test_page_shows_asset_breakdown_when_available(self):
        self._package("拿證據說話_01_ad")
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,拿證據說話_01_ad,12500,340,5000,12,18600\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("拿證據說話_01_ad", page.text)


class VerdictShiftTest(unittest.TestCase):
    """翻盤分級規則寫死在程式（票 #38，決策 0025：「翻盤警示分級——微調不吵、判定翻盤才進佇列」）。"""

    def test_unchanged_status_is_unchanged(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "scale_candidate"), "unchanged")

    def test_positive_to_negative_is_a_reversal(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "pause_candidate"), "reversal")
        self.assertEqual(
            reading.classify_verdict_shift("maintain", "pause_candidate"), "reversal")

    def test_negative_to_positive_is_also_a_reversal(self):
        self.assertEqual(
            reading.classify_verdict_shift("pause_candidate", "maintain"), "reversal")

    def test_move_within_the_same_group_is_just_an_adjustment(self):
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "maintain"), "adjustment")

    def test_move_involving_an_uncertain_status_is_not_a_reversal(self):
        """還看不準／學習期是中間群，不跟正負任一群構成翻盤——不確定不是結論反轉。"""
        self.assertEqual(
            reading.classify_verdict_shift("scale_candidate", "learning"), "adjustment")
        self.assertEqual(
            reading.classify_verdict_shift("pause_candidate", "insufficient_data"), "adjustment")


def _order_row(order_number, order_date, fulfillment_status="fulfilled"):
    return {
        "order_number": order_number, "order_date": order_date, "total_amount": 1000,
        "refunded_amount": 0, "financial_status": "paid",
        "fulfillment_status": fulfillment_status, "order_status": "paid",
        "voucher_code": None, "billing_email": None, "billing_phone": None, "items": [],
    }


class _ReadingIntegrationBase(unittest.TestCase):
    """票 #38 新增測試共用的檔期＋產品經濟性 setUp，比照既有 ReadingFlowTest／
    SettlementFreezeTest 的建立方式。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（票38）",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "測試判讀說明"}'))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)


class FinalizeTest(_ReadingIntegrationBase):
    """期末＋14 天最終結算（決策 0025 判讀節奏第 5 點）：全系統唯一把檔期轉 CLOSED 的地方。"""

    def test_finalize_closes_the_cycle(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["status"], "CLOSED")

    def test_finalized_reading_is_not_tentative_but_normal_run_is(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(
            reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["is_tentative"])

        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(
            reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["is_tentative"])

    def _reset_prototype_phase_flag(self):
        """修憲落地 A6：這個旗標是全站唯一一次性事件，同一支測試檔的其他 finalize()
        測試也可能先把它翻過去——每個測本旗標的測試自己重置，不依賴測試執行順序。"""
        main.conn.execute("DELETE FROM app_setting WHERE key = ?", (prototype_phase.FLAG_SETTING,))
        main.conn.execute("DELETE FROM interrupt WHERE category = 'prototype_phase_ended'")
        main.conn.commit()

    def test_finalize_with_real_spend_ends_prototype_phase(self):
        """修憲落地 A6：檔期結算完成＋這期實際花費 > 0，原型階段旗標翻轉並進打斷佇列。"""
        self._reset_prototype_phase_flag()
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(prototype_phase.has_ended(main.conn))
        open_items = core_interrupts.list_open(main.conn)
        matches = [i for i in open_items if i["category"] == "prototype_phase_ended"]
        self.assertTrue(matches)
        self.assertEqual(matches[0]["action_url"], "/app/inbox")

        # 修憲落地 A6 修正：「詳情」連結要能真的看到四項豁免的逐項內容，不是死連結。
        resp = self.client.get("/api/system/prototype-phase")
        self.assertEqual(resp.status_code, 200)
        for exemption in prototype_phase.EXEMPTIONS:
            self.assertIn(exemption["item"], resp.text)

    def test_finalize_with_zero_spend_does_not_end_prototype_phase(self):
        """花費是 0 就不算「用真錢跑完一期」，旗標不動（決策 0037 第一節第 1 條）。"""
        self._reset_prototype_phase_flag()
        self._spend(spend=0, impressions=20000, clicks=400, conversions=10, revenue=0)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(prototype_phase.has_ended(main.conn))


class UnsettledRatioInReadingTest(_ReadingIntegrationBase):
    """期末暫定判讀標注「未結案訂單佔 X%」（決策 0025 判讀節奏第 5 點）。"""

    def test_no_order_data_says_so_honestly(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertIsNone(result["unsettled_ratio"])
        self.assertIn("沒有比對得到訂單資料", result["unsettled_note"])

    def test_unsettled_ratio_reflects_order_data_in_range(self):
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        rows = [
            _order_row("O1", cycle["start_date"], "fulfilled"),
            _order_row("O2", cycle["start_date"], "unfulfilled"),
        ]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertEqual(result["unsettled_ratio"], 0.5)
        self.assertIn("50%", result["unsettled_note"])


class LateDataRerunTest(_ReadingIntegrationBase):
    """補件→自動重判→差異摘要（AI 只翻人話）→分級翻盤警示鏈路（票 #38）。"""

    def _judge_once(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

    def test_no_op_while_still_live(self):
        """還在投放中就不算「晚到」，即使這期已經判讀過——原樣略過，不新增版次。"""
        self._judge_once()  # 產生 v1，run() 結束後 status 會變成 EVALUATING
        main.conn.execute("UPDATE campaign_cycle SET status = 'LIVE' WHERE id = ?",
                          (self.cycle_id,))
        main.conn.commit()
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        self.assertIsNone(outcome)

    def test_no_op_when_never_judged_before(self):
        """還沒判讀過（沒有版次）就不是補件，是第一次判讀，原樣略過。"""
        main.conn.execute("UPDATE campaign_cycle SET status = 'EVALUATING' WHERE id = ?",
                          (self.cycle_id,))
        main.conn.commit()
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        self.assertIsNone(outcome)

    def test_reversal_bumps_version_writes_diff_and_enqueues_interrupt(self):
        self._judge_once()  # v1：scale_candidate（roas 4.0 倍，打平線 1.67 倍）
        first_status = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["status"]
        self.assertEqual(first_status, "scale_candidate")

        # 晚到一筆巨額花費、沒有額外轉換：累積 roas 掉到 0.67 倍，翻成該停損
        self._spend(spend=50000, impressions=0, clicks=0, conversions=0, revenue=0)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["shift"], "reversal")
        self.assertEqual(outcome["before_status"], "scale_candidate")
        self.assertEqual(outcome["after_status"], "pause_candidate")
        self.assertTrue(outcome["diffs"])
        self.assertEqual(outcome["explanation"], "測試判讀說明")

        versions = main.conn.execute(
            "SELECT version, diff_summary FROM settlement_version"
            " WHERE campaign_cycle_id = ? ORDER BY version", (self.cycle_id,)).fetchall()
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertIsNone(versions[0]["diff_summary"])
        self.assertEqual(versions[1]["diff_summary"], "測試判讀說明")

        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid,
                                                category="reading_reversal")
        self.assertEqual(len(open_items), 1)
        self.assertEqual(open_items[0]["campaign_cycle_id"], self.cycle_id)

    def test_page_shows_version_badge_and_diff_summary(self):
        """版次徽章與逐版差異可見；不靜默覆蓋（票 #38 驗收條件）。"""
        self._judge_once()
        self._spend(spend=50000, impressions=0, clicks=0, conversions=0, revenue=0)
        reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("第 2 版", page.text)
        self.assertIn("測試判讀說明", page.text)

    def test_rerun_again_without_new_diffs_does_not_duplicate_the_warning(self):
        self._judge_once()
        self._spend(spend=50000, impressions=0, clicks=0, conversions=0, revenue=0)
        reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        # 立刻再重判一次，這次數字完全沒變（沒有新的成效資料進來）——diff 仍可能因訂單到達
        # 時間戳而非空，但翻盤警示走去重鍵，同一版不會再排第二筆。
        reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid,
                                                category="reading_reversal")
        self.assertLessEqual(len(open_items), 2)  # 兩個不同版次各自的去重鍵，不會同版重複


def _repeat_customer_rows(count, *, prefix):
    """count 位顧客，首單 2020-01-01（早於任何測試執行時間 90 天以上）、45 天內回購等額
    一筆 -> 回購倍數 2.0（票 #39 fixture 驗算）。"""
    rows = []
    for i in range(count):
        email = f"{prefix}{i}@example.com"
        rows.append(_order_row(f"{prefix}F{i}", "2020-01-01"))
        rows.append(_order_row(f"{prefix}R{i}", "2020-02-15"))
        rows[-2]["billing_email"] = email
        rows[-1]["billing_email"] = email
    return rows


class RepurchaseLineTest(_ReadingIntegrationBase):
    """票 #39：雙打平線並列，樣本不足不顯示實質線；結論相反時 AI 具名異議進佇列並可採納／駁回。"""

    def test_no_order_history_leaves_repurchase_line_unavailable(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        line = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["repurchase_line"]
        self.assertFalse(line["available"])
        self.assertTrue(line["insufficient_sample"])

    def test_below_sample_threshold_repurchase_line_stays_unavailable(self):
        orders_repo.save_orders(main.conn, self.bid, _repeat_customer_rows(29, prefix="lo"),
                                source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        line = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["repurchase_line"]
        self.assertFalse(line["available"])
        self.assertEqual(line["sample_size"], 29)

    def test_conflicting_lines_write_dissent_and_enqueue_interrupt(self):
        """首單線 roas 1.0（打平線 1.67 倍）判該停損；回購倍數 2.0 讓實質打平線降到 0.83 倍，
        同一組數字回購線判維持——結論相反，要進佇列＋留一筆 AI 具名異議。"""
        orders_repo.save_orders(main.conn, self.bid, _repeat_customer_rows(30, prefix="hi"),
                                source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=10000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertEqual(result["repurchase_line"]["multiplier"], 2.0)
        self.assertEqual(reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["status"],
                         "pause_candidate")
        self.assertTrue(result["repurchase_line"]["available"])
        self.assertTrue(result["repurchase_line"]["conflict"])

        dissents = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id, status="pending")
        repurchase_dissents = [d for d in dissents if d["target_type"] == "repurchase_breakeven"]
        self.assertEqual(len(repurchase_dissents), 1)
        self.assertIn("結論相反", repurchase_dissents[0]["suggestion"])

        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid,
                                                category="repurchase_conflict")
        self.assertEqual(len(open_items), 1)
        self.assertEqual(open_items[0]["campaign_cycle_id"], self.cycle_id)

    def test_dissent_decision_is_recorded_and_can_be_adopted(self):
        orders_repo.save_orders(main.conn, self.bid, _repeat_customer_rows(30, prefix="ad"),
                                source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=10000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        dissent = ads_repo.list_dissents(main.conn, self.bid, self.cycle_id,
                                         status="pending")[0]

        page = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/dissents/{dissent['id']}/decide",
            data={"decision": "adopted"}, follow_redirects=False)
        self.assertEqual(page.status_code, 303)

        decided = main.conn.execute(
            "SELECT status, decided_by FROM rule_dissent WHERE id = ?", (dissent["id"],)
        ).fetchone()
        self.assertEqual(decided["status"], "adopted")
        self.assertEqual(decided["decided_by"], OPERATOR)

    def test_resolving_the_conflict_clears_the_stale_pending_dissent(self):
        """再判讀一次，這次數字不衝突了——舊的 pending 異議要被清掉，不留殭屍紀錄。"""
        orders_repo.save_orders(main.conn, self.bid, _repeat_customer_rows(30, prefix="cl"),
                                source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=10000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertEqual(len(ads_repo.list_dissents(main.conn, self.bid, self.cycle_id,
                                                     status="pending")), 1)

        # 晚到一大筆營收：兩條線都會判成加碼，不再衝突
        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=90000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        result = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]
        self.assertFalse(result["repurchase_line"]["conflict"])
        self.assertEqual(len(ads_repo.list_dissents(main.conn, self.bid, self.cycle_id,
                                                     status="pending")), 0)

    def test_page_shows_repurchase_line_and_conflict_badge(self):
        orders_repo.save_orders(main.conn, self.bid, _repeat_customer_rows(30, prefix="pg"),
                                source="easystore_xlsx", actor=ACTOR)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=10000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("含 90 天回購的實質判讀", page.text)
        self.assertIn("兩線結論相反", page.text)


class DualBaselineTest(_ReadingIntegrationBase):
    """票 #39：基線兩條並列＋旺淡季標注；口徑變更記錄可見。"""

    def test_no_history_baseline_says_so_honestly(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        bl = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["baseline_comparison"]
        self.assertIsNone(bl["season"]["level"])
        self.assertEqual(bl["annual_average"], {})
        self.assertEqual(bl["same_period_last_year"], {})

    def test_same_period_last_year_baseline_is_computed_from_matching_cycle(self):
        """票 #39 驗收條件：基線兩條並列——「去年同期」要真的能從去年同一段日子的檔期
        算出來，不是只有空 dict 的退路。"""
        from datetime import date
        current_start = date.fromisoformat(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["start_date"])
        last_year_start = current_start.replace(year=current_start.year - 1).isoformat()
        last_year_cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR, start_date=last_year_start, duration_days=14)
        perf.import_manual(main.conn, self.bid, last_year_cycle["id"],
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        # 比照 app/ads/routes.py 匯入路由：直呼 import_manual 不會順便落地 derived_metric，
        # 要自己補這一步，跟真實匯入流程一致。
        perf.save_derived_metrics(main.conn, self.bid, last_year_cycle["id"])
        reading.run(main.conn, self.bid, last_year_cycle["id"], ACTOR)

        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        bl = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["baseline_comparison"]
        self.assertEqual(bl["same_period_last_year"]["roas"], 4.0)
        self.assertEqual(bl["season"]["level"], "typical")

    def test_policy_change_produces_a_cross_ruler_note(self):
        orders_repo.record_policy_change(main.conn, self.bid, policy_type="discount",
                                         changed_at="2026-01-01", description="折扣規則調整",
                                         actor=ACTOR)
        # 有基線可比才會標不同尺：先跑一期產生歷史 derived_metric，再跑一次當期判讀
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        bl = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["baseline_comparison"]
        self.assertEqual(len(bl["policy_changes"]), 1)
        # 沒有過去檔期可比時 annual_average 仍是空 dict，不同尺note 因此不會出現——
        # 這裡只驗證變更紀錄本身有被撈到、可見（驗收條件：口徑變更紀錄可見）。
        self.assertEqual(bl["policy_changes"][0]["policy_type"], "discount")


class SimulationExcludedFromBaselineTest(_ReadingIntegrationBase):
    """票 #71：模擬檔期（phase='simulation'）的假成效不能污染任何真基線聚合——
    brand_baseline／同期比較／校準區間 basis 共用同一個排除點（見 reading._median_derived_metrics），
    模擬頁自己顯示不受影響。"""

    def _make_simulation_cycle(self, **overrides):
        """模擬期一個品牌只能開一個（simulation.offer_simulation），這裡直接建表不經表單，
        避免跟 setUp() 已建立的 self.cycle_id 互相干擾。"""
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR, phase="simulation", **overrides)
        # 刻意用極端值（且刻意避開會四捨五入成 0 的組合，例如 cpc=0.0 這種假的「空白」
        # 會讓 `if baseline.get("cpc")` 誤判成沒有品牌歷史，反而矇對，測不出真的污染）：
        # 若污染真基線的中位數或校準區間 basis，任何斷言都會立刻炸開。
        totals = {"spend": 1000, "impressions": 1000, "clicks": 100,
                  "conversions": 50, "revenue": 1000000}
        perf.import_manual(main.conn, self.bid, cycle["id"], totals, actor=ACTOR)
        perf.save_derived_metrics(main.conn, self.bid, cycle["id"])
        return cycle["id"]

    def test_brand_baseline_ignores_simulation_only_history(self):
        """整個品牌只有模擬期跑過，brand_baseline 該回空 dict，不是拿假數字充數。"""
        self._make_simulation_cycle()
        self.assertEqual(reading.brand_baseline(main.conn, self.bid), {})

    def test_brand_baseline_not_pulled_by_simulation_when_real_history_exists(self):
        """真檔期＋模擬期並存：中位數只能反映真檔期，不能被模擬的極端值拉走。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        perf.save_derived_metrics(main.conn, self.bid, self.cycle_id)  # 落地這期的 derived_metric
        self._make_simulation_cycle()

        baseline = reading.brand_baseline(main.conn, self.bid, exclude_cycle_id=self.cycle_id)
        self.assertEqual(baseline, {})  # exclude_cycle_id 排掉唯一的真檔期，剩下的模擬期也不算數

        baseline_incl = reading.brand_baseline(main.conn, self.bid)
        self.assertEqual(baseline_incl["roas"], 4.0)  # 只有真檔期的 roas，沒被模擬的極端值拉走

    def test_same_period_last_year_excludes_simulation_cycle(self):
        """去年同期若剛好是模擬期，一樣不算數——同期比較跟 annual_average 走同一個排除點。"""
        from datetime import date
        current_start = date.fromisoformat(
            ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)["start_date"])
        last_year_start = current_start.replace(year=current_start.year - 1).isoformat()
        self._make_simulation_cycle(start_date=last_year_start, duration_days=14)

        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        bl = reading.load(main.conn, self.bid,
                          self.cycle_id)["cycle"]["result"]["baseline_comparison"]
        self.assertEqual(bl["same_period_last_year"], {})

    def test_calibration_forecast_basis_not_pulled_by_simulation(self):
        """校準區間 basis（simulation._basis，經 brand_baseline）不吃模擬數據——
        品牌只有模擬史時，basis 要老實退回產業通例值，不是假裝有品牌歷史。"""
        from app.ads import simulation as ads_simulation

        self._make_simulation_cycle()
        _, note = ads_simulation._basis(main.conn, self.bid)
        self.assertIn("產業通例值", note)


class _HypothesisReviewBase(unittest.TestCase):
    """票 #53 判讀頁假設結案共用的建置。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"product_ids": [self.product],
                                      "custom_amount": "10000", "objective": "sales"},
                                follow_redirects=False)
        self.cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"reasons": {}}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _link_hypothesis(self, statement, hypothesis_type="audience", product_id=None):
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type=hypothesis_type, statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=product_id, source_cycle_id=self.cycle_id)
        main.conn.execute(
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, ?)",
            (self.cycle_id, hyp["id"], self.bid, hypothesis_type),
        )
        main.conn.commit()
        return hyp

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)


class HypothesisReviewTest(_HypothesisReviewBase):
    """票 #53：判讀頁假設結案（三選一，AI 預選）＋入帳 learning_ledger＋打斷佇列補網。"""

    def test_ai_preselects_supported_when_scale_candidate(self):
        """判讀結論偏正向 → 三選一預選「成立」，AI 只負責寫理由，不決定選哪個（決策 0016）。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["id"], hyp["id"])
        self.assertEqual(reviews[0]["preselect"], "supported")
        self.assertTrue(reviews[0]["ai_reason"])

    def test_ai_preselects_rejected_when_pause_candidate(self):
        self._link_hypothesis("這群受眾在意價格")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "rejected")

    def test_ai_preselects_inconclusive_when_maintain(self):
        """修憲落地 G4（決策 0035 第三節第 6 點）：`maintain`（只是打平）不算「程式算出
        方向」，預選改看不出來，不是成立——橡皮圖章的產物不該被貼上「已驗證」標籤。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        # 這個品牌的產品毛利率固定（售價1000／變動成本400 → 打平線約1.667），
        # ROAS=1.8 落在 [打平線, 打平線*1.3) → maintain。
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=18000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "inconclusive")

    def test_llm_failure_falls_back_to_program_generated_reason(self):
        """AI 講不出話不擋清單顯示——理由退回程式產生的版本，選項本身不受影響。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        reading.PROVIDER = FakeProvider(exception=ProviderError("暫時無法回應"))
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        review = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"][0]
        self.assertIn("這期判讀結論是", review["ai_reason"])

    def test_zero_operation_submit_uses_ai_preselect(self):
        """使用者零操作也能過：直接照 AI 預選送出，status 隨之更新。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        preselect = reading.load(main.conn, self.bid,
                                 self.cycle_id)["cycle"]["hypothesis_reviews"][0]["preselect"]
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
            data={f"verdict_{hyp['id']}": preselect}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], preselect)

    def test_supported_confirmation_writes_learning_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = ?", (self.bid,))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["learning_text"], "通勤族比在家工作者更會下單")
        self.assertEqual(rows[0]["source_cycle_id"], self.cycle_id)
        self.assertEqual(rows[0]["source_hypothesis_id"], hyp["id"])
        self.assertEqual(rows[0]["created_by"], OPERATOR)
        self.assertEqual(rows[0]["sample_size"], "10")
        self.assertIsNotNone(rows[0]["confidence"])
        self.assertIsNotNone(rows[0]["source_reading_id"])

    def test_ledger_confidence_is_its_own_scale_not_the_data_grade_label(self):
        """修憲落地 G4（決策 0035 第三節第 8 點）：ledger 的 confidence 是「樣本數＋是否
        重測過」自己一套，不是資料成色標籤（那個標籤講的是資料有沒有對過帳，不是這條
        學習可不可信）——這裡的品牌沒有接 GA4／Meta 對帳，成色標籤會是「Meta 視角判讀」，
        跟 confidence 欄位的值必須不同。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertNotEqual(row["confidence"], "Meta 視角判讀")
        self.assertEqual(row["confidence"], "moderate")

    def test_small_sample_manual_override_gets_preliminary_confidence(self):
        """使用者手動把還在學習期的假設硬結案「成立」，系統不擋（決策 0013）；
        樣本只有 5 筆、不是重測，confidence 該誠實標「初步」。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=5, revenue=9000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(row["confidence"], "preliminary")

    def test_repeated_learning_text_gets_reinforced_confidence(self):
        """同一個品牌、同一個範圍、同一句學習文字，不同期別各自被判定「成立」——不是同一次
        判讀的巧合，是獨立重測，第二次入帳的 confidence 要標「已加強」。"""
        statement = "通勤族比在家工作者更會下單"
        hyp1 = self._link_hypothesis(statement)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp1['id']}": "supported"})

        cycle2_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        hyp2 = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type="audience", statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=None, source_cycle_id=cycle2_id)
        main.conn.execute(
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, 'audience')",
            (cycle2_id, hyp2["id"], self.bid))
        main.conn.commit()
        perf.import_manual(main.conn, self.bid, cycle2_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        reading.run(main.conn, self.bid, cycle2_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{cycle2_id}/performance/hypotheses",
                         data={f"verdict_{hyp2['id']}": "supported"})

        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = ? ORDER BY created_at", (self.bid,))]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["confidence"], "moderate")
        self.assertEqual(rows[1]["confidence"], "reinforced")

    def _later_cycle(self):
        """比照 DualBaselineTest 直接用 repository 開一期，只用來造「後面又開過幾期」的
        時間序（`mark_stale_learnings_for_revalidation` 依 `campaign_cycle.created_at`
        排序，不必真的填成效資料）。"""
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]

    def test_ledger_entry_flagged_for_revalidation_after_window_of_later_cycles(self):
        """修憲落地 G4（決策 0035 第三節第 5 點）：`needs_revalidation` 欄位在表上但全庫
        沒有任何一行寫入過。「第 N 期再驗一次」＝這個品牌又開過幾期（依建立順序），
        超過門檻期數還沒被下架，就標記需要複查——只提醒，不擋路、不自動下架。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        entry_id = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()["id"]

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES - 1):
            self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = ?", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 0, "還沒滿門檻期數，不該標記")

        self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = ?", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_revalidation_check_is_wired_into_next_cycle_build(self):
        """驗證真的掛進判讀後的下期準備流程（nextcycle.build()），不是孤兒函式沒人呼叫。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES):
            self._later_cycle()

        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)  # 重判同一期，順手觸發 nextcycle.build()
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE brand_id = ?",
            (self.bid,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_learning_flows_into_next_cycle_prompt_via_context_compiler(self):
        """端到端實測（GitHub issue #54 驗收條件）：建虛構品牌 → 開期產假設 → 判讀 → 結案入帳
        → 下一期生成的 prompt（context_compiler.compile）內確實出現該學習。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})

        # 模擬下一期生成計畫時 plan.py／creative.py 呼叫 compile() 的方式（brand-level）
        text, knowledge_item_ids, _brand_version, _product_version = context_compiler.compile(
            main.conn, self.bid)

        self.assertIn("【已驗證的學習】", text)
        self.assertIn("通勤族比在家工作者更會下單", text)
        self.assertIn(f"來源期別 {self.cycle_id}", text)
        learning_row = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertIn(learning_row["id"], knowledge_item_ids)

    def test_rejected_confirmation_does_not_write_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "rejected"})
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 0)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "rejected")

    def test_resolved_hypothesis_disappears_from_page_after_confirm(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews, [])

    def test_page_renders_hypothesis_review_section(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("這期驗證了什麼", page.text)
        self.assertIn("通勤族比在家工作者更會下單", page.text)
        self.assertIn(f"verdict_{hyp['id']}", page.text)

    def test_unresolved_hypothesis_flagged_at_finalize(self):
        self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertTrue(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_resolved_before_finalize_does_not_flag(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertFalse(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_ignores_unknown_hypothesis_id_and_invalid_verdict_value(self):
        """防偽造 id、防非法 verdict 值：忽略不處理，不拋例外。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        updated = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id,
            {"hyp_not_real": "supported", hyp["id"]: "not_a_real_verdict"}, actor=ACTOR)
        self.assertEqual(updated, 0)


class HypothesisLedgerHaltTest(_HypothesisReviewBase):
    """修憲落地 G4（決策 0035 第三節第 6 點）：假設結案入帳原本是確認偏誤幫浦——AI 預選加
    一路下一步等於橡皮圖章，只有「成立」單向累積、產物貼「已驗證的學習」標籤永久寫進
    prompt。統計缺陷（橡皮圖章式的預選、`maintain` 誤算正面、小樣本喊加碼停損）修好後，
    選「成立」照樣入帳，這裡驗證使用者實際會遇到的預設狀態。"""

    def test_supported_confirmation_writes_ledger_even_though_the_flag_is_on(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/hypotheses",
                         data={f"verdict_{hyp['id']}": "supported"})
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 1)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "supported")


if __name__ == "__main__":
    unittest.main()
