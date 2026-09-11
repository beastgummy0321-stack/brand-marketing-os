"""app/tests/test_schedule_creative_pack_signal.py — F02-I04: `GET /api/schedule/brands/{b}`
carries `creative_pack`, the "可以下一步" signal read through `workbench.pack_for_source`
(ARCHITECTURE.md §5.5, `.work/features/F02.md` Decisions). This module only falsifies
`app/schedule/state.py::_creative_pack_for_tree` and its wiring into `_brand_response` —
generation itself (what a pack/set actually produces) is `test_workbench_pack.py`'s and
`test_workbench_pack_api.py`'s job, not repeated here. Packs are seeded through
`app.workbench.submit_pack()`, the one public entry (ADR 0068 rule 2: `app/schedule` never
imports `app.workbench` internals), and approved through the `/api/workbench/*` HTTP surface
for the same reason — this module never touches a real provider.
"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.schedule import state as schedule_state

ACTOR = "測試員"


class _CreativePackSignalTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：任務包信號", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        rule_cards.set_value(
            web.conn, self.brand_id, "schedule_budget", "daily_budget", 3000.0,
            ACTOR, org_id=self.org_id,
        )
        web.conn.commit()

    def _submit_pack(self, tree_task_id: str, node_keys: list) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": tree_task_id},
            "name": "測試任務包", "summary": {"情境": "測試情境"},
            "sets": [
                {
                    "name": f"單元 {key}", "source_ref": {"node_key": key},
                    "coordinates": {}, "style_key": "ugc",
                    "required_outputs": {"copy": 1},
                    "request": {"copy_length": "short"},
                }
                for key in node_keys
            ],
        }
        pack_id = workbench_module.submit_pack(web.conn, self.org_id, self.brand_id, pack)
        web.conn.commit()
        return pack_id

    def _approve_via_api(self, pack_id: str) -> None:
        for key in ("required_outputs_met", "brand_rules_checked", "ready_to_report"):
            resp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(resp.status_code, 200, resp.text)
        resp = self.client.post(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve")
        self.assertEqual(resp.status_code, 200, resp.text)


class NoTreeIsNullTest(_CreativePackSignalTestBase):
    def test_no_tree_ever_expanded_returns_null(self):
        body = self.client.get(f"/api/schedule/brands/{self.brand_id}").json()
        self.assertIsNone(body["creative_pack"])
        # 直接呼叫內部函式，確認 `tree_row=None` 這個分支本身，不只是靠 GET 的其他前提。
        self.assertIsNone(
            schedule_state._creative_pack_for_tree(web.conn, self.org_id, self.brand_id, None)
        )


class DerivedCountsTest(_CreativePackSignalTestBase):
    def test_unapproved_pack_carries_state_and_set_counts(self):
        tree_task_id = str(uuid.uuid4())
        pack_id = self._submit_pack(tree_task_id, ["1.1.1", "1.2.1"])

        signal = schedule_state._creative_pack_for_tree(
            web.conn, self.org_id, self.brand_id, {"id": tree_task_id},
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["pack_id"], pack_id)
        self.assertIsNone(signal["approved_at"])
        self.assertEqual(signal["sets_total"], 2)
        self.assertEqual(signal["sets_done"], 0)
        # §5.3：沒有 set 開始生成 -> 待處理，這裡原樣透傳中文字，不是英文列舉值。
        self.assertEqual(signal["state"], "待處理")


class ApprovedAtTest(_CreativePackSignalTestBase):
    def test_approved_at_is_set_once_the_pack_is_approved(self):
        tree_task_id = str(uuid.uuid4())
        pack_id = self._submit_pack(tree_task_id, ["1.1.1"])

        before = schedule_state._creative_pack_for_tree(
            web.conn, self.org_id, self.brand_id, {"id": tree_task_id},
        )
        self.assertIsNone(before["approved_at"])

        # 完成條件用人工覆核跳過（真的產完再選定是 test_workbench_pack.py 的事，這裡只
        # 驗證 state.py 讀 approve 之後的欄位）。
        self._approve_via_api(pack_id)

        after = schedule_state._creative_pack_for_tree(
            web.conn, self.org_id, self.brand_id, {"id": tree_task_id},
        )
        self.assertIsNotNone(after["approved_at"])
        self.assertEqual(after["state"], "已完成")


class NoLeakBetweenTreesTest(_CreativePackSignalTestBase):
    def test_a_second_trees_pack_does_not_leak_into_the_first_trees_signal(self):
        first_tree_id = str(uuid.uuid4())
        second_tree_id = str(uuid.uuid4())
        first_pack_id = self._submit_pack(first_tree_id, ["1.1.1"])
        second_pack_id = self._submit_pack(second_tree_id, ["1.1.1", "1.2.1", "1.3.1"])

        first_signal = schedule_state._creative_pack_for_tree(
            web.conn, self.org_id, self.brand_id, {"id": first_tree_id},
        )
        second_signal = schedule_state._creative_pack_for_tree(
            web.conn, self.org_id, self.brand_id, {"id": second_tree_id},
        )
        self.assertEqual(first_signal["pack_id"], first_pack_id)
        self.assertEqual(first_signal["sets_total"], 1)
        self.assertEqual(second_signal["pack_id"], second_pack_id)
        self.assertEqual(second_signal["sets_total"], 3)


if __name__ == "__main__":
    unittest.main()
