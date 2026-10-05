"""P2 studio state and scoped job destination regression."""

import app.shared.web as web
import app.workbench as workbench
from app.workbench import repository as repo

from .test_workbench_pack_api import _WorkbenchPackApiTestBase


class StudioProgressTest(_WorkbenchPackApiTestBase):
    def test_generation_states_and_tenant_scoped_destination(self):
        pack_id = self._submit_pack([self._one_set("p2", {"copy": 1})])
        brief_id = self._briefs(pack_id)[0]["id"]
        url = f"/brands/{self.brand_id}/workbench/packs/{pack_id}/sets/{brief_id}"
        self.assertEqual(
            workbench.set_action_url(web.conn, self.org_id, self.brand_id, brief_id), url
        )
        self.assertIsNone(workbench.set_action_url(web.conn, "other", self.brand_id, brief_id))
        self.assertIsNone(workbench.set_action_url(web.conn, self.org_id, "other", brief_id))
        for status in ("queued", "running", "done"):
            repo.mark_brief_status(web.conn, self.org_id, self.brand_id, brief_id, status)
            detail = repo.set_detail(web.conn, self.org_id, self.brand_id, brief_id)
            self.assertEqual(detail["generation"]["status"], status)
        repo.mark_brief_failed(
            web.conn, self.org_id, self.brand_id, brief_id, "provider unavailable"
        )
        detail = repo.set_detail(web.conn, self.org_id, self.brand_id, brief_id)
        self.assertEqual(
            detail["generation"], {"status": "failed", "error": "provider unavailable"}
        )


class SiblingSubtitleTest(_WorkbenchPackApiTestBase):
    def test_sibling_subtitle_is_the_angle_label_with_the_key_as_fallback(self):
        """F41-I02 (drill-8 #11): the set sidebar prints the angle's label, never its key; a
        key with no vocabulary row still prints itself. The vocabulary row is created through
        the brand-library HTTP door (the table belongs to another module)."""
        created = self.client.post(
            f"/api/schedule/brands/{self.brand_id}/coordinates",
            json={"dimension": "angle", "label": "權威背書", "category": ""},
        )
        self.assertEqual(created.status_code, 200, created.text)
        angle_key = created.json()["key"]
        pack_id = self._submit_pack([
            self._one_set("a", {"copy": 1}, coordinates={"angle": angle_key}),
            self._one_set("b", {"copy": 1}, coordinates={"angle": "no_such_key"}),
        ])
        brief_id = self._briefs(pack_id)[0]["id"]

        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{brief_id}")

        self.assertEqual(resp.status_code, 200, resp.text)
        angles = [sibling["angle"] for sibling in resp.json()["set"]["siblings"]]
        self.assertEqual(angles, ["權威背書", "no_such_key"])
