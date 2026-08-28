"""全站進行中工作只經由各模組公開 active_jobs() 匯入 dashboard。"""

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.brand_web import routes_library, routes_products
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.intake import routes_api

from .identity_test_helpers import mint_hs256


class DashboardJobsBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="進行中工作測試品牌", client_name=None, actor="測試員", org_id=DEV_ORG_ID)
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


class DashboardJobsTenantIsolationTest(unittest.TestCase):
    """票 03-1 r1 defect 2：五個記憶體 registry 沒有 org_id 概念，過濾改在聚合端點做——
    org A 的 token 看不到 org B 品牌底下的進行中工作。"""

    def setUp(self):
        self.client = TestClient(main.app)
        for registry in (routes_api._JOBS, routes_products._research_jobs, routes_library._cv_jobs):
            registry.clear()

        a_user = uuid4()
        self.a_token = mint_hs256(sub=str(a_user), email=f"jobs-orga-{a_user.hex[:8]}@example.com")
        me_a = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {self.a_token}"}
        )
        self.org_a = me_a.json()["org"]["id"]

        b_user = uuid4()
        self.b_token = mint_hs256(sub=str(b_user), email=f"jobs-orgb-{b_user.hex[:8]}@example.com")
        me_b = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {self.b_token}"}
        )
        self.org_b = me_b.json()["org"]["id"]

        self.brand_b = bi_repo.create_brand(
            main.conn, org_id=self.org_b, name="組織B的品牌", client_name=None, actor="測試"
        )["id"]
        main.conn.commit()
        routes_products._research_jobs.set("product_test_b", {
            "brand_id": self.brand_b, "status": "running", "stage": None,
            "started_at": "2026-08-20T04:12:02+00:00",
        })

    def tearDown(self):
        for registry in (routes_api._JOBS, routes_products._research_jobs, routes_library._cv_jobs):
            registry.clear()

    def test_org_a_does_not_see_org_b_jobs(self):
        resp = self.client.get(
            "/api/jobs/active", headers={"Authorization": f"Bearer {self.a_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

    def test_org_b_sees_its_own_job(self):
        resp = self.client.get(
            "/api/jobs/active", headers={"Authorization": f"Bearer {self.b_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        jobs = resp.json()["data"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["brand_id"], self.brand_b)
