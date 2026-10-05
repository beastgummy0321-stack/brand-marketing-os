"""app/tests/test_workbench_parts.py — F02-I15: the brief-shaped `POST /briefs` route this
file used to exercise was removed by F02-I03 (`app/workbench/routes.py`); `kind` derivation
and the `parts_unknown` cases moved to (or were already proven at) `test_workbench_pack.py`
and `test_workbench_pack_api.py`. What remains is the **dispatch contract**
(`submit_pack` -> `request_json.parts` -> one job per required 產物類型) and the two
request-level validations that live nowhere else: `copy_length_unknown`, and that an
image-prompt round may run before any copy is selected (ARCHITECTURE.md §5.8).
"""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import repository as workbench_repo

ACTOR = "測試員"


class _WorkbenchPartsTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)  # dev token, see conftest.py — actor is org_dev
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：parts 合約", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _submit_pack(self, sets: list, **overrides) -> str:
        pack = {
            "source_kind": "schedule_node", "source_ref": {"source_tree_task_id": "tree_1"},
            "name": "測試任務包", "summary": {"情境": "測試"}, "sets": sets,
        }
        pack.update(overrides)
        return workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)

    def _one_set(self, node_key: str, required_outputs: dict, **request_overrides) -> dict:
        request = {"copy_length": "short", "image_prompt_count": 3}
        request.update(request_overrides)
        return {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": request,
        }

    def _briefs(self, pack_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return [dict(r) for r in rows]


# -- 案例 1：dispatch 跟 required_outputs 的 key 一對一，每個 key 各自排一個 job --------------

class DispatchFollowsRequiredOutputsKeysTest(_WorkbenchPartsTestBase):
    def test_two_required_parts_enqueue_both_jobs(self):
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 1, "image_prompt": 1}),
        ])
        brief = self._briefs(pack_id)[0]
        self.assertEqual(brief["request_json"]["parts"], ["copy", "image_prompt"])
        self.assertTrue(background_module.is_active(f"workbench:{brief['id']}:copy"))
        self.assertTrue(background_module.is_active(f"workbench:{brief['id']}:image_prompt"))


# -- 案例 2：copy_length_unknown 讓 submit_pack 整包不落 -------------------------------------

class CopyLengthUnknownTest(_WorkbenchPartsTestBase):
    def test_unknown_copy_length_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._submit_pack([
                self._one_set("1", {"copy": 1}, copy_length="extra_long"),
            ])
        self.assertEqual(str(ctx.exception), "copy_length_unknown")


# -- 案例 3：image_prompt 這一輪可以在還沒選定任何 copy 之前先跑 ------------------------------

class RunImagePromptWithoutAdoptedCopyTest(_WorkbenchPartsTestBase):
    def test_run_image_prompt_before_copy_selected_leaves_parts_unchanged(self):
        pack_id = self._submit_pack([
            self._one_set("1", {"copy": 1, "image_prompt": 1}),
        ])
        brief = self._briefs(pack_id)[0]
        set_id = brief["id"]

        # 模擬「送出那一輪已經跑完」——這裡只驗 `run_product()` 本身的行為，不需要真的
        # 跑一輪 worker（比照舊測試手法）。
        web.conn.execute(
            "UPDATE workbench_brief SET status = 'done' WHERE id = %s", (set_id,)
        )
        web.conn.commit()

        run_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/sets/{set_id}/products/image_prompt/run",
            json={"count": 2},
        )
        self.assertEqual(run_resp.status_code, 200)
        self.assertTrue(background_module.is_active(f"workbench:{set_id}:image_prompt"))

        row = web.conn.execute(
            "SELECT request_json FROM workbench_brief WHERE id = %s", (set_id,)
        ).fetchone()
        self.assertEqual(row["request_json"]["parts"], ["copy", "image_prompt"])


# -- 案例 4：F50 Contract J（intake #11）——job 死掉的一輪不再永遠「生成中」 ------------------

class StuckRoundReconcileTest(_WorkbenchPartsTestBase):
    """`run_part`／`set_detail` read a `queued`／`running` round against its job through
    `_reconcile_running`: a dead round is marked failed and the next run proceeds; a live job
    still refuses `round_running`."""

    def _queued_set_without_job(self) -> str:
        # The pack is written with the enqueue swallowed: the set reads `queued` while no
        # procrastinate job ever carried its lock (a killed worker／a lost enqueue).
        with mock.patch("app.background.enqueue", return_value=True):
            pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        set_id = self._briefs(pack_id)[0]["id"]
        self.assertIsNone(background_module.outcome(f"workbench:{set_id}:copy"))
        return set_id

    def _age(self, set_id: str, seconds: float) -> None:
        web.conn.execute(
            "UPDATE workbench_brief SET updated_at = now() - make_interval(secs => %s)"
            " WHERE id = %s",
            (seconds, set_id),
        )
        web.conn.commit()

    def _brief(self, set_id: str) -> dict:
        brief = workbench_repo.get_brief(web.conn, self.org_id, self.brand_id, set_id)
        assert brief is not None
        return brief

    def test_queued_without_job_older_than_the_timeout_runs_again(self):
        set_id = self._queued_set_without_job()
        self._age(set_id, workbench_repo.GENERATION_TIMEOUT_S + 60)

        detail = workbench_repo.set_detail(web.conn, self.org_id, self.brand_id, set_id)
        assert detail is not None
        self.assertEqual(detail["generation"]["status"], "failed")
        self.assertEqual(detail["generation"]["error"], background_module.JOB_FAILED_MESSAGE)

        self._age(set_id, workbench_repo.GENERATION_TIMEOUT_S + 60)
        web.conn.execute(
            "UPDATE workbench_brief SET status = 'queued' WHERE id = %s", (set_id,)
        )
        web.conn.commit()
        workbench_repo.run_part(web.conn, self.org_id, self.brand_id, set_id, "copy")

        brief = self._brief(set_id)
        self.assertEqual(brief["status"], "queued")
        # The old round reads failed: its reason stays until a round ends done.
        self.assertEqual(brief["last_error"], background_module.JOB_FAILED_MESSAGE)
        self.assertTrue(background_module.is_active(f"workbench:{set_id}:copy"))

    def test_queued_without_job_inside_the_timeout_still_refuses(self):
        set_id = self._queued_set_without_job()
        with self.assertRaises(ValueError) as ctx:
            workbench_repo.run_part(web.conn, self.org_id, self.brand_id, set_id, "copy")
        self.assertEqual(str(ctx.exception), "round_running")
        self.assertEqual(self._brief(set_id)["status"], "queued")

    def test_a_live_job_still_refuses_however_long_it_waited(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        set_id = self._briefs(pack_id)[0]["id"]
        live = background_module.outcome(f"workbench:{set_id}:copy")
        assert live is not None
        self.assertEqual(live["state"], "running")
        self._age(set_id, workbench_repo.GENERATION_TIMEOUT_S * 10)

        with self.assertRaises(ValueError) as ctx:
            workbench_repo.run_part(web.conn, self.org_id, self.brand_id, set_id, "copy")
        self.assertEqual(str(ctx.exception), "round_running")
        # A live job on another part of the same set keeps the round live too.
        with self.assertRaises(ValueError):
            workbench_repo.run_part(
                web.conn, self.org_id, self.brand_id, set_id, "video_script", count=1,
            )
        self.assertEqual(self._brief(set_id)["status"], "queued")

    def test_a_failed_job_marks_the_round_failed_at_once_with_its_text(self):
        set_id = self._queued_set_without_job()
        failed = {"state": "failed", "code": "unexpected", "text": "工作中斷了。",
                  "finished_at": None, "started_at": None}

        def outcome(lock):
            return failed if lock == f"workbench:{set_id}:copy" else None

        with mock.patch("app.background.outcome", side_effect=outcome):
            workbench_repo.run_part(web.conn, self.org_id, self.brand_id, set_id, "copy")

        brief = self._brief(set_id)
        self.assertEqual(brief["status"], "queued")
        self.assertEqual(brief["last_error"], "工作中斷了。")

    def test_a_finished_round_is_never_overwritten(self):
        set_id = self._queued_set_without_job()
        self._age(set_id, workbench_repo.GENERATION_TIMEOUT_S + 60)
        web.conn.execute("UPDATE workbench_brief SET status = 'done' WHERE id = %s", (set_id,))
        web.conn.commit()

        detail = workbench_repo.set_detail(web.conn, self.org_id, self.brand_id, set_id)
        assert detail is not None
        self.assertEqual(detail["generation"], {"status": "done", "error": None})


if __name__ == "__main__":
    unittest.main()
