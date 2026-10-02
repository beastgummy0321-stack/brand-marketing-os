"""app/tests/test_workbench_approve.py — F02-I03: 核准整包 (ARCHITECTURE.md §5.5, `.work/
features/F02.md` "核准整包"). 完成條件's computed check (`required_outputs_met`), its human
override, the 409 `completion_incomplete` gate, the selection lock once approved, and
`pack_for_source()`'s read of the approval — the whole of the "可以下一步" signal the upstream
reads, never a callback.
"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import repository as workbench_repo

ACTOR = "測試員"


class _WorkbenchApproveTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：核准整包", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _submit_pack(self, sets: list, *, source_ref: dict | None = None) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": source_ref or {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包：核准", "summary": {"情境": "測試"}, "sets": sets,
        }
        return workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)

    def _one_set(self, node_key: str, required_outputs: dict) -> dict:
        return {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": {"copy_length": "short", "image_prompt_count": 3},
        }

    def _briefs(self, pack_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def _tick(self, pack_id: str, key: str, checked: bool = True) -> dict:
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
            json={"key": key, "checked": checked},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["pack"]

    def _approve(self, pack_id: str):
        return self.client.post(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve")


# -- 案例 1：素材組未完成 -> 409；覆寫第一項條件後成功，pack 讀「已完成」 ------------------------

class ApproveWithOverrideTest(_WorkbenchApproveTestBase):
    def test_unfinished_set_is_409_then_override_lets_it_through(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])

        blocked = self._approve(pack_id)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "completion_incomplete")

        pack = self._tick(pack_id, "required_outputs_met", True)
        item = next(i for i in pack["completion"] if i["key"] == "required_outputs_met")
        self.assertTrue(item["ok"])
        self.assertTrue(item["overridden"])

        self._tick(pack_id, "brand_rules_checked", True)
        pack = self._tick(pack_id, "ready_to_report", True)
        self.assertTrue(pack["can_approve"])

        approved = self._approve(pack_id)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["pack"]["status"], "done")

        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}"
        ).json()["pack"]
        self.assertEqual(detail["status"], "done")

        # 核准兩次是冪等的，不是錯誤
        again = self._approve(pack_id)
        self.assertEqual(again.status_code, 200)


# -- 案例 2：核准後已選定的版本不能被取消選定 ---------------------------------------------

class LockedSelectionCannotBeDeselectedTest(_WorkbenchApproveTestBase):
    def test_selected_version_cannot_be_deselected_after_approve(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        self._tick(pack_id, "brand_rules_checked", True)
        self._tick(pack_id, "ready_to_report", True)
        approved = self._approve(pack_id)
        self.assertEqual(approved.status_code, 200)

        deselect = self.client.delete(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
            f"/versions/{outputs[0]['id']}/select"
        )
        self.assertEqual(deselect.status_code, 409)
        self.assertEqual(deselect.json()["error"]["code"], "pack_approved")


# -- 案例 2b：F47 Q7，覆蓋核准後只開放還缺的那一部分 ----------------------------------------

class OverrideApprovedPackRecoversTest(_WorkbenchApproveTestBase):
    def _write(self, brief_id: str, part: str, n: int = 2) -> list:
        return workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part=part, generation_round=1, body_json=[{"sets": []}] * n,
            coordinates_json=None, llm_task_id=None,
        )

    def _set_url(self, brief_id: str) -> str:
        return f"/api/workbench/brands/{self.brand_id}/sets/{brief_id}"

    def test_missing_part_stays_open_and_selected_part_stays_locked(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1, "image_prompt": 1})])
        brief = self._briefs(pack_id)[0]
        workbench_repo.mark_brief_status(web.conn, self.org_id, self.brand_id, brief["id"], "done")
        copies = self._write(brief["id"], "copy")
        images = self._write(brief["id"], "image_prompt")
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, copies[0]["id"])
        for key in ("required_outputs_met", "brand_rules_checked", "ready_to_report"):
            self._tick(pack_id, key, True)
        self.assertEqual(self._approve(pack_id).status_code, 200)

        pack = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}"
        ).json()["pack"]
        self.assertEqual(pack["approved_gap"], {
            "missing": 1, "set_id": brief["id"], "label": "已核准・還缺 1 組",
        })
        detail = self.client.get(self._set_url(brief["id"])).json()["set"]
        self.assertEqual(detail["lock"]["open_parts"], ["image_prompt"])
        self.assertTrue(detail["products"]["copy"]["locked"])
        self.assertFalse(detail["products"]["image_prompt"]["locked"])

        # The selected part refuses any change: deselect, another select, a new round.
        url = self._set_url(brief["id"])
        refused = [
            self.client.delete(f"{url}/versions/{copies[0]['id']}/select"),
            self.client.post(f"{url}/versions/{copies[1]['id']}/select"),
            self.client.post(f"{url}/products/copy/run", json={}),
        ]
        for resp in refused:
            self.assertEqual(resp.status_code, 409)
            self.assertEqual(resp.json()["error"]["code"], "pack_approved")

        # The missing part can be generated and selected.
        run = self.client.post(f"{url}/products/image_prompt/run", json={})
        self.assertEqual(run.status_code, 200)
        workbench_repo.mark_brief_status(web.conn, self.org_id, self.brand_id, brief["id"], "done")
        picked = self.client.post(f"{url}/versions/{images[0]['id']}/select")
        self.assertEqual(picked.status_code, 200)
        after = picked.json()["set"]
        self.assertEqual(after["status"], "已完成")
        self.assertTrue(after["lock"]["locked"])

        # Once selected it locks like the rest.
        again = self.client.delete(f"{url}/versions/{images[0]['id']}/select")
        self.assertEqual(again.status_code, 409)
        pack = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}"
        ).json()["pack"]
        self.assertIsNone(pack["approved_gap"])


# -- 案例 3：pack_for_source 讀得到核准；不同 source_ref／不同組織讀不到 ------------------------

class PackForSourceApprovalTest(_WorkbenchApproveTestBase):
    def test_pack_for_source_reads_approval_scoped_by_source_ref_and_org(self):
        source_ref = {"source_tree_task_id": "tree_approve_read"}
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})], source_ref=source_ref)
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        self._tick(pack_id, "brand_rules_checked", True)
        self._tick(pack_id, "ready_to_report", True)
        self.assertEqual(self._approve(pack_id).status_code, 200)

        found = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", source_ref,
        )
        assert found is not None
        self.assertIsNotNone(found["approved_at"])

        other_ref = workbench_module.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node",
            {"source_tree_task_id": "tree_does_not_exist"},
        )
        self.assertIsNone(other_ref)

        org_b = "org_workbench_approve_isolation"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_b, org_b),
        )
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：核准隔離", client_name=None, actor=ACTOR,
        )
        web.conn.commit()
        other_org = workbench_module.pack_for_source(
            web.conn, org_b, brand_b["id"], "schedule_node", source_ref,
        )
        self.assertIsNone(other_org)


# -- 案例 4：F02-I17，`GET /sets/{s}` 的 `source_kind`／`lock` ------------------------------

class SetDetailSourceKindAndLockTest(_WorkbenchApproveTestBase):
    def test_set_detail_reports_source_kind_and_lock(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]

        before = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        self.assertEqual(before["source_kind"], "schedule_node")
        self.assertFalse(before["lock"]["locked"])
        self.assertIsNone(before["lock"]["reason"])

        self._tick(pack_id, "brand_rules_checked", True)
        self._tick(pack_id, "ready_to_report", True)
        # copy 沒有選定版本也可以核准——這個案例只在乎鎖定訊號，不是完成條件。
        self._tick(pack_id, "required_outputs_met", True)
        self.assertEqual(self._approve(pack_id).status_code, 200)

        # F47 Q7: approved with copy still missing -> the set stays open for copy only.
        after = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        self.assertFalse(after["lock"]["locked"])
        self.assertEqual(after["lock"]["open_parts"], ["copy"])
        self.assertEqual(after["lock"]["reason"], workbench_repo.PACK_APPROVED_GAP_MESSAGE)

        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])
        done = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        self.assertTrue(done["lock"]["locked"])
        self.assertEqual(done["lock"]["reason"], workbench_repo.PACK_APPROVED_MESSAGE)

    def test_free_job_set_reports_free_job_source_kind(self):
        pack = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json={
                "name": "自由工作測試", "free_text": "測試",
                "sets": [{
                    "name": "唯一素材組", "coordinates": {}, "style_key": "ugc",
                    "required_outputs": {"copy": 1}, "request": {"copy_length": "short"},
                }],
                "summary": {},
            },
        ).json()["pack"]
        brief = self._briefs(pack["id"])[0]
        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
        ).json()["set"]
        self.assertEqual(detail["source_kind"], "free_job")


if __name__ == "__main__":
    unittest.main()
