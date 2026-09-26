"""app/tests/test_schedule_job_status.py — F31-I14, feature Contract J on the schedule readers.

`state._latest_task_row()` / `_display_task_row()` (plan and tree, `GET /api/schedule/brands/{b}`)
and `diagnosis._round_rows()` (`GET .../diagnosis`, and the adopt route) used to look only at
`llm_task`. A job still queued behind an older row read as the older row's finished state, and a
job that failed before its AI call wrote no row at all, so it was invisible. Now the newest job
decides first. Real procrastinate against this module's own queue schema (conftest.py); every
provider is a FakeProvider and the failing runs raise before any provider call.
"""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.schedule as schedule_module
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.llm import providers
from app.schedule import diagnosis as diagnosis_mod
from app.schedule import jobs as schedule_jobs
from app.schedule import state as schedule_state

ACTOR = "測試員"
_DATA = schedule_state._load_platform_data()
_PLATFORM = next(p["id"] for p in _DATA["platforms"] if p["enabled"])
_OBJECTIVE = next(o["value"] for o in _DATA["objectives"] if o["platform"] == _PLATFORM)


def _fake_plans() -> providers.FakeProvider:
    plans = [{
        "summary": "主打驗證過的受眾，小額測試新概念。",
        "reasoning": "過去表現穩定，先守住再小額試新的。",
        "splits": [
            {"label": "主力方向", "share": 0.7, "why": "已驗證的受眾，先守住"},
            {"label": "測試方向", "share": 0.3, "why": "新概念，小額試"},
        ],
    }]
    body = json.dumps({"plans": plans}, ensure_ascii=False)
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=f"說明文字。\n\n```json\n{body}\n```", structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # This module has its own queue schema (conftest.py): register the schedule tasks on
        # this module's `background.app()` again.
        schedule_module.register_tasks()
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="虛構茶飲－工作狀態", client_name=None,
            actor=ACTOR,
        )["id"]
        self._orig_provider = schedule_jobs.PROVIDER
        self.addCleanup(setattr, schedule_jobs, "PROVIDER", self._orig_provider)

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)


class PlanJobStatusTest(_Base):
    def setUp(self):
        super().setUp()
        self.product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="虛構蜂蜜柚子茶", actor=ACTOR)["id"]
        rule_cards.set_value(web.conn, self.brand_id, "schedule_budget", "daily_budget",
                             3000.0, ACTOR, org_id=coredb.DEV_ORG_ID)

    def _post_plan(self):
        resp = self.client.post(f"/api/schedule/brands/{self.brand_id}/plans", json={
            "product_ids": [self.product_id], "platform": _PLATFORM, "objective": _OBJECTIVE,
            "promotion_note": "", "plan_count": 1,
            "start_date": "2026-09-10", "end_date": "2026-09-24",
        })
        self.assertEqual(resp.status_code, 200, resp.text)

    def _plan(self) -> dict | None:
        return self.client.get(f"/api/schedule/brands/{self.brand_id}").json()["plan"]

    def _run_worker_failing_before_the_ai_call(self, fake) -> None:
        with mock.patch.object(schedule_jobs, "_compile_brand_context",
                               side_effect=RuntimeError("模擬前置失敗")):
            self._run_worker()
        self.assertEqual(fake.calls, [], "the failing run must stop before any provider call")

    def test_first_plan_failing_before_the_ai_call_reads_failed(self):
        """Red on master: no `llm_task` row was written, so `plan` stayed null — the failure
        was invisible."""
        fake = _fake_plans()
        schedule_jobs.PROVIDER = fake
        self._post_plan()
        self._run_worker_failing_before_the_ai_call(fake)

        plan = self._plan()
        self.assertIsNotNone(plan)
        self.assertFalse(plan["running"])
        self.assertEqual(plan["failure"], background_module.JOB_FAILED_MESSAGE)
        self.assertEqual(plan["plans"], [])

    def test_rerun_queued_behind_a_finished_plan_reads_running_then_failed(self):
        """Red on master: while the rerun waited in the queue the older succeeded row won
        (`running` false), and after it failed before its AI call the old plan still showed
        with no failure."""
        schedule_jobs.PROVIDER = _fake_plans()
        self._post_plan()
        self._run_worker()
        first = self._plan()
        self.assertFalse(first["running"])
        self.assertEqual(len(first["plans"]), 1)

        fake = _fake_plans()
        schedule_jobs.PROVIDER = fake
        self._post_plan()  # queued, not yet picked up
        queued = self._plan()
        self.assertTrue(queued["running"])
        self.assertEqual(queued["task_id"], first["task_id"])  # last good plan stays visible
        # the plan being replaced cannot be expanded while its replacement is queued
        resp = self.client.post(f"/api/schedule/brands/{self.brand_id}/tree",
                                json={"plan_index": 0})
        self.assertEqual(resp.status_code, 400, resp.text)

        self._run_worker_failing_before_the_ai_call(fake)

        failed = self._plan()
        self.assertFalse(failed["running"])
        self.assertEqual(failed["failure"], background_module.JOB_FAILED_MESSAGE)


class DiagnosisJobStatusTest(_Base):
    _SUGGESTION = {
        "dimension": "audience", "coordinate_key": "cold_problem_aware",
        "coordinate_label": "陌生・知道問題", "direction": "scale_up", "impact_spend": 500.0,
        "headline": "下一輪把預算往「陌生・知道問題」加碼", "evidence": "保守 ROAS 2.58x",
        "agreed_by": ["budget"],
    }

    def _insert_finished_round(self) -> None:
        round_id = coredb.new_id("dgr")
        for lens in diagnosis_mod.LENSES:
            web.conn.execute(
                "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
                " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
                " brand_version, prompt_template_id, prompt_template_version, provider, model,"
                " status, attempt_no, started_at, structured_output_json)"
                " VALUES (%s, %s, %s, %s, %s, '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
                " 'succeeded', 1, %s, %s)",
                (coredb.new_id("llm"), coredb.DEV_ORG_ID, self.brand_id,
                 schedule_state.DIAGNOSIS_TASK_TYPE,
                 coredb.jsonb({"brand_id": self.brand_id, "round_id": round_id, "lens": lens}),
                 coredb.now_utc(),
                 coredb.jsonb([self._SUGGESTION]) if lens == "budget" else None),
            )
        web.conn.commit()

    def _diagnosis(self) -> dict:
        return self.client.get(f"/api/schedule/brands/{self.brand_id}/diagnosis").json()

    def _run_worker_failing_before_the_ai_call(self) -> None:
        fake = _fake_plans()
        schedule_jobs.PROVIDER = fake
        with mock.patch.object(diagnosis_mod, "compress",
                               side_effect=RuntimeError("模擬前置失敗")):
            self._run_worker()
        self.assertEqual(fake.calls, [], "the failing run must stop before any provider call")

    def _run(self) -> dict:
        resp = self.client.post(f"/api/schedule/brands/{self.brand_id}/diagnosis", json={})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_first_round_failing_before_the_ai_call_reads_failed(self):
        """Red on master: no row was written, so the status stayed null (never judged)."""
        self._run()
        self._run_worker_failing_before_the_ai_call()

        body = self._diagnosis()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["suggestions"], [])

    def test_round_queued_behind_a_finished_one_reads_running_then_failed(self):
        """Red on master: the queued round read as the previous round's `succeeded` with its
        suggestions still adoptable, and after it failed before its AI call it kept reading
        `succeeded`."""
        self._insert_finished_round()
        self.assertEqual(self._diagnosis()["status"], "succeeded")

        self.assertEqual(self._run()["status"], "running")  # the POST response itself
        body = self._diagnosis()
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["suggestions"], [])
        adopt = self.client.post(f"/api/schedule/brands/{self.brand_id}/diagnosis/adopt",
                                 json={"suggestion_index": 0})
        self.assertEqual(adopt.status_code, 400, adopt.text)
        self.assertEqual(bi_repo.list_rules_for_brand(web.conn, self.brand_id), [])

        self._run_worker_failing_before_the_ai_call()

        body = self._diagnosis()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
