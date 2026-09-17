"""P2 studio state and scoped job destination regression."""
import app.shared.web as web
import app.workbench as workbench
from app.workbench import repository as repo

from .test_dashboard_jobs_boundary import _seed_running_queue_job
from .test_workbench_pack_api import _WorkbenchPackApiTestBase


class StudioProgressTest(_WorkbenchPackApiTestBase):
    def test_generation_states_and_tenant_scoped_destination(self):
        pack_id = self._submit_pack([self._one_set("p2", {"copy": 1})])
        brief_id = self._briefs(pack_id)[0]["id"]
        url = f"/app/brands/{self.brand_id}/workbench/packs/{pack_id}/sets/{brief_id}"
        self.assertEqual(workbench.set_action_url(web.conn, self.org_id, self.brand_id, brief_id), url)
        self.assertIsNone(workbench.set_action_url(web.conn, "other", self.brand_id, brief_id))
        self.assertIsNone(workbench.set_action_url(web.conn, self.org_id, "other", brief_id))
        _seed_running_queue_job(self.org_id, self.brand_id, "workbench_copy", {"brief_id": brief_id})
        jobs = self.client.get("/api/jobs/active").json()["data"]
        self.assertIn(url, [job["action_url"] for job in jobs])
        for status in ("queued", "running", "done"):
            repo.mark_brief_status(web.conn, self.org_id, self.brand_id, brief_id, status)
            detail = repo.set_detail(web.conn, self.org_id, self.brand_id, brief_id)
            self.assertEqual(detail["generation"]["status"], status)
        repo.mark_brief_failed(web.conn, self.org_id, self.brand_id, brief_id, "provider unavailable")
        detail = repo.set_detail(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(detail["generation"], {"status": "failed", "error": "provider unavailable"})
