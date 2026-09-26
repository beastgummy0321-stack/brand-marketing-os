"""顧問分析報告 React API：資料形狀、兩分鐘守門與背景工作狀態。

票 08：報告生成從行程內 dict＋thread 搬上 `app.background` 佇列，狀態端點改讀
`llm_task`（見 `app/brand_web/routes_report_api.py`）。"""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.brand_web as brand_web_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import report_service
from app.core import db as coredb
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.llm import providers

ACTOR = "測試員"


def _sections(tag: str) -> dict:
    return {
        "positioning": {"summary": f"{tag}定位摘要", "points": ["定位重點"]},
        "market": {"summary": f"{tag}市場摘要", "points": ["市場重點"]},
        "audience": {"summary": f"{tag}受眾摘要", "points": ["受眾重點"]},
        "claims": {"summary": f"{tag}宣稱摘要", "points": ["宣稱重點"]},
        "rhythm": {"summary": f"{tag}節奏摘要", "points": ["節奏重點"]},
    }


def _provider(tag: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=json.dumps(_sections(tag), ensure_ascii=False), structured=None,
        usage=providers.Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn",
    ))


class BrandReportApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # 票 08：這個測試模組自己有一份 schema（見 conftest.py），要重新掛一次
        # `background.brand_report`——DSN 換了 App 整顆重建，跟 `test_schedule.py`
        # `schedule_module.register_tasks()` 同一個理由。
        brand_web_module.register(main.app)

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _brand_with_report(self, fact_count: int):
        brand = repo.create_brand(web.conn, name=f"報告 API 測試 {fact_count}", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        for index in range(fact_count):
            repo.create_brand_fact(
                web.conn, brand["id"], fact_type="positioning", label=f"事實 {index}",
                value=f"內容 {index}", status="confirmed", confirmed_by=ACTOR, actor=ACTOR,
            )
        ok, error = report_service.generate(
            web.conn, brand["id"], ACTOR, provider=_provider(brand["name"])
        )
        self.assertTrue(ok, error)
        return brand

    def test_generate_with_provider_keeps_default_provider_unchanged(self):
        brand = repo.create_brand(web.conn, name="注入 Provider 報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        default_provider = report_service.PROVIDER

        ok, error = report_service.generate(
            web.conn, brand["id"], ACTOR, provider=_provider(brand["name"])
        )

        self.assertTrue(ok, error)
        self.assertIs(report_service.PROVIDER, default_provider)

    def test_get_returns_fixed_five_sections_and_thin_data_boundary(self):
        four = self._brand_with_report(4)
        five = self._brand_with_report(5)

        four_data = self.client.get(f"/api/brands/{four['id']}/report").json()
        five_data = self.client.get(f"/api/brands/{five['id']}/report").json()

        self.assertEqual(
            [item["label"] for item in four_data["report"]["sections"]],
            ["品牌定位", "市場與競爭觀察", "受眾洞察", "可用宣稱與紅線", "建議節奏方向"],
        )
        self.assertTrue(four_data["report"]["thin_data"])
        self.assertFalse(five_data["report"]["thin_data"])
        self.assertEqual(four_data["job"], {"status": "idle"})

    def test_recent_post_is_rejected_with_exact_message(self):
        brand = self._brand_with_report(0)

        response = self.client.post(f"/api/brands/{brand['id']}/report/generate")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"detail"})

    def test_generate_via_queue_runs_worker_and_produces_report(self):
        """票 08：完整走一次 enqueue → worker → GET，證明佇列接線本身是通的（其餘測試
        直接呼叫 `report_service.generate()`，繞過佇列）。"""
        brand = repo.create_brand(web.conn, name="佇列生成報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        orig_provider = report_service.PROVIDER
        report_service.PROVIDER = _provider(brand["name"])
        try:
            resp = self.client.post(f"/api/brands/{brand['id']}/report/generate")
            self.assertEqual(resp.status_code, 200)
            self._run_worker()
        finally:
            report_service.PROVIDER = orig_provider

        data = self.client.get(f"/api/brands/{brand['id']}/report").json()
        self.assertIsNotNone(data["report"])
        self.assertEqual(data["job"], {"status": "idle"})

    def test_get_exposes_running_job(self):
        """票 08 done-check 3（重啟測試，顧問報告是三個裡最簡單的一個）：狀態端點只認
        `llm_task` 裡 `status = 'running'` 的那一列——這個 process 有沒有被殺掉重開，
        讀到的東西不變（它沒有行程內字典可以讀，那個字典已經被這張票刪掉了）。這裡直接
        造一列 `running` 的 llm_task，比照 `app/tests/test_background.py` 既有的手動
        INSERT 寫法：模擬「enqueue 之後、worker 正在跑到一半、process 被殺掉重開」那一刻
        的資料庫真實狀態，不必真的开一條背景執行緒卡住等（那一半的行為本來就在
        `test_background.py::WorkerProcessTest` 驗過——process 死掉留下的
        running 列會被下一個 worker 的 `fail_interrupted_tasks()` 掃到；這裡驗的是
        「process 還沒被下一個 worker 掃到之前，狀態端點讀不讀得到這一列」）。

        證紅一次（人工核對，不留在自動化測試裡）：把 `_job_shape()` 的讀法暫時指回一顆
        空字典，這個測試會看到 `job.status == "idle"`，不是 `"running"`；改回來就恢復。"""
        brand = repo.create_brand(web.conn, name="執行中報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        web.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, 'brand_report', '{}', '[]', '', '[]', 1, 'p', 'v1',"
            " 'seed', 'seed', 'running', 1, %s)",
            (coredb.new_id("llm"), DEV_ORG_ID, brand["id"], coredb.now_utc()),
        )
        web.conn.commit()

        response = self.client.get(f"/api/brands/{brand['id']}/report")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report"], None)
        self.assertEqual(response.json()["job"]["status"], "running")

    def test_second_generate_while_first_is_claimed_but_not_yet_calling_provider_is_refused(self):
        """票 08 round 2 done-check 9 — the exact reproduction from the ticket's "Blocked"
        section, now refused: a worker has claimed the job (procrastinate moved it
        `todo` -> `doing`) but `context_compiler.compile()` — the work `report_service.generate`
        does before the paid provider call — has not returned yet. Round 1's code read
        `_job_shape()` (backed by `llm_task`) for the 400 check, whose `running` row does not
        exist yet in this window, so the second press was wrongly accepted and the provider
        was called twice. Proven red once against round 1's code (reverting
        `routes_report_api.py`'s gate back to the `llm_task` read): this test saw 2 rows / 2
        provider calls; restored after."""
        import threading

        brand = repo.create_brand(web.conn, name="重複按報告測試", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        started = threading.Event()
        release = threading.Event()
        orig_compile = report_service.context_compiler.compile

        def _blocking_compile(conn, brand_id):
            started.set()
            release.wait(timeout=5)
            return orig_compile(conn, brand_id)

        orig_provider = report_service.PROVIDER
        fake_provider = _provider(brand["name"])
        report_service.PROVIDER = fake_provider
        report_service.context_compiler.compile = _blocking_compile
        worker_thread = None
        try:
            resp1 = self.client.post(f"/api/brands/{brand['id']}/report/generate")
            self.assertEqual(resp1.status_code, 200)
            web.conn.commit()

            worker_thread = threading.Thread(
                target=lambda: background_module.app().run_worker(wait=False)
            )
            worker_thread.start()
            self.assertTrue(started.wait(timeout=5), "worker never claimed the job")

            resp2 = self.client.post(f"/api/brands/{brand['id']}/report/generate")
            self.assertEqual(resp2.status_code, 400)
        finally:
            release.set()
            if worker_thread is not None:
                worker_thread.join(timeout=5)
            report_service.context_compiler.compile = orig_compile
            report_service.PROVIDER = orig_provider

        rows = web.conn.execute(
            "SELECT COUNT(*) AS c FROM llm_task WHERE brand_id = %s AND task_type = 'brand_report'",
            (brand["id"],),
        ).fetchone()
        self.assertEqual(rows["c"], 1)
        self.assertEqual(len(fake_provider.calls), 1)

    def _generate_via_queue(self, brand, provider) -> dict:
        orig_provider = report_service.PROVIDER
        report_service.PROVIDER = provider
        try:
            self.assertEqual(
                self.client.post(f"/api/brands/{brand['id']}/report/generate").status_code, 200)
            self._run_worker()
        finally:
            report_service.PROVIDER = orig_provider
        return self.client.get(f"/api/brands/{brand['id']}/report").json()

    def test_save_failure_after_ai_success_reads_failed(self):
        """F31-I02 (Contract J): the AI call succeeded but saving the report raised. The
        handler notifies and re-raises, so the job ends `failed`. Red on master: the
        exception was swallowed and the succeeded `llm_task` row read `idle`."""
        brand = repo.create_brand(web.conn, name="報告存檔失敗", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        with mock.patch.object(repo, "create_brand_report", side_effect=RuntimeError("模擬存檔失敗")):
            data = self._generate_via_queue(brand, _provider(brand["name"]))
        self.assertIsNone(data["report"])
        self.assertEqual(data["job"], {"status": "failed",
                                       "message": background_module.JOB_FAILED_MESSAGE})

    def test_unreadable_reply_reads_failed_not_idle(self):
        """F31-I02: the AI answered but the reply is not five chapters, so no report was
        saved. Red on master: the succeeded `llm_task` row read `idle`."""
        brand = repo.create_brand(web.conn, name="報告讀不懂", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        garbage = providers.FakeProvider(response=providers.ProviderResponse(
            output_text="這不是五章的 JSON", structured=None,
            usage=providers.Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn",
        ))
        data = self._generate_via_queue(brand, garbage)
        self.assertEqual(data["job"]["status"], "failed")
        self.assertEqual(data["job"]["message"], report_service.brand_report_mod.PARSE_FAIL_MESSAGE)

    def test_new_job_queued_behind_an_older_report_reads_running(self):
        """F31-I02 (Contract J): the newest job decides first. Red on master: the older
        succeeded `llm_task` row read `idle` while the new job waited in the queue."""
        brand = repo.create_brand(web.conn, name="排隊中的報告", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.assertEqual(self._generate_via_queue(brand, _provider(brand["name"]))["job"],
                         {"status": "idle"})

        background_module.enqueue("background.brand_report", org_id=DEV_ORG_ID,
                                  lock=f"brand_report:{brand['id']}", brand_id=brand["id"], actor=ACTOR)
        web.conn.commit()
        job = self.client.get(f"/api/brands/{brand['id']}/report").json()["job"]

        self.assertEqual(job["status"], "running")
        self.assertIsInstance(job["started_at"], str)
        orig_provider = report_service.PROVIDER
        report_service.PROVIDER = _provider(brand["name"])
        try:
            self._run_worker()  # drain the queued job so no later test's worker picks it up
        finally:
            report_service.PROVIDER = orig_provider

    def test_missing_brand_returns_json_404_for_get_and_post(self):
        brand_id = "missing-brand"

        get_response = self.client.get(f"/api/brands/{brand_id}/report")
        post_response = self.client.post(f"/api/brands/{brand_id}/report/generate")

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(set(get_response.json()), {"detail"})
        self.assertEqual(post_response.status_code, 404)
        self.assertEqual(set(post_response.json()), {"detail"})
