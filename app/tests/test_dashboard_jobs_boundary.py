"""全站進行中工作只經由各模組公開 active_jobs() 匯入 dashboard。"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.brand_web import routes_library, routes_products
from app.intake import routes_api


class DashboardJobsBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="進行中工作測試品牌", client_name=None, actor="測試員")
        for registry in (routes_api._JOBS, routes_products._research_jobs, routes_library._cv_jobs):
            registry.clear()

    def tearDown(self):
        for registry in (routes_api._JOBS, routes_products._research_jobs, routes_library._cv_jobs):
            registry.clear()

    def test_active_jobs_are_normalized_by_owning_modules(self):
        brand_id = self.brand["id"]
        routes_api._JOBS.set(brand_id, {
            "kind": "scan", "status": "running", "stage": "讀取網址中",
            "started_at": "2026-08-20T04:11:02+00:00",
        })
        routes_products._research_jobs.set("product_test", {
            "brand_id": brand_id, "status": "waiting", "stage": None,
            "started_at": "2026-08-20T04:12:02+00:00",
        })
        routes_library._cv_jobs.set("cvjob_test", {
            "brand_id": brand_id, "status": "running", "started_at": None,
        })
        routes_api._JOBS.set("terminal_job", {
            "kind": "scan", "status": "done", "stage": "完成", "started_at": "2026-08-20T04:13:02+00:00",
        })

        response = self.client.get("/api/jobs/active")

        self.assertEqual(response.status_code, 200)
        jobs = response.json()["data"]
        self.assertEqual({job["kind"] for job in jobs}, {"scan", "product_research", "library_convert"})
        self.assertTrue(all(job["status"] in {"running", "waiting"} for job in jobs))
        self.assertTrue(all(job["brand_name"] == "進行中工作測試品牌" for job in jobs))
        self.assertEqual(
            {job["action_url"] for job in jobs},
            {f"/app/brands/{brand_id}/intake", f"/app/brands/{brand_id}/products/product_test", f"/app/brands/{brand_id}/library"},
        )
        expected_keys = {"brand_id", "brand_name", "kind", "status", "stage", "started_at", "action_url"}
        self.assertTrue(all(set(job) == expected_keys for job in jobs))
        self.assertEqual(next(job for job in jobs if job["kind"] == "product_research")["stage"], "")
        self.assertEqual(next(job for job in jobs if job["kind"] == "library_convert")["started_at"], "")
