"""app/tests/test_brand_web_cv_job_status.py — F31-I14, feature Contract J on the customer-voice
extraction status (`GET /api/library/brands/{b}/customer-voice/jobs/{job_key}`).

The status reader used to look only at `llm_task`: a job that failed before its AI call wrote no
row, so the poll read "running" forever (and the task body swallowed the exception, so the job
itself even ended `succeeded`). Now the newest job decides first. Imports legacy facades only
(this file matches no managed module's `owns`).
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.brand_web as brand_web_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.core import db as coredb
from app.core import interrupts as core_interrupts
from app.llm import gateway

ACTOR = "測試員"


class CustomerVoiceJobStatusTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # This test module has its own queue schema (conftest.py): register the brand_web
        # tasks on this module's `background.app()` again.
        brand_web_module.register(main.app)
        brand = repo.create_brand(web.conn, name="虛構茶研所－原話狀態", client_name=None,
                                  actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = brand["id"]

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _submit(self) -> str:
        resp = self.client.post(f"/api/library/brands/{self.bid}/customer-voice", json={
            "source_channel": "ptt", "raw_text": "喝了三天真的有感",
        })
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["job_key"]

    def _status(self, job_key: str) -> dict:
        return self.client.get(
            f"/api/library/brands/{self.bid}/customer-voice/jobs/{job_key}").json()

    def test_failure_before_the_ai_call_reads_failed_not_running_forever(self):
        """Red on master: the task body caught the exception (job ended `succeeded`) and no
        `llm_task` row existed, so the status read `running` forever."""
        job_key = self._submit()
        self.assertEqual(self._status(job_key), {"status": "running"})  # queued

        with mock.patch.object(gateway, "run_task", side_effect=RuntimeError("模擬前置失敗")):
            self._run_worker()

        self.assertEqual(self._status(job_key), {
            "status": "failed", "message": background_module.JOB_FAILED_MESSAGE,
        })
        self.assertEqual(repo.list_customer_voices(web.conn, self.bid), [])
        notices = [r["message"] for r in core_interrupts.list_open(web.conn, brand_id=self.bid)
                   if r["category"] == "customer_voice_extraction_done"]
        self.assertEqual(len(notices), 1)
        self.assertIn("失敗", notices[0])


if __name__ == "__main__":
    unittest.main()
