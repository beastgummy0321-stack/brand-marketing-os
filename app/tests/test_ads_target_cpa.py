# -*- coding: utf-8 -*-
"""app/tests/test_ads_target_cpa.py — 目標 CPA 三層鏈＋投放量護欄＋三檔預算卡（票 21）。

驗收重點：
1. 三層鏈依序嘗試，各層可用／不可用／混合都要覆蓋（歷史 CPA → 打平 CPA → 引導推算）。
2. 護欄公式與三檔卡是獨立可測的純函式，不碰資料庫。
3. 積極檔上限＝上期實際週預算 × 2，沒有上期資料就不設上限。
4. 非轉換型目標完全不觸發三層鏈（不做白工計算），走 ±30% 或「無依據」分支。
5. 引導推算表單送出寫入 brand_performance_baseline，可跳過且跳過不擋往下走。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_target_cpa_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import codes as ads_codes  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import target_cpa  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _order(order_number, order_date, total_amount, voucher_code=None):
    return {
        "order_number": order_number, "order_date": order_date, "total_amount": total_amount,
        "refunded_amount": 0, "financial_status": "paid", "fulfillment_status": "fulfilled",
        "order_status": "paid", "voucher_code": voucher_code,
        "billing_email": f"{order_number}@example.test", "billing_phone": None, "items": [],
    }


def _closed_cycle_with_history(bid, *, objective="sales", spend=5000, net_orders=10,
                               start_date="2026-01-01"):
    """開一期、配碼、灌淨歸因訂單、灌花費、結案——湊出一筆可用的歷史 CPA。"""
    cycle = ads_repo.create_cycle(
        main.conn, bid, product_ids=[], pain_value=spend, objective=objective, actor=ACTOR,
        start_date=start_date, duration_days=14)
    codes = ads_codes.generate_codes(
        main.conn, bid, cycle["id"], discount_type="percent", discount_value=10, actor=ACTOR)
    ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
    rows = [_order(f"O{cycle['id']}{i}", start_date, 100, voucher_code=ad_code)
            for i in range(net_orders)]
    orders_repo.save_orders(main.conn, bid, rows, source="easystore_xlsx", actor=ACTOR)
    ads_performance.import_manual(main.conn, bid, cycle["id"], {"spend": spend}, actor=ACTOR)
    ads_repo.update_cycle_status(main.conn, bid, cycle["id"], status="CLOSED", actor=ACTOR)
    return cycle


class _BaseTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構晨露茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]


# ---------------------------------------------------------------------------
# 第 1 層：歷史實際 CPA
# ---------------------------------------------------------------------------

class HistoricalTierTest(_BaseTest):
    def test_uses_the_closed_cycle_with_ad_code_and_net_conversions(self):
        _closed_cycle_with_history(self.bid, objective="sales", spend=5000, net_orders=10)
        result = target_cpa.resolve_target_cpa(main.conn, self.bid, "sales", [])
        self.assertEqual(result["tier"], "history")
        self.assertEqual(result["value"], 500.0)
        self.assertIn("實際成效", result["basis_label"])

    def test_unavailable_without_any_closed_cycle(self):
        self.assertIsNone(target_cpa._historical_tier(main.conn, self.bid, "sales"))

    def test_skips_a_closed_cycle_that_never_got_ad_codes(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="sales", actor=ACTOR,
            start_date="2026-01-01", duration_days=14)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status="CLOSED",
                                     actor=ACTOR)
        self.assertIsNone(target_cpa._historical_tier(main.conn, self.bid, "sales"))

    def test_skips_a_closed_cycle_with_zero_net_conversions_and_falls_back(self):
        older = _closed_cycle_with_history(self.bid, objective="sales", spend=3000, net_orders=6,
                                           start_date="2026-01-01")
        newer = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="sales", actor=ACTOR,
            start_date="2026-02-01", duration_days=14)
        ads_codes.generate_codes(main.conn, self.bid, newer["id"], discount_type="percent",
                                 discount_value=10, actor=ACTOR)
        ads_repo.update_cycle_status(main.conn, self.bid, newer["id"], status="CLOSED",
                                     actor=ACTOR)
        result = target_cpa._historical_tier(main.conn, self.bid, "sales")
        self.assertEqual(result["value"], 500.0)  # 3000/6，來自較舊那期（新那期淨歸因數為 0）
        self.assertNotEqual(older["id"], newer["id"])

    def test_ignores_a_different_objective(self):
        _closed_cycle_with_history(self.bid, objective="leads", spend=1000, net_orders=5)
        self.assertIsNone(target_cpa._historical_tier(main.conn, self.bid, "sales"))

    def test_ignores_a_cycle_that_is_not_closed(self):
        cycle = _closed_cycle_with_history(self.bid, objective="sales")
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status="LIVE", actor=ACTOR)
        self.assertIsNone(target_cpa._historical_tier(main.conn, self.bid, "sales"))


# ---------------------------------------------------------------------------
# 第 2 層：打平 CPA（僅 sales）
# ---------------------------------------------------------------------------

class BreakevenTierTest(_BaseTest):
    def setUp(self):
        super().setUp()
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構茶葉禮盒",
                                              actor=ACTOR)

    def test_uses_the_single_products_gross_margin(self):
        bi_repo.save_product_economics(
            main.conn, self.bid, self.product["id"], actor=ACTOR, selling_price=1000,
            currency="TWD", confirmed_by=ACTOR, unit_variable_cost=400)
        result = target_cpa.resolve_target_cpa(main.conn, self.bid, "sales", [self.product["id"]])
        self.assertEqual(result["tier"], "breakeven")
        self.assertEqual(result["value"], 600.0)

    def test_unavailable_with_multiple_products(self):
        other = bi_repo.create_product(main.conn, self.bid, name="虛構蜂蜜禮盒", actor=ACTOR)
        bi_repo.save_product_economics(
            main.conn, self.bid, self.product["id"], actor=ACTOR, selling_price=1000,
            currency="TWD", confirmed_by=ACTOR, unit_variable_cost=400)
        result = target_cpa._breakeven_tier(main.conn, self.bid,
                                            [self.product["id"], other["id"]])
        self.assertIsNone(result)

    def test_unavailable_without_economics(self):
        self.assertIsNone(target_cpa._breakeven_tier(main.conn, self.bid, [self.product["id"]]))

    def test_not_attempted_for_a_non_sales_objective(self):
        """leads／booking 直接跳過打平 CPA 這層，就算產品有毛利資料。"""
        bi_repo.save_product_economics(
            main.conn, self.bid, self.product["id"], actor=ACTOR, selling_price=1000,
            currency="TWD", confirmed_by=ACTOR, unit_variable_cost=400)
        result = target_cpa.resolve_target_cpa(main.conn, self.bid, "leads",
                                               [self.product["id"]])
        self.assertIsNone(result)  # 還沒存過引導推算值，第 3 層也不可用


# ---------------------------------------------------------------------------
# 第 3 層：引導推算
# ---------------------------------------------------------------------------

class GuidedTierTest(_BaseTest):
    def test_unavailable_before_anything_is_saved(self):
        self.assertIsNone(target_cpa._guided_tier(main.conn, self.bid))

    def test_becomes_available_after_saving(self):
        target_cpa.save_guided_target_cpa(main.conn, self.bid, events_per_sale=5,
                                          margin_per_sale=1000, actor=ACTOR)
        result = target_cpa.resolve_target_cpa(main.conn, self.bid, "leads", [])
        self.assertEqual(result["tier"], "guided")
        self.assertEqual(result["value"], 200.0)  # 1000 ÷ 5

    def test_reached_for_sales_only_after_the_first_two_tiers_fail(self):
        target_cpa.save_guided_target_cpa(main.conn, self.bid, events_per_sale=5,
                                          margin_per_sale=1000, actor=ACTOR)
        result = target_cpa.resolve_target_cpa(main.conn, self.bid, "sales", [])
        self.assertEqual(result["tier"], "guided")

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            target_cpa.save_guided_target_cpa(main.conn, self.bid, events_per_sale=0,
                                              margin_per_sale=1000, actor=ACTOR)
        with self.assertRaises(ValueError):
            target_cpa.save_guided_target_cpa(main.conn, self.bid, events_per_sale=5,
                                              margin_per_sale=0, actor=ACTOR)

    def test_writes_only_into_the_existing_baseline_table(self):
        row = target_cpa.save_guided_target_cpa(main.conn, self.bid, events_per_sale=5,
                                                margin_per_sale=1000, actor=ACTOR)
        self.assertEqual(row["metric"], "target_cpa")
        self.assertIsNone(row["product_id"])
        stored = main.conn.execute(
            "SELECT * FROM brand_performance_baseline WHERE id = ?", (row["id"],)).fetchone()
        self.assertIsNotNone(stored)
        self.assertIn("引導推算", stored["basis_note"])


class AllTiersUnavailableTest(_BaseTest):
    def test_none_when_nothing_can_be_resolved(self):
        self.assertIsNone(target_cpa.resolve_target_cpa(main.conn, self.bid, "leads", []))
        self.assertIsNone(target_cpa.resolve_target_cpa(main.conn, self.bid, "sales", []))


# ---------------------------------------------------------------------------
# 護欄公式與三檔卡：純函式，不碰資料庫
# ---------------------------------------------------------------------------

class VolumeGuardrailTest(unittest.TestCase):
    def test_formula(self):
        result = target_cpa.volume_guardrail(weekly_budget=5000, target_cpa=100)
        self.assertEqual(result["weekly_conversions"], 50.0)
        self.assertEqual(result["groups_sustainable"], 1)
        self.assertEqual(result["creatives_per_group_min"], 3)
        self.assertEqual(result["creatives_per_group_max"], 5)
        self.assertEqual(result["cycle_creative_cap"], 5)

    def test_fewer_than_the_per_group_threshold_sustains_zero_groups(self):
        result = target_cpa.volume_guardrail(weekly_budget=1000, target_cpa=100)  # 週 10 次轉換
        self.assertEqual(result["groups_sustainable"], 0)
        self.assertEqual(result["cycle_creative_cap"], 0)

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            target_cpa.volume_guardrail(0, 100)
        with self.assertRaises(ValueError):
            target_cpa.volume_guardrail(1000, 0)


class BudgetTiersTest(unittest.TestCase):
    def test_three_tiers_use_the_documented_multipliers(self):
        tiers = target_cpa.budget_tiers(200)
        self.assertEqual(tiers["conservative"]["weekly_budget"], 10000)
        self.assertEqual(tiers["recommended"]["weekly_budget"], 15000)
        self.assertEqual(tiers["aggressive"]["weekly_budget"], 20000)
        self.assertTrue(tiers["recommended"]["default"])
        self.assertFalse(tiers["aggressive"]["capped"])

    def test_aggressive_tier_capped_at_twice_previous_weekly_spend(self):
        tiers = target_cpa.budget_tiers(200, previous_weekly_spend=6000)
        self.assertEqual(tiers["aggressive"]["weekly_budget"], 12000)  # min(20000, 6000*2)
        self.assertTrue(tiers["aggressive"]["capped"])

    def test_no_cap_without_previous_cycle_data(self):
        tiers = target_cpa.budget_tiers(200, previous_weekly_spend=None)
        self.assertEqual(tiers["aggressive"]["weekly_budget"], 20000)
        self.assertFalse(tiers["aggressive"]["capped"])

    def test_a_generous_cap_does_not_inflate_the_aggressive_tier(self):
        """上期預算比原本算出來的積極檔還高時，不該反過來把積極檔拉高。"""
        tiers = target_cpa.budget_tiers(200, previous_weekly_spend=50000)
        self.assertEqual(tiers["aggressive"]["weekly_budget"], 20000)
        self.assertFalse(tiers["aggressive"]["capped"])

    def test_rejects_non_positive_target_cpa(self):
        with self.assertRaises(ValueError):
            target_cpa.budget_tiers(0)


# ---------------------------------------------------------------------------
# 非轉換型目標：±30% 區間
# ---------------------------------------------------------------------------

class NonConversionRangeTest(_BaseTest):
    def test_uses_previous_same_objective_actual_spend(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="awareness",
            actor=ACTOR, start_date="2026-01-01", duration_days=14)
        ads_performance.import_manual(main.conn, self.bid, cycle["id"], {"spend": 1000},
                                      actor=ACTOR)
        result = target_cpa.non_conversion_range(main.conn, self.bid, "awareness")
        self.assertEqual(result["low"], 700.0)
        self.assertEqual(result["high"], 1300.0)
        self.assertIn("±30%", result["basis_label"])

    def test_none_without_a_previous_cycle(self):
        self.assertIsNone(target_cpa.non_conversion_range(main.conn, self.bid, "awareness"))

    def test_none_when_the_previous_cycle_has_no_spend_recorded(self):
        ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="traffic",
            actor=ACTOR, start_date="2026-01-01", duration_days=14)
        self.assertIsNone(target_cpa.non_conversion_range(main.conn, self.bid, "traffic"))

    def test_ignores_a_different_objective(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="engagement",
            actor=ACTOR, start_date="2026-01-01", duration_days=14)
        ads_performance.import_manual(main.conn, self.bid, cycle["id"], {"spend": 1000},
                                      actor=ACTOR)
        self.assertIsNone(target_cpa.non_conversion_range(main.conn, self.bid, "traffic"))


class PreviousActualWeeklySpendTest(_BaseTest):
    def test_computes_the_weekly_rate_from_the_most_recent_cycle(self):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1400, objective="sales", actor=ACTOR,
            start_date="2026-01-01", duration_days=14)
        ads_performance.import_manual(main.conn, self.bid, cycle["id"], {"spend": 1400},
                                      actor=ACTOR)
        self.assertEqual(target_cpa.previous_actual_weekly_spend(main.conn, self.bid), 700.0)

    def test_none_without_any_cycle(self):
        self.assertIsNone(target_cpa.previous_actual_weekly_spend(main.conn, self.bid))

    def test_none_when_spend_not_yet_recorded(self):
        ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=1000, objective="sales", actor=ACTOR,
            start_date="2026-01-01", duration_days=14)
        self.assertIsNone(target_cpa.previous_actual_weekly_spend(main.conn, self.bid))


# ---------------------------------------------------------------------------
# 頁面組裝：非轉換型完全不碰三層鏈
# ---------------------------------------------------------------------------

class GuardrailViewTest(_BaseTest):
    def test_non_conversion_objective_never_calls_the_three_tier_chain(self):
        original = target_cpa.resolve_target_cpa

        def _boom(*args, **kwargs):
            raise AssertionError("非轉換型目標不該呼叫三層鏈——這是白工計算")

        target_cpa.resolve_target_cpa = _boom
        try:
            view = target_cpa.guardrail_view(main.conn, self.bid, objective="awareness",
                                             product_ids=[], weekly_budget=1000)
        finally:
            target_cpa.resolve_target_cpa = original
        self.assertEqual(view["kind"], "non_conversion")
        self.assertIsNone(view["range"])

    def test_conversion_objective_assembles_volume_and_tiers(self):
        _closed_cycle_with_history(self.bid, objective="sales", spend=5000, net_orders=10)
        view = target_cpa.guardrail_view(main.conn, self.bid, objective="sales", product_ids=[],
                                         weekly_budget=3500)
        self.assertEqual(view["kind"], "conversion")
        self.assertEqual(view["target_cpa"]["value"], 500.0)
        self.assertEqual(view["volume"]["weekly_conversions"], 7.0)
        self.assertIn("recommended", view["tiers"])
        self.assertEqual(view["learning_note"], target_cpa.LEARNING_PHASE_NOTE)

    def test_conversion_objective_with_no_data_returns_no_target(self):
        view = target_cpa.guardrail_view(main.conn, self.bid, objective="leads", product_ids=[],
                                         weekly_budget=1000)
        self.assertEqual(view["kind"], "conversion")
        self.assertIsNone(view["target_cpa"])


# ---------------------------------------------------------------------------
# HTTP 層：開新檔期頁與引導推算表單
# ---------------------------------------------------------------------------

class NewPageHttpTest(_BaseTest):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)

    def test_default_objective_with_no_history_shows_no_basis_message(self):
        """沒有任何產品資料時 AI 推薦「知名度」（非轉換型），沒有上期資料就誠實說無依據。"""
        page = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("此目標無公式依據", page.text)

    def test_sales_objective_with_history_shows_resolved_cpa_and_learning_note(self):
        _closed_cycle_with_history(self.bid, objective="sales", spend=5000, net_orders=10)
        product = bi_repo.create_product(main.conn, self.bid, name="虛構茶葉禮盒", actor=ACTOR)
        bi_repo.save_product_economics(
            main.conn, self.bid, product["id"], actor=ACTOR, selling_price=1000, currency="TWD",
            confirmed_by=ACTOR, unit_variable_cost=400)
        page = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertIn("這期的目標 CPA", page.text)
        self.assertIn("實際成效", page.text)
        self.assertIn("新檔期會重跑 Meta 學習期", page.text)

    def test_guided_form_saves_and_redirects_back_to_the_same_page(self):
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/target-cpa-guided",
            json={"events_per_sale": "5", "margin_per_sale": "1000"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["value"], 200.0)
        saved = target_cpa._guided_tier(main.conn, self.bid)
        self.assertEqual(saved["value"], 200.0)

    def test_skipping_the_guided_form_does_not_block_creating_a_real_cycle(self):
        # 兩格留白＝跳過這一步：什麼都沒存下來（舊頁用 warn 訊息條、API 用 400 表達同一件事）
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/target-cpa-guided",
            json={"events_per_sale": "", "margin_per_sale": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(target_cpa._guided_tier(main.conn, self.bid))

        resp2 = self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"objective": "leads", "budget": 3000, "product_ids": []})
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["cycle_id"])


if __name__ == "__main__":
    unittest.main()
