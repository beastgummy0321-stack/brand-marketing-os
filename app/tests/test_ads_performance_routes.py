"""app/tests/test_ads_performance_routes.py — HTTP route surface for performance manual/CSV
import (ticket 01: restoring the entry points `performance_manual` and `performance_csv`
in app/ads/routes_campaigns_performance_api.py that were deleted along with the Jinja
`ads_performance_manual`/`ads_performance_csv` routes).

Split out of test_ads_performance.py on purpose: that file is business-layer tests — it
calls `perf.import_manual`/`perf.import_csv` directly and never goes through TestClient.
This file is the only place in the suite that drives the JSON routes end to end (request
parsing, status codes, the `{"error": ...}` envelope, the CSV multipart upload path), so a
regression in the route itself — not the business logic it wraps — shows up here even if
test_ads_performance.py stays green. Splitting also keeps test_ads_performance.py under the
architecture boundary line cap (see app/tests/test_architecture_boundaries.py, FILE_LINE_CAP)
without dropping any coverage.

Shares `_BaseImportTest` (brand + cycle fixture, TestClient) with test_ads_performance.py
instead of duplicating it — same convention as test_ads_creative_web_search.py importing
`_BaseCreativeTest` from test_ads_creative.py. Per-module database isolation is handled by
app/tests/conftest.py's `isolate_module_database` fixture (keys off `import app.main as
main` below), so this file does not need its own tempdir/atexit cleanup boilerplate.
"""

import json
import unittest

import app.main as main
from app.ads import performance as perf
from app.ads import reading, weekly_proposals
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.llm.providers import FakeProvider, ProviderResponse, Usage
from app.tests.test_ads_performance import ACTOR, _BaseImportTest


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")





class PerformanceRouteTest(_BaseImportTest):
    """票 01：T4 清倉連 JSON 路由也一併清掉；復原 `/performance/manual`／`/csv` 兩條路由。"""

    def test_manual_route_imports_and_returns_result_json(self):
        """票 11 D2：手動路由改跟 CSV 路由同一個回應形狀，秀出跳過幾筆——不是 204 空回應。"""
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                                json={"spend": "12000", "impressions": "80000", "clicks": "1600",
                                      "conversions": "24", "revenue": "18000", "reach": "52000",
                                      "date_start": "2026-08-01", "date_stop": "2026-08-07"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["imported"], 1)
        self.assertEqual(resp.json()["skipped"], 0)
        rows = perf.list_snapshots(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "manual")
        self.assertEqual(rows[0]["spend"], 12000)

    def test_manual_route_rejects_non_numeric_field(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                                json={"spend": "abc"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_manual_route_requires_spend(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                                json={"clicks": "10"})
        self.assertEqual(resp.status_code, 400)

    def test_csv_route_imports_using_chinese_meta_aliases(self):
        csv_text = "花費金額,廣告名稱\n1000,廣告A\n2000,廣告B\n"
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_text, "text/csv")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["imported"], 2)

    def test_csv_route_rejects_empty_upload(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/csv",
                                files={"perf_file": ("perf.csv", "", "text/csv")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_csv_route_decodes_cp950_header(self):
        """Windows 匯出常見 cp950/big5——decode 不能默默吞成亂碼再回報 imported=0。"""
        csv_bytes = "花費金額,廣告名稱\n1000,廣告A\n2000,廣告B\n".encode("cp950")
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_bytes, "text/csv")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["imported"], 2)

    def test_manual_route_saves_derived_metrics(self):
        """路由要照舊順序做完 import_manual 再 save_derived_metrics，不能只落快照不算 KPI。"""
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                         json={"spend": "12000", "clicks": "1600", "impressions": "80000",
                               "conversions": "24", "revenue": "18000"})
        rows = main.conn.execute(
            "SELECT metric, value FROM derived_metric WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchall()
        self.assertTrue(rows)  # save_derived_metrics 真的寫進 derived_metric 了


class PerformanceGetAssetBreakdownTest(_BaseImportTest):
    """契約 C（票 03-performance-reaches-the-user）：GET /performance 的 reading 物件要帶
    asset_breakdown，沒有素材層拆分時給空陣列，不能是 null。"""

    def setUp(self):
        super().setUp()
        self._orig_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig_provider

    def _package(self, ad_name: str) -> str:
        pkg_id = db.new_id("pkg")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " campaign_name, adset_name, ad_name, destination_url, utm_json, status,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, "測試活動", "測試組合", ad_name,
             "https://example.test", ts))
        mapping_id = db.new_id("xam")
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (mapping_id, db.DEV_ORG_ID, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        return pkg_id

    def test_reading_carries_asset_breakdown_with_documented_shape(self):
        self._package("在地手工品質_03")
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,在地手工品質_03,10000,48,2500,2,840\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertEqual(resp.status_code, 200)
        breakdown = resp.json()["data"]["reading"]["asset_breakdown"]
        self.assertEqual(len(breakdown), 1)
        row = breakdown[0]
        self.assertEqual(row["asset_name"], "在地手工品質_03")
        self.assertEqual(row["impressions"], 10000)
        self.assertEqual(row["revenue"], 840)
        self.assertEqual(row["kpis"]["roas"], round(840 / 2500, 2))

    def test_reading_asset_breakdown_is_empty_list_not_null_without_a_split(self):
        perf.import_manual(main.conn, self.bid, self.cycle_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertEqual(resp.json()["data"]["reading"]["asset_breakdown"], [])


class LiveCycleImportTriggersReadingTest(_BaseImportTest):
    """票 R1-live-reading-output（`.scratch/rehearsal-b0-fix/issues/R1-live-reading-output.md`）：
    投放中（LIVE）檔期匯入成效，成效路由自己要補一次判讀＋建卡，不能乾等 day7 提醒、
    每週一背景排程，或使用者自己去駕駛艙按「現在就重新判讀」。根因：`_late_data_rerun()`
    原本只認「已經判讀過又補件」，LIVE 檔期的第一次判讀完全沒人觸發（見 R1-rootcause.md）。"""

    def setUp(self):
        super().setUp()
        self._orig_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig_provider

    def _live_cycle_with_losing_ad(self):
        product_id = bi_repo.create_product(
            main.conn, self.bid, name="虛構R1商品", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.bid, product_id, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR, actor=ACTOR)
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product_id], pain_value=10000,
            objective="sales", actor=ACTOR, start_date="2026-07-01", duration_days=14)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status="LIVE", actor=ACTOR)
        ts = db.now_utc()
        pkg_id, mapping_id = db.new_id("pkg"), db.new_id("xam")
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " product_id, campaign_name, adset_name, ad_name, destination_url, utm_json,"
            " status, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, cycle["id"], product_id, "R1測試活動",
             "R1測試組合", "虧損_01_ad", "https://example.test", ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (mapping_id, db.DEV_ORG_ID, self.bid, pkg_id, cycle["id"], ACTOR, ts, ts))
        main.conn.commit()
        return cycle["id"]

    def test_csv_import_on_live_cycle_runs_reading_and_generates_a_stop_card(self):
        cycle_id = self._live_cycle_with_losing_ad()
        self.assertIsNone(reading.load(main.conn, self.bid, cycle_id)["cycle"])

        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "R1測試活動,虧損_01_ad,20000,400,10000,0,0\n")
        resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/performance/csv",
                                files={"perf_file": ("perf.csv", csv_text, "text/csv")})

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["rerun"], "live_reading")
        self.assertTrue(resp.json()["rerun_message"])

        loaded = reading.load(main.conn, self.bid, cycle_id)
        self.assertIsNotNone(loaded["cycle"])  # reading.run() 真的跑了，不用再等結算
        self.assertTrue(any(p["status"] == "pause_candidate" for p in loaded["products"]))

        cards = weekly_proposals.list_cards(main.conn, self.bid, cycle_id)
        self.assertTrue(any(card["action"] == "停掉" for card in cards))  # generate() 真的建卡了

    def test_confidence_label_agrees_with_reading_right_after_import(self):
        """B0-02／B0-06（`.scratch/rehearsal-b0-fix/issues/R5-cockpit-and-state-machine.md`）：
        匯入完成、不按任何按鈕，GET /performance 的 `confidence_label` 不能還停在「這期還
        沒有成效判讀」，卻同時附上一份已經判讀完的 `reading`——這支測試鎖住 R1（判讀在匯入
        當下同步跑完）讓這兩個欄位不可能互相矛盾。"""
        cycle_id = self._live_cycle_with_losing_ad()
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "R1測試活動,虧損_01_ad,20000,400,10000,0,0\n")
        import_resp = self.client.post(f"/api/campaigns/{self.bid}/{cycle_id}/performance/csv",
                                       files={"perf_file": ("perf.csv", csv_text, "text/csv")})
        self.assertEqual(import_resp.status_code, 200, import_resp.text)

        resp = self.client.get(f"/api/campaigns/{self.bid}/{cycle_id}/performance")
        data = resp.json()["data"]
        self.assertIsNotNone(data["reading"])
        self.assertNotEqual(data["confidence_label"], "這期還沒有成效判讀，可信度未知。")


if __name__ == "__main__":
    unittest.main()
