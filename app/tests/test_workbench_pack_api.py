"""app/tests/test_workbench_pack_api.py — F02-I03: `/api/workbench/*`'s pack/set surface over
HTTP (`.work/features/F02.md` "API surface"). Fixture shape from `app/tests/test_workbench_api.
py`/`test_schedule.py:626-680` (`TestClient(main.app)`, `_headers(token, org_id)`, each test
module's own fresh `background.app()` needing `register_tasks()` called again). Packs are
seeded directly through `workbench_repo.submit_pack()` (the real upstream door, exercised end
to end in `test_workbench_pack.py`) so these tests only exercise the HTTP/JSON layer this
issue adds; `POST /packs` (自由創作) is the one write path tested over HTTP itself.
"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.identity import repository as identity_repo
from app.workbench import repository as workbench_repo

from .identity_test_helpers import mint_hs256

ACTOR = "測試員"


class _WorkbenchPackApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：任務包 API", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_workbench_pack_api_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid.uuid4()
        email = f"workbench-pack-api-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _one_set(self, node_key: str, required_outputs: dict, **overrides) -> dict:
        s = {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": {"copy_length": "short", "image_prompt_count": 3},
        }
        s.update(overrides)
        return s

    def _submit_pack(self, sets: list, *, brand_id: str | None = None,
                      org_id: str | None = None, **overrides) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包", "summary": {"情境": "測試情境"}, "sets": sets,
        }
        pack.update(overrides)
        return workbench_repo.submit_pack(
            web.conn, org_id or self.org_id, brand_id or self.brand_id, pack,
        )

    def _briefs(self, pack_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：列表 filters／sorts／q ------------------------------------------------------

class ListPacksTest(_WorkbenchPackApiTestBase):
    def test_status_filter_and_q_and_sort(self):
        pending_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        done_id = self._submit_pack(
            [self._one_set("2", {"copy": 1})],
            name="另一包 咖啡因", summary={"情境": "另一種情境"},
        )
        brief = self._briefs(done_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        all_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs")
        self.assertEqual(all_resp.status_code, 200)
        ids = [p["id"] for p in all_resp.json()["packs"]]
        self.assertIn(pending_id, ids)
        self.assertIn(done_id, ids)

        pending_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=pending"
        )
        pending_ids = [p["id"] for p in pending_resp.json()["packs"]]
        self.assertIn(pending_id, pending_ids)
        self.assertNotIn(done_id, pending_ids)

        awaiting_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=awaiting_approval"
        )
        awaiting_ids = [p["id"] for p in awaiting_resp.json()["packs"]]
        self.assertIn(done_id, awaiting_ids)
        self.assertNotIn(pending_id, awaiting_ids)

        q_resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs?q=咖啡因")
        q_ids = [p["id"] for p in q_resp.json()["packs"]]
        self.assertEqual(q_ids, [done_id])

        sort_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?sort=progress"
        )
        sort_ids = [p["id"] for p in sort_resp.json()["packs"]]
        self.assertEqual(sort_ids[0], done_id)

    def test_status_and_sort_unknown_are_400(self):
        bad_status = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs?status=bogus"
        )
        self.assertEqual(bad_status.status_code, 400)
        self.assertEqual(bad_status.json()["error"]["code"], "status_unknown")

        bad_sort = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs?sort=bogus")
        self.assertEqual(bad_sort.status_code, 400)
        self.assertEqual(bad_sort.json()["error"]["code"], "sort_unknown")


# -- 案例 2：另一個組織的 pack／set -> 404 ------------------------------------------------

class CrossTenantTest(_WorkbenchPackApiTestBase):
    def test_other_orgs_pack_and_set_are_404(self):
        org_b, _token_b = self._make_org("cross-tenant")
        brand_b = bi_repo.create_brand(
            web.conn, org_id=org_b, name="測試品牌 B：任務包 API 隔離", client_name=None,
            actor=ACTOR,
        )
        web.conn.commit()
        other_pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1})], org_id=org_b, brand_id=brand_b["id"],
        )
        other_set_id = [
            dict(r) for r in web.conn.execute(
                "SELECT id FROM workbench_brief WHERE org_id = %s AND pack_id = %s",
                (org_b, other_pack_id),
            ).fetchall()
        ][0]["id"]

        pack_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/packs/{other_pack_id}"
        )
        self.assertEqual(pack_resp.status_code, 404)
        self.assertEqual(pack_resp.json()["error"]["code"], "pack_unknown")

        set_resp = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/sets/{other_set_id}"
        )
        self.assertEqual(set_resp.status_code, 404)
        self.assertEqual(set_resp.json()["error"]["code"], "set_unknown")


# -- 案例 3：select 兩次冪等；核准後 select／run 一律 409 ----------------------------------

class SelectAndLockTest(_WorkbenchPackApiTestBase):
    def test_select_twice_is_idempotent_then_locks_after_approve(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief["id"],
            part="copy", generation_round=1, body_json=[{"sets": []}],
            coordinates_json=None, llm_task_id=None,
        )
        output_id = outputs[0]["id"]
        select_url = (
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}"
            f"/versions/{output_id}/select"
        )
        first = self.client.post(select_url)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(select_url)
        self.assertEqual(second.status_code, 200)

        # 完成三個條件 -> approve
        for key in ("brand_rules_checked", "ready_to_report"):
            resp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(resp.status_code, 200)
        approve_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve"
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.json()["pack"]["status"], "done")

        locked_select = self.client.post(select_url)
        self.assertEqual(locked_select.status_code, 409)
        self.assertEqual(locked_select.json()["error"]["code"], "pack_approved")

        locked_run = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}/products/copy/run",
            json={},
        )
        self.assertEqual(locked_run.status_code, 409)
        self.assertEqual(locked_run.json()["error"]["code"], "pack_approved")


# -- 案例 4：run 一個已關閉的素材組 -> 409 -------------------------------------------------

class RunClosedSetTest(_WorkbenchPackApiTestBase):
    def test_run_on_closed_set_is_409(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        brief = self._briefs(pack_id)[0]
        web.conn.execute(
            "UPDATE workbench_brief SET status = 'done', closed_at = now() WHERE id = %s",
            (brief["id"],),
        )
        web.conn.commit()
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{brief['id']}/products/copy/run",
            json={},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "brief_closed")


# -- 案例 5：自由創作建 pack -> 命名 自由工作 #2；空 sets／free part 一律 400 -------------------

class CreateFreePackTest(_WorkbenchPackApiTestBase):
    def _body(self, **overrides) -> dict:
        body = {
            "free_text": "五張社群圖片", "style_key": "ugc",
            "sets": [self._one_set("free-1", {"image_prompt": 5})],
        }
        body.update(overrides)
        return body

    def test_second_free_pack_is_named_sequentially(self):
        first = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(),
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["pack"]["name"], "自由工作 #1")
        self.assertEqual(first.json()["pack"]["source_kind"], "free_job")

        second = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(),
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["pack"]["name"], "自由工作 #2")

    def test_empty_sets_is_400(self):
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs", json=self._body(sets=[]),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "sets_unknown")

    def test_free_part_in_required_outputs_is_400(self):
        resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/packs",
            json=self._body(sets=[self._one_set("free-1", {"free": 1})]),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "part_retired")


# -- 案例 6：一份剛送出的 pack，還沒生成任何版本 -> cell 讀「未生成」 ----------------------------

class FreshPackCellTextTest(_WorkbenchPackApiTestBase):
    def test_fresh_pack_cells_read_未生成(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1, "image_prompt": 1})])
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(resp.status_code, 200)
        cells = resp.json()["pack"]["sets"][0]["cells"]
        for cell in cells:
            if cell["part"] in ("copy", "image_prompt"):
                self.assertEqual(cell["text"], "未生成")
            else:
                self.assertEqual(cell["text"], "—")


if __name__ == "__main__":
    unittest.main()
