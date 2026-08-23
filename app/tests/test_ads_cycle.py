# -*- coding: utf-8 -*-
"""app/tests/test_ads_cycle.py — 廣告分支票 4：開期入口、歷期清單、開新檔期。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_cycle_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class _BaseAdsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_a = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                actor=ACTOR)["id"]
        self.product_b = bi_repo.create_product(main.conn, self.bid, name="虛構冷萃瓶",
                                                actor=ACTOR)["id"]

    def _add_economics(self, product_id, price, cost):
        bi_repo.save_product_economics(main.conn, self.bid, product_id, selling_price=price,
                                       unit_variable_cost=cost, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)

    def _open_cycle(self, **overrides):
        data = {"product_ids": [self.product_a, self.product_b], "slider_index": "5",
                "objective": "sales"}
        data.update(overrides)
        amount = data.get("custom_amount") or 10000
        try:
            amount = float(amount)
            if amount.is_integer():
                amount = int(amount)
        except (TypeError, ValueError):
            pass
        duration_days = data.get("duration_days")
        if duration_days:
            duration_days = int(duration_days)
        return self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"product_ids": data["product_ids"], "budget": amount,
                  "objective": data["objective"], "duration_days": duration_days,
                  "background": data.get("background"),
                  "simulate": data.get("mode") == "simulation"},
        )


class AdsHomeTest(_BaseAdsTest):
    def test_cycle_appears_in_list(self):
        """D線票3（#45）：廣告 hub 改五卡後，全部檔期清單搬到 /ads/history——
        產品名與目標這類per-檔期細節不再出現在 hub（hub 卡片有 30 全形字容量上限，
        放不下不定長的產品清單），改到歷期戰績頁確認。"""
        self._open_cycle()
        listing = json.dumps(
            self.client.get(f"/api/campaigns/brands/{self.bid}").json()["data"],
            ensure_ascii=False)
        self.assertIn("虛構濾掛組", listing)
        self.assertIn("銷售", listing)


class AdsNewPageTest(_BaseAdsTest):
    def test_recommends_sales_when_margin_known(self):
        self._add_economics(self.product_a, 600, 200)
        data = self.client.get(f"/api/campaigns/{self.bid}/new-context").json()["data"]
        self.assertEqual(data["recommended_objective"], "sales")

    def test_recommends_awareness_when_no_margin(self):
        data = self.client.get(f"/api/campaigns/{self.bid}/new-context").json()["data"]
        self.assertEqual(data["recommended_objective"], "awareness")

    def test_readiness_notes_warn_but_do_not_block(self):
        """缺資料只提示、附一鍵去補，開期照樣走得下去（決策 0013）。"""
        data = self.client.get(f"/api/campaigns/{self.bid}/new-context").json()["data"]
        notes = json.dumps(data["readiness_notes"], ensure_ascii=False)
        self.assertIn("還沒有可用的成本售價", notes)
        self.assertIn(f"/app/brands/{self.bid}/products", notes)
        self.assertEqual(self._open_cycle().status_code, 200)


class CreateCycleTest(_BaseAdsTest):
    def test_creates_cycle_with_derived_plan(self):
        resp = self._open_cycle(slider_index="5")  # 10,000
        self.assertEqual(resp.status_code, 200)
        cycle_id = resp.json()["cycle_id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["budget"], 10000)
        self.assertEqual(cycle["status"], "PLANNING")
        plan = ads_repo.derived_plan(cycle)
        self.assertEqual(plan["duration_days"], 14)
        self.assertEqual(plan["daily_budget"], 714.29)

    def test_custom_amount_overrides_slider(self):
        resp = self._open_cycle(slider_index="0", custom_amount="25000")
        cycle_id = resp.json()["cycle_id"]
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["budget"], 25000)

    def test_budget_split_follows_margin(self):
        self._add_economics(self.product_a, 1000, 400)   # 毛利 600
        self._add_economics(self.product_b, 500, 200)    # 毛利 300
        resp = self._open_cycle(custom_amount="9000")
        cycle_id = resp.json()["cycle_id"]
        rows = {r["product_id"]: r for r in
                ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)}
        self.assertEqual(rows[self.product_a]["allocated_budget"], 6000)
        self.assertEqual(rows[self.product_b]["allocated_budget"], 3000)
        self.assertEqual(rows[self.product_a]["allocation_basis"], "economics")

    def test_missing_economics_flagged_but_still_allocated(self):
        self._add_economics(self.product_a, 1000, 400)
        resp = self._open_cycle(custom_amount="10000")
        cycle_id = resp.json()["cycle_id"]
        rows = {r["product_id"]: r for r in
                ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)}
        self.assertEqual(rows[self.product_b]["economics_missing"], 1)
        self.assertGreater(rows[self.product_b]["allocated_budget"], 0)

    def test_allocation_sums_to_total(self):
        resp = self._open_cycle(custom_amount="9999.99")
        cycle_id = resp.json()["cycle_id"]
        rows = ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)
        self.assertAlmostEqual(sum(r["allocated_budget"] for r in rows), 9999.99, places=2)

    def test_no_products_selected_is_brand_scope(self):
        resp = self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"product_ids": [], "budget": 5000, "objective": "awareness"},
        )
        self.assertEqual(resp.status_code, 200)
        cycle_id = resp.json()["cycle_id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(json.loads(cycle["product_scope_json"]), [])

    def test_custom_duration_recomputes_daily_budget(self):
        """票 3：自訂天數要連動日預算（單純除法，不套自動縮短天數的演算法）。"""
        import datetime
        resp = self._open_cycle(custom_amount="10000", duration_days="20")
        cycle_id = resp.json()["cycle_id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        plan = ads_repo.derived_plan(cycle)
        self.assertEqual(plan["duration_days"], 20)
        self.assertEqual(plan["daily_budget"], 500.0)
        start = datetime.date.fromisoformat(cycle["start_date"])
        end = datetime.date.fromisoformat(cycle["end_date"])
        self.assertEqual((end - start).days, 19)  # 20 天含頭尾

    def test_duration_out_of_range_is_rejected(self):
        for value in ("6", "31", "abc"):
            resp = self.client.post(
                f"/api/campaigns/{self.bid}",
                json={"product_ids": [self.product_a, self.product_b], "budget": 10000,
                      "objective": "sales", "duration_days": value},
            )
            self.assertEqual(resp.status_code, 400)

    def test_custom_start_date_is_used(self):
        # /api 開檔期不吃 start_date（新殼一律今天開跑），直接呼叫業務函式驗同一件事
        cycle_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_a, self.product_b],
            pain_value=10000, objective="sales", actor=ACTOR, start_date="2026-09-01")["id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["start_date"], "2026-09-01")

    def test_background_is_saved_and_readable(self):
        """票 3：背景欄落庫，後續計畫生成讀得到。"""
        resp = self._open_cycle(background="七月有一波電商大促，同業都在打折。")
        cycle_id = resp.json()["cycle_id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["background"], "七月有一波電商大促，同業都在打折。")

    def test_background_left_blank_is_null(self):
        resp = self._open_cycle()
        cycle_id = resp.json()["cycle_id"]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertIsNone(cycle["background"])

    def test_invalid_objective_is_rejected_with_message(self):
        resp = self._open_cycle(objective="")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請選一個本期目標", resp.text)

    def test_invalid_amount_is_rejected(self):
        resp = self._open_cycle(custom_amount="abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("大於 0 的金額", resp.text)

    def test_works_without_operator_cookie(self):
        """ADR 0004：單機單人不再具名，沒設操作人 cookie 一樣能完成操作，不再被攔下。"""
        self.client.cookies.clear()
        resp = self._open_cycle()
        self.assertEqual(resp.status_code, 200)
        cycle_id = resp.json()["cycle_id"]
        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_cycle' AND entity_id = ?",
            (cycle_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], OPERATOR)

    def test_audit_log_written(self):
        resp = self._open_cycle()
        cycle_id = resp.json()["cycle_id"]
        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_cycle' AND entity_id = ?",
            (cycle_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], OPERATOR)


class PacingCurveTest(_BaseAdsTest):
    """票 pacing-curve：開期自動算好排期策略、頁面顯示、手動改排法。"""

    def _create(self, **overrides):
        resp = self._open_cycle(**overrides)
        return resp.json()["cycle_id"]

    def test_long_duration_defaults_to_continuous_with_daily_budgets(self):
        """這裡沒帶 offer，has_offer=False，天數夠長時仍是連續（帶 offer 的分支見
        OfferCycleTest.test_offer_at_open_time_flips_pacing_to_pulse）。"""
        cycle_id = self._create(custom_amount="10000", duration_days="14")
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        plan = ads_repo.derived_plan(cycle)
        self.assertEqual(plan["pacing_strategy"], "continuous")
        self.assertEqual(len(plan["daily_budgets"]), 14)
        self.assertAlmostEqual(sum(d["budget"] for d in plan["daily_budgets"]), 10000, delta=1)

    def test_short_duration_is_continuous_with_short_reason(self):
        cycle_id = self._create(custom_amount="2000", duration_days="7")
        plan = ads_repo.derived_plan(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertEqual(plan["pacing_strategy"], "continuous")
        self.assertIn("太短", plan["pacing_reason"])

    def test_manual_switch_to_pulse_recomputes_curve(self):
        cycle_id = self._create(custom_amount="21000", duration_days="21")
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/pacing",
            json={"pacing_strategy": "pulse", "pacing_reason": "檔期本身是限時衝刺"})
        self.assertEqual(resp.status_code, 204)
        plan = ads_repo.derived_plan(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertEqual(plan["pacing_strategy"], "pulse")
        self.assertEqual(plan["pacing_reason"], "檔期本身是限時衝刺")
        self.assertEqual(len(plan["daily_budgets"]), 21)
        self.assertAlmostEqual(sum(d["budget"] for d in plan["daily_budgets"]), 21000, delta=1)

    def test_short_duration_rejects_non_continuous_switch(self):
        """天數不夠時系統不讓使用者選脈動或間歇（G9.4／ADR 0010 第五節）。"""
        cycle_id = self._create(custom_amount="2000", duration_days="7")
        resp = self.client.post(
            f"/api/campaigns/{self.bid}/{cycle_id}/pacing",
            json={"pacing_strategy": "intermittent", "pacing_reason": "怕受眾疲乏"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("天數不足", resp.json()["error"])
        plan = ads_repo.derived_plan(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertEqual(plan["pacing_strategy"], "continuous")  # 沒被改動


class OfferCycleTest(_BaseAdsTest):
    """票 V1-01：開期帶優惠、後補／編輯優惠、清除優惠。"""

    def _open_with_offer(self, **overrides):
        offer = overrides.pop("offer", {"name": "全館 8 折", "offer_type": "discount",
                                        "terms": "滿 2000 折 300，不含特價品"})
        body = {"product_ids": [self.product_a], "budget": 30000, "objective": "sales",
                "duration_days": 30, "offer": offer}
        body.update(overrides)
        return self.client.post(f"/api/campaigns/{self.bid}", json=body)

    def test_offer_at_open_time_flips_pacing_to_pulse(self):
        """驗收 1：開期當下帶優惠，30 天檔期的排期策略從連續變脈動。"""
        resp = self._open_with_offer()
        self.assertEqual(resp.status_code, 200)
        cycle = ads_repo.get_cycle(main.conn, self.bid, resp.json()["cycle_id"])
        self.assertIsNotNone(cycle["offer_id"])
        self.assertEqual(ads_repo.derived_plan(cycle)["pacing_strategy"], "pulse")
        offer_row = main.conn.execute("SELECT * FROM offer WHERE id = ?", (cycle["offer_id"],)).fetchone()
        self.assertEqual(offer_row["name"], "全館 8 折")
        self.assertEqual(offer_row["valid_from"], cycle["start_date"])
        self.assertEqual(offer_row["valid_to"], cycle["end_date"])
        self.assertEqual(offer_row["product_scope_json"], cycle["product_scope_json"])

    def test_cycle_detail_serves_offer(self):
        cycle_id = self._open_with_offer().json()["cycle_id"]
        data = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}").json()["data"]
        self.assertEqual(data["cycle"]["offer"]["name"], "全館 8 折")
        self.assertEqual(data["cycle"]["offer"]["offer_type_label"], "折扣")

    def test_cycle_detail_offer_is_null_without_one(self):
        cycle_id = self._open_cycle().json()["cycle_id"]
        data = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}").json()["data"]
        self.assertIsNone(data["cycle"]["offer"])

    def test_put_edit_leaves_daily_budgets_byte_identical(self):
        """驗收 3：已開檔期後補／改優惠，daily_budgets 一個數字都不動。"""
        cycle_id = self._open_with_offer(duration_days=21).json()["cycle_id"]
        before = ads_repo.derived_plan(ads_repo.get_cycle(main.conn, self.bid, cycle_id))["daily_budgets"]
        resp = self.client.put(f"/api/campaigns/{self.bid}/{cycle_id}/offer",
                               json={"name": "改個名字", "offer_type": "gift", "terms": "改過的條件"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["name"], "改個名字")
        self.assertEqual(resp.json()["data"]["offer_type_label"], "贈品")
        after = ads_repo.derived_plan(ads_repo.get_cycle(main.conn, self.bid, cycle_id))["daily_budgets"]
        self.assertEqual(json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False))

    def test_put_fills_offer_on_cycle_without_one_and_does_not_recompute(self):
        cycle_id = self._open_cycle(duration_days="21").json()["cycle_id"]
        before_cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertIsNone(before_cycle["offer_id"])
        before_plan = ads_repo.derived_plan(before_cycle)
        resp = self.client.put(f"/api/campaigns/{self.bid}/{cycle_id}/offer",
                               json={"name": "全館 8 折", "offer_type": "discount", "terms": "滿 2000 折 300"})
        self.assertEqual(resp.status_code, 200)
        after_cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertIsNotNone(after_cycle["offer_id"])
        after_plan = ads_repo.derived_plan(after_cycle)
        self.assertEqual(after_plan["pacing_strategy"], "continuous")  # PUT 不觸發脈動
        self.assertEqual(after_plan["daily_budgets"], before_plan["daily_budgets"])

    def test_blank_name_is_rejected_with_no_row_written(self):
        """驗收 5：名稱空白，白話 400，開期本身也不落地。"""
        before_offers = main.conn.execute("SELECT COUNT(*) c FROM offer").fetchone()["c"]
        resp = self._open_with_offer(offer={"name": "", "offer_type": "discount", "terms": "滿 2000 折 300"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("取個名字", resp.json()["error"])
        self.assertEqual(main.conn.execute("SELECT COUNT(*) c FROM offer").fetchone()["c"], before_offers)
        self.assertEqual(ads_repo.list_cycles(main.conn, self.bid), [])

    def test_blank_terms_is_rejected_with_no_row_written(self):
        before_offers = main.conn.execute("SELECT COUNT(*) c FROM offer").fetchone()["c"]
        resp = self._open_with_offer(offer={"name": "全館 8 折", "offer_type": "discount", "terms": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(main.conn.execute("SELECT COUNT(*) c FROM offer").fetchone()["c"], before_offers)
        self.assertEqual(ads_repo.list_cycles(main.conn, self.bid), [])

    def test_put_blank_name_is_rejected(self):
        cycle_id = self._open_with_offer().json()["cycle_id"]
        resp = self.client.put(f"/api/campaigns/{self.bid}/{cycle_id}/offer",
                               json={"name": "", "offer_type": "discount", "terms": "還是那句話"})
        self.assertEqual(resp.status_code, 400)

    def test_delete_clears_offer_id_and_row(self):
        """驗收 4：清除後 campaign_cycle.offer_id 是 NULL，offer row 消失。"""
        cycle_id = self._open_with_offer().json()["cycle_id"]
        offer_id = ads_repo.get_cycle(main.conn, self.bid, cycle_id)["offer_id"]
        self.assertIsNotNone(offer_id)
        resp = self.client.delete(f"/api/campaigns/{self.bid}/{cycle_id}/offer")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["cleared"])
        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["offer_id"])
        self.assertIsNone(main.conn.execute("SELECT * FROM offer WHERE id = ?", (offer_id,)).fetchone())


class AdsBrandIsolationTest(_BaseAdsTest):
    def test_other_brand_cannot_see_or_open_cycle(self):
        resp = self._open_cycle()
        cycle_id = resp.json()["cycle_id"]

        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙", client_name=None, actor=ACTOR)
        other_id = other["id"]

        self.assertEqual(ads_repo.list_cycles(main.conn, other_id), [])
        self.assertIsNone(ads_repo.get_cycle(main.conn, other_id, cycle_id))
        self.assertEqual(
            self.client.get(f"/api/campaigns/{other_id}/{cycle_id}").status_code, 404)
        # 自己的品牌查得到，證明過濾條件不是永遠回空
        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))


if __name__ == "__main__":
    unittest.main()
