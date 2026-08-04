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
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402

main.reopen_connection()


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
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                         follow_redirects=False)
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
        return self.client.post(f"/brands/{self.bid}/ads/new", data=data,
                                follow_redirects=False)


class AdsHomeTest(_BaseAdsTest):
    def test_empty_state_invites_first_cycle(self):
        resp = self.client.get(f"/brands/{self.bid}/ads")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("還沒有跑過任何一期廣告", resp.text)

    def test_brand_menu_links_to_ads_as_real_feature(self):
        """廣告已從「即將推出」灰卡變成正式功能卡。"""
        resp = self.client.get(f"/brands/{self.bid}")
        self.assertIn(f'href="/brands/{self.bid}/ads"', resp.text)
        self.assertNotIn("廣告即將推出", resp.text.replace(" ", ""))

    def test_cycle_appears_in_list(self):
        """D線票3（#45）：廣告 hub 改五卡後，全部檔期清單搬到 /ads/history——
        產品名與目標這類per-檔期細節不再出現在 hub（hub 卡片有 30 全形字容量上限，
        放不下不定長的產品清單），改到歷期戰績頁確認。"""
        self._open_cycle()
        resp = self.client.get(f"/brands/{self.bid}/ads/history")
        self.assertIn("虛構濾掛組", resp.text)
        self.assertIn("銷售", resp.text)


class AdsNewPageTest(_BaseAdsTest):
    def test_slider_options_are_precomputed_server_side(self):
        """換算規則只有 Python 一份：每檔的結果由後端算好塞進頁面，前端不重算。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("slider-data", resp.text)
        self.assertIn("duration_days", resp.text)

    def test_products_default_to_all_selected(self):
        """反對制：預設全勾，使用者只需要把不推的拿掉。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        checked = resp.text.count("checkbox")
        self.assertEqual(checked, 2)
        self.assertEqual(resp.text.count('name="product_ids"'), 2)
        for product_id in (self.product_a, self.product_b):
            marker = f'value="{product_id}"'
            index = resp.text.index(marker)
            self.assertIn("checked", resp.text[index:index + 120])

    def test_recommends_sales_when_margin_known(self):
        self._add_economics(self.product_a, 600, 200)
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        index = resp.text.index('value="sales"')
        self.assertIn("checked", resp.text[index:index + 80])
        self.assertIn("AI 推薦", resp.text)

    def test_recommends_awareness_when_no_margin(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        index = resp.text.index('value="awareness"')
        self.assertIn("checked", resp.text[index:index + 80])

    def test_five_objectives_aligned_to_meta_with_hints(self):
        """票 3：成效目標改 5 選項，對齊 Meta 官方分類，各附白話說明。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        for value in ("awareness", "traffic", "engagement", "leads", "sales"):
            self.assertIn(f'value="{value}"', resp.text)
        for label in ("知名度", "流量", "互動", "潛在顧客", "銷售"):
            self.assertIn(label, resp.text)
        self.assertNotIn("應用程式推廣", resp.text)

    def test_duration_suggestion_shown_with_rationale(self):
        """票 3：檔期長度顯示建議值（預設 14 天）與白話理由，可自訂 7–30 天。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertIn('name="duration_days"', resp.text)
        self.assertIn('min="7"', resp.text)
        self.assertIn('max="30"', resp.text)
        self.assertIn('value="14"', resp.text)
        self.assertIn("兩週是常見的檔期長度", resp.text)

    def test_slider_and_duration_scripts_wait_for_dom_ready(self):
        """票 25 回歸守門：連動腳本在 <head> 執行，若沒等 DOM 就緒，
        document.getElementById('slider') 等會在元素解析出來之前抓空，
        guard clause 直接 return，事件永遠綁不上（根因）。
        這裡守住兩點：腳本包在 DOMContentLoaded 裡、且被綁定的元素 id 確實存在於畫面上。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        html = resp.text
        self.assertIn("document.addEventListener('DOMContentLoaded'", html)
        for hook_id in ("slider", "readout-amount", "readout-days", "readout-daily",
                        "readout-note", "duration_days", "duration-daily",
                        "duration-tier-note", "custom_amount"):
            self.assertIn(f'id="{hook_id}"', html)

    def test_background_field_is_present_and_optional(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertIn('name="background"', resp.text)
        self.assertIn("這期有什麼背景？（選填）", resp.text)

    def test_readiness_notes_warn_but_do_not_block(self):
        """缺資料只提示、附一鍵去補，開期照樣走得下去（決策 0013）。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertIn("還沒有可用的成本售價", resp.text)
        self.assertIn(f"/brands/{self.bid}/hub/products", resp.text)
        self.assertEqual(self._open_cycle().status_code, 303)


class CreateCycleTest(_BaseAdsTest):
    def test_creates_cycle_with_derived_plan(self):
        resp = self._open_cycle(slider_index="5")  # 10,000
        self.assertEqual(resp.status_code, 303)
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["budget"], 10000)
        self.assertEqual(cycle["status"], "PLANNING")
        plan = ads_repo.derived_plan(cycle)
        self.assertEqual(plan["duration_days"], 14)
        self.assertEqual(plan["daily_budget"], 714.29)

    def test_custom_amount_overrides_slider(self):
        resp = self._open_cycle(slider_index="0", custom_amount="25000")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["budget"], 25000)

    def test_budget_split_follows_margin(self):
        self._add_economics(self.product_a, 1000, 400)   # 毛利 600
        self._add_economics(self.product_b, 500, 200)    # 毛利 300
        resp = self._open_cycle(custom_amount="9000")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        rows = {r["product_id"]: r for r in
                ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)}
        self.assertEqual(rows[self.product_a]["allocated_budget"], 6000)
        self.assertEqual(rows[self.product_b]["allocated_budget"], 3000)
        self.assertEqual(rows[self.product_a]["allocation_basis"], "economics")

    def test_missing_economics_flagged_but_still_allocated(self):
        self._add_economics(self.product_a, 1000, 400)
        resp = self._open_cycle(custom_amount="10000")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        rows = {r["product_id"]: r for r in
                ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)}
        self.assertEqual(rows[self.product_b]["economics_missing"], 1)
        self.assertGreater(rows[self.product_b]["allocated_budget"], 0)
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn("精準度打折", page.text)

    def test_allocation_sums_to_total(self):
        resp = self._open_cycle(custom_amount="9999.99")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        rows = ads_repo.list_cycle_products(main.conn, self.bid, cycle_id)
        self.assertAlmostEqual(sum(r["allocated_budget"] for r in rows), 9999.99, places=2)

    def test_no_products_selected_is_brand_scope(self):
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"slider_index": "3", "objective": "awareness"},
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(json.loads(cycle["product_scope_json"]), [])
        # D線票3（#45）：產品範圍這類per-檔期細節搬到歷期戰績頁，hub 卡片不再列出
        self.assertIn("整個品牌", self.client.get(f"/brands/{self.bid}/ads/history").text)

    def test_custom_duration_recomputes_daily_budget(self):
        """票 3：自訂天數要連動日預算（單純除法，不套自動縮短天數的演算法）。"""
        import datetime
        resp = self._open_cycle(custom_amount="10000", duration_days="20")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        plan = ads_repo.derived_plan(cycle)
        self.assertEqual(plan["duration_days"], 20)
        self.assertEqual(plan["daily_budget"], 500.0)
        start = datetime.date.fromisoformat(cycle["start_date"])
        end = datetime.date.fromisoformat(cycle["end_date"])
        self.assertEqual((end - start).days, 19)  # 20 天含頭尾

    def test_duration_out_of_range_is_rejected(self):
        for value in ("6", "31", "abc"):
            resp = self._open_cycle(duration_days=value)
            self.assertEqual(resp.status_code, 400)

    def test_invalid_start_date_is_rejected(self):
        resp = self._open_cycle(start_date="not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("開始日期格式不對", resp.text)

    def test_custom_start_date_is_used(self):
        resp = self._open_cycle(start_date="2026-09-01")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["start_date"], "2026-09-01")

    def test_background_is_saved_and_readable(self):
        """票 3：背景欄落庫，後續計畫生成讀得到。"""
        resp = self._open_cycle(background="七月有一波電商大促，同業都在打折。")
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        self.assertEqual(cycle["background"], "七月有一波電商大促，同業都在打折。")

    def test_background_left_blank_is_null(self):
        resp = self._open_cycle()
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
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

    def test_requires_operator_name(self):
        self.client.cookies.clear()
        resp = self._open_cycle()
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/settings/operator", resp.headers["location"])

    def test_audit_log_written(self):
        resp = self._open_cycle()
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]
        row = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'campaign_cycle' AND entity_id = ?",
            (cycle_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], ACTOR)


class AdsBrandIsolationTest(_BaseAdsTest):
    def test_other_brand_cannot_see_or_open_cycle(self):
        resp = self._open_cycle()
        cycle_id = resp.headers["location"].split("/ads/")[1].split("?")[0]

        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙", client_name=None, actor=ACTOR)
        other_id = other["id"]

        self.assertEqual(ads_repo.list_cycles(main.conn, other_id), [])
        self.assertIsNone(ads_repo.get_cycle(main.conn, other_id, cycle_id))
        self.assertEqual(
            self.client.get(f"/brands/{other_id}/ads/{cycle_id}").status_code, 404)
        # 自己的品牌查得到，證明過濾條件不是永遠回空
        self.assertIsNotNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))


if __name__ == "__main__":
    unittest.main()
