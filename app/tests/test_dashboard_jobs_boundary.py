"""全站背景工作經由 dashboard 讀佇列彙總。

F29-I05（feature Contract G）：來源從 `llm_task` 的 running 列換成 procrastinate 佇列本身
（`app.background.queue_snapshot()`）。這裡直接把工作排進這個測試模組自己的
`<schema>__queue`（沒有 worker 在跑，工作會一直停在 todo），要測「進行中」就把那一列改成
doing——跟 `app/tests/test_background.py::IsActiveTest` 同一種寫法。"""

import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.workbench as workbench
from app import ads as ads_module
from app import background
from app import meta as meta_module
from app import schedule as schedule_module
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.dashboard.routes_jobs_api import TASK_KINDS

from .identity_test_helpers import mint_hs256

ITEM_KEYS = {"brand_id", "brand_name", "kind", "status", "stage", "started_at", "action_url",
             "position", "task_name", "scope", "waited_seconds"}


def _queue_schema() -> str:
    schema = main.conn.execute("SELECT current_schema() AS s").fetchone()["s"]
    return f"{schema}__queue"


def _in_queue(sql: str, params=()) -> list:
    """Run SQL with the queue schema on the search_path: its status trigger casts to
    `procrastinate_job_status` unqualified (see IsActiveTest)."""
    main.conn.execute(f'SET LOCAL search_path TO "{_queue_schema()}"')
    cur = main.conn.execute(sql, params)
    rows = cur.fetchall() if sql.lstrip().upper().startswith("SELECT") else []
    main.conn.commit()
    return rows


def _defer(task_name: str, org_id: str, **kwargs) -> int:
    lock = f"jobs-test:{uuid4().hex}"
    assert background.enqueue(task_name, org_id=org_id, lock=lock, **kwargs)
    return _in_queue("SELECT id FROM procrastinate_jobs WHERE queueing_lock = %s", (lock,))[0]["id"]


def _set_status(job_id: int, status: str) -> None:
    _in_queue("UPDATE procrastinate_jobs SET status = %s WHERE id = %s", (status, job_id))


class QueueJobsTestCase(unittest.TestCase):
    def setUp(self):
        _in_queue("DELETE FROM procrastinate_jobs")  # events cascade; each test owns the queue
        _in_queue("DELETE FROM procrastinate_workers")  # no worker heartbeat unless a test adds one
        self.client = TestClient(main.app)


class DashboardJobsQueueTest(QueueJobsTestCase):
    def setUp(self):
        super().setUp()
        self.brand = bi_repo.create_brand(main.conn, name="進行中工作測試品牌", client_name=None,
                                          actor="測試員", org_id=DEV_ORG_ID)
        main.conn.commit()

    def test_position_spans_two_tenants_and_hides_other_jobs(self):
        b_org = f"org_other_{uuid4().hex[:8]}"
        brand_id = self.brand["id"]
        _defer("background.product_scan", b_org, brand_id="brd_elsewhere",
                       product_id="prd_b")
        sync = _defer("background.ads_external_sync", DEV_ORG_ID, brand_id=brand_id,
                      job_id="xsj_1")
        # No brand_id in its args (only org): never an item, still in the queue.
        _defer("background.meta_daily_pull", DEV_ORG_ID)
        _defer("background.ads_angles", DEV_ORG_ID, brand_id=brand_id, campaign_id="cmp_1",
               entity_id="ent_1", copy_hash="h")
        _set_status(sync, "doing")  # running jobs come first, whatever their id

        body = self.client.get("/api/jobs/active").json()

        self.assertEqual(body["total"], 4)
        self.assertEqual(body["other_count"], 2)
        jobs = body["data"]
        self.assertEqual([(j["task_name"], j["status"], j["position"]) for j in jobs], [
            ("background.ads_external_sync", "running", 1),
            ("background.ads_angles", "queued", 4),
        ])
        self.assertTrue(all(set(j) == ITEM_KEYS for j in jobs), "job args never leak")
        running, angles = jobs
        self.assertEqual(running["kind"], "ads_sync")
        self.assertEqual(running["action_url"], f"/brands/{brand_id}/ads/connections")
        self.assertTrue(running["started_at"])
        self.assertIsInstance(running["waited_seconds"], int)
        self.assertEqual(running["scope"], {})
        self.assertEqual(angles["scope"], {"campaign_id": "cmp_1", "entity_id": "ent_1"})
        self.assertEqual(angles["action_url"], f"/brands/{brand_id}/ads/campaigns/cmp_1/detail")
        self.assertEqual(angles["started_at"], "")
        self.assertEqual(angles["brand_name"], "進行中工作測試品牌")

    def test_done_and_failed_today_count_only_the_actor_org(self):
        brand_id = self.brand["id"]
        for org, end in ((DEV_ORG_ID, "succeeded"), (DEV_ORG_ID, "succeeded"),
                         (DEV_ORG_ID, "failed"), ("org_someone_else", "succeeded")):
            job = _defer("background.brand_report", org, brand_id=brand_id, actor="t")
            _set_status(job, "doing")
            _set_status(job, end)

        body = self.client.get("/api/jobs/active").json()

        self.assertEqual((body["done_today"], body["failed_today"]), (2, 1))
        self.assertEqual((body["data"], body["total"], body["other_count"]), ([], 0, 0))

    def test_existing_kinds_keep_their_screens(self):
        brand_id = self.brand["id"]
        _defer("background.intake_scan", DEV_ORG_ID, brand_id=brand_id)
        _defer("background.product_scan", DEV_ORG_ID, brand_id=brand_id, product_id="prd_test")
        _defer("background.customer_voice_extraction", DEV_ORG_ID, brand_id=brand_id,
               job_key="cv", raw_text="顧客原話不可外流")
        _defer("background.schedule_plan", DEV_ORG_ID, brand_id=brand_id)

        body = self.client.get("/api/jobs/active").json()

        self.assertEqual(
            {(j["kind"], j["action_url"]) for j in body["data"]},
            {("scan", f"/brands/{brand_id}/intake"),
             ("product_research", f"/brands/{brand_id}/products/prd_test"),
             ("library_convert", f"/brands/{brand_id}/library?tab=customer-voice"),
             ("schedule_plan", f"/brands/{brand_id}/ads")},
        )
        self.assertEqual([j["position"] for j in body["data"]], [1, 2, 3, 4])
        self.assertNotIn("顧客原話不可外流", str(body))

    def test_workbench_job_targets_its_actual_set(self):
        brand_id = self.brand["id"]
        pack_id = workbench.submit_pack(main.conn, DEV_ORG_ID, brand_id, {
            "name": "Jobs test", "source_kind": "schedule_node", "source_ref": {"p2": True},
            "sets": [{"name": "Set", "source_ref": {"p2": True}, "coordinates": {},
                      "required_outputs": {"copy": 1}, "request": {}}],
        })
        main.conn.commit()
        brief = workbench.briefs_for_source(main.conn, DEV_ORG_ID, brand_id,
                                           "schedule_node", {"p2": True})[0]
        jobs = self.client.get("/api/jobs/active").json()["data"]
        self.assertIn(f"/brands/{brand_id}/workbench/packs/{pack_id}/sets/{brief['id']}",
                      [job["action_url"] for job in jobs])
        self.assertEqual({job["kind"] for job in jobs}, {"workbench_generate"})

    def test_every_registered_background_task_has_a_label(self):
        meta_module.register_task()
        schedule_module.register_tasks()
        workbench.register_tasks()
        ads_module.register_tasks()
        names = [n for n in background.app().tasks if n.startswith("background.")]
        self.assertTrue(any(n.startswith("background.ads_") for n in names))
        missing = [n for n in names if n != "background.noop" and n not in TASK_KINDS]
        self.assertEqual(missing, [])


class DashboardJobsTenantIsolationTest(QueueJobsTestCase):
    """票 03-1 r1 defect 2 的租戶界線照舊：org A 的 token 看不到 org B 品牌底下的工作，
    只看到它排在第幾個之後（other_count）。"""

    def setUp(self):
        super().setUp()
        tokens = []
        for label in ("a", "b"):
            user = uuid4()
            token = mint_hs256(sub=str(user), email=f"jobs-org{label}-{user.hex[:8]}@example.com")
            me = self.client.get("/api/identity/me", headers={"Authorization": f"Bearer {token}"})
            tokens.append((token, me.json()["org"]["id"]))
        (self.a_token, self.org_a), (self.b_token, self.org_b) = tokens
        self.brand_b = bi_repo.create_brand(
            main.conn, org_id=self.org_b, name="組織B的品牌", client_name=None, actor="測試"
        )["id"]
        main.conn.commit()
        _defer("background.product_scan", self.org_b, brand_id=self.brand_b,
               product_id="product_test_b")

    def _get(self, token):
        resp = self.client.get("/api/jobs/active", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_org_a_does_not_see_org_b_jobs(self):
        body = self._get(self.a_token)
        self.assertEqual((body["data"], body["total"], body["other_count"]), ([], 1, 1))

    def test_org_a_brand_id_forged_into_org_b_args_is_not_listed(self):
        # A job carrying org A's id but org B's brand stays hidden (brand re-checked).
        _defer("background.brand_report", self.org_a, brand_id=self.brand_b, actor="t")
        self.assertEqual(self._get(self.a_token)["data"], [])

    def test_org_b_sees_its_own_job(self):
        jobs = self._get(self.b_token)["data"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["brand_id"], self.brand_b)
        self.assertEqual(jobs[0]["position"], 1)

    def test_stalled_only_for_the_org_whose_work_waits(self):
        """F47 Contract C: no live worker -> stalled for org B (its job waits), not for org A
        (nothing of its own queued); a fresh heartbeat clears it."""
        a, b = self._get(self.a_token), self._get(self.b_token)
        self.assertEqual((a["worker_alive"], a["stalled"]), (False, False))
        self.assertEqual((b["worker_alive"], b["stalled"]), (False, True))

        _in_queue("INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now())")
        b = self._get(self.b_token)
        self.assertEqual((b["worker_alive"], b["stalled"]), (True, False))

    def test_unknown_health_does_not_claim_stalled_or_alive(self):
        health = {"state": "unknown", "checked_at": "2026-10-08T00:00:00+00:00",
                  "last_heartbeat_at": None, "reason_code": "health_unavailable"}
        with mock.patch.object(background, "worker_health", return_value=health):
            b = self._get(self.b_token)
        self.assertEqual(b["worker_health"], health)
        self.assertEqual((b["worker_alive"], b["stalled"]), (False, False))
        self.assertEqual(len(b["data"]), 1)

    def test_a_job_without_a_brand_still_stalls_its_org(self):
        # Not listed (no brand_id), but it waits on the same stopped worker.
        _defer("background.meta_daily_pull", self.org_a)
        body = self._get(self.a_token)
        self.assertEqual((body["data"], body["stalled"]), ([], True))


if __name__ == "__main__":
    unittest.main()
