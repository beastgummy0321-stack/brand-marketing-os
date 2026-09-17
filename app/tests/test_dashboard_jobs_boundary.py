"""全站進行中工作經由 dashboard 直接讀佇列彙總（票 08：品牌智庫抽原話／產品調研／顧問
報告搬上 `app.background` 佇列；票 09：建檔初掃／出題／貼回修格式／人物誌生成跟進——最後
四個 kind 也不再有行程內字典可以讀，狀態改讀 `llm_task`）。"""

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core.db import DEV_ORG_ID  # noqa: E402

from .identity_test_helpers import mint_hs256


def _seed_running_queue_job(org_id: str, brand_id: str, task_type: str, context_scope: dict) -> None:
    """直接插一列 `status = 'running'` 的 llm_task，比照 `app/tests/test_background.py`
    既有的手動 INSERT 寫法——七個 kind 搬上佇列後，dashboard 的聚合端點直接讀這張表
    （見 `app/dashboard/routes_jobs_api.py::_queue_active_jobs`），不再有字典可以 `.set()`。"""
    main.conn.execute(
        "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
        " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
        " brand_version, prompt_template_id, prompt_template_version, provider, model,"
        " status, attempt_no, started_at)"
        " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
        " 'running', 1, %s)",
        (coredb.new_id("llm"), org_id, brand_id, task_type, coredb.jsonb(context_scope),
         coredb.now_utc()),
    )
    main.conn.commit()


class DashboardJobsBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="進行中工作測試品牌", client_name=None, actor="測試員", org_id=DEV_ORG_ID)

    def test_active_jobs_are_normalized_by_owning_modules(self):
        brand_id = self.brand["id"]
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "intake_scan", {"brand_id": brand_id})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "product_scan", {"product_id": "prd_test"})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "customer_voice_extraction", {"job_key": "cvjob_test"})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "brand_report", {})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "intake_persona", {"brand_id": brand_id})
        # issue jobs-bell-blind-to-schedule-jobs：產品裡最慢的三個工作，2026-09-06 演練前
        # 一個都不在這份聚合裡——按下「產素材」的同時鈴鐺寫「目前沒有進行中的背景工作」。
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "schedule_plan", {"brand_id": brand_id})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "schedule_tree", {"brand_id": brand_id})
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "workbench_copy", {"brand_id": brand_id})
        # 票 F07-I02：品牌視覺推導在圖片回合裡跑，鈴鐺要看得到它，不能只看得到外層的
        # workbench_image_prompt。
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "workbench_derive_identity", {"brand_id": brand_id})

        response = self.client.get("/api/jobs/active")

        self.assertEqual(response.status_code, 200)
        jobs = response.json()["data"]
        # 票 08／09 done-check：搬上佇列的 kind 都要點名斷言（含票 09 done-check 4 的
        # 人物誌生成）——半調的聚合悄悄漏掉一個 kind 是這張票最容易犯的錯，光看「有東西
        # 回來」看不出來哪個 kind 不見了。
        self.assertEqual(
            {job["kind"] for job in jobs},
            {"scan", "product_research", "library_convert", "brand_report", "persona",
             "schedule_plan", "schedule_tree", "workbench_generate"},
        )
        self.assertTrue(all(job["status"] in {"running", "waiting"} for job in jobs))
        self.assertTrue(all(job["brand_name"] == "進行中工作測試品牌" for job in jobs))
        self.assertEqual(
            {job["action_url"] for job in jobs},
            {
                f"/app/brands/{brand_id}/intake",
                f"/app/brands/{brand_id}/products/prd_test",
                f"/app/brands/{brand_id}/library?tab=customer-voice",
                f"/app/brands/{brand_id}/report",
                f"/app/brands/{brand_id}/ads",
                f"/app/brands/{brand_id}/workbench",
            },
        )
        expected_keys = {"brand_id", "brand_name", "kind", "status", "stage", "started_at", "action_url"}
        self.assertTrue(all(set(job) == expected_keys for job in jobs))
        # 逐步進度（票 08／09 明文放棄）：running 一律回固定字串，不是 seed 進去的值。
        self.assertEqual(next(job for job in jobs if job["kind"] == "scan")["stage"], "讀取網址中")
        self.assertEqual(next(job for job in jobs if job["kind"] == "product_research")["stage"], "讀取網址中")
        self.assertTrue(next(job for job in jobs if job["kind"] == "library_convert")["started_at"])
        self.assertEqual(next(job for job in jobs if job["kind"] == "brand_report")["stage"], "正在整理五章")
        self.assertEqual(next(job for job in jobs if job["kind"] == "persona")["stage"], "整理人物誌")
        self.assertEqual(
            next(job for job in jobs if job["kind"] == "workbench_generate")["stage"], "素材生成中")
        # 兩列（workbench_copy、workbench_derive_identity）都要落到 workbench_generate；
        # 只留其中一列也會讓上面兩個斷言通過，所以另外點名數量，讓少收一個 kind 這種
        # 半調閘門露出來。
        self.assertEqual(
            sum(1 for job in jobs if job["kind"] == "workbench_generate"), 2)

    def test_workbench_derive_identity_alone_maps_to_generate_stage(self):
        # F07-I13：上面那個測試同時塞了 workbench_copy 和 workbench_derive_identity，
        # `next(...)` 只看到排第一個的那列，改錯 routes_jobs_api.py 裡
        # workbench_derive_identity 對應的 stage 字串不會讓上面的斷言變紅。這裡只塞
        # 一列 workbench_derive_identity，單獨盯住它的 stage。
        brand_id = self.brand["id"]
        _seed_running_queue_job(DEV_ORG_ID, brand_id, "workbench_derive_identity", {"brand_id": brand_id})

        response = self.client.get("/api/jobs/active")

        self.assertEqual(response.status_code, 200)
        jobs = [job for job in response.json()["data"] if job["brand_id"] == brand_id]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["kind"], "workbench_generate")
        self.assertEqual(jobs[0]["stage"], "素材生成中")


class DashboardJobsTenantIsolationTest(unittest.TestCase):
    """票 03-1 r1 defect 2：intake 的行程內 registry 沒有 org_id 概念，過濾改在聚合端點做
    ——org A 的 token 看不到 org B 品牌底下的進行中工作；票 08 起，其餘三個 kind 改讀
    `llm_task`（本身就有 org_id 欄位），走同一條過濾迴圈；票 09 起，七個 kind 全部同一套。"""

    def setUp(self):
        self.client = TestClient(main.app)

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
        _seed_running_queue_job(self.org_b, self.brand_b, "product_scan", {"product_id": "product_test_b"})

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
