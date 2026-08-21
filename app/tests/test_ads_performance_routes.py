# -*- coding: utf-8 -*-
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

import unittest

import app.main as main
from app.ads import performance as perf
from app.tests.test_ads_performance import _BaseImportTest


class PerformanceRouteTest(_BaseImportTest):
    """票 01：T4 清倉連 JSON 路由也一併清掉；復原 `/performance/manual`／`/csv` 兩條路由。"""

    def test_manual_route_imports_and_returns_204(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                                json={"spend": "12000", "impressions": "80000", "clicks": "1600",
                                      "conversions": "24", "revenue": "18000", "reach": "52000",
                                      "date_start": "2026-08-01", "date_stop": "2026-08-07"})
        self.assertEqual(resp.status_code, 204)
        rows = perf.list_snapshots(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "manual")
        self.assertEqual(rows[0]["spend"], 12000)

    def test_manual_route_rejects_non_numeric_field(self):
        resp = self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual",
                                json={"spend": "abc"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": "數字欄位請只填數字。"})

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
        self.assertEqual(resp.json(), {"error": "沒有選到檔案。"})

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
            "SELECT metric, value FROM derived_metric WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchall()
        self.assertTrue(rows)  # save_derived_metrics 真的寫進 derived_metric 了


if __name__ == "__main__":
    unittest.main()
