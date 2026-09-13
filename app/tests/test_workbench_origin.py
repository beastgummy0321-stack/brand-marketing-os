"""app/tests/test_workbench_origin.py — F03-I07 (ARCHITECTURE.md §5.4): the workbench stores
and returns `origin_label`/`origin_href` verbatim, never interprets them. Fixture shape from
`app/tests/test_workbench_approve.py` (`TestClient(main.app)`, fresh `background.app()` needing
`register_tasks()` again, `submit_pack()` as the real upstream door).
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

# 特殊字元：驗收 origin_label 原樣往返，不被任何一層改寫或跳脫。
ORIGIN_LABEL = "投放中心 → Beast Gummy｜9 月新客開發 → Meta → 新客｜Broad"
ORIGIN_HREF = "/brands/brd_test/ads/campaigns/cmp_test"


class _WorkbenchOriginTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：pack 來源", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _one_set(self, node_key: str, required_outputs: dict) -> dict:
        return {
            "name": f"單元 {node_key}", "source_ref": {"node_key": node_key},
            "coordinates": {}, "style_key": "ugc", "required_outputs": required_outputs,
            "request": {"copy_length": "short", "image_prompt_count": 3},
        }

    def _submit_pack(self, sets: list, *, context: dict | None = None) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包：來源", "summary": {"情境": "測試"}, "sets": sets,
        }
        if context is not None:
            pack["context"] = context
        return workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)

    def _tick_all(self, pack_id: str) -> None:
        for key in ("required_outputs_met", "brand_rules_checked", "ready_to_report"):
            resp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(resp.status_code, 200)

    def _approve(self, pack_id: str):
        return self.client.post(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve")


# -- 案例 1：帶 origin_label／origin_href 的 pack，PackDetail 原樣吐回 ------------------------

class OriginRoundTripTest(_WorkbenchOriginTestBase):
    def test_origin_label_returns_verbatim_through_pack_detail(self):
        pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1})],
            context={"origin_label": ORIGIN_LABEL, "origin_href": ORIGIN_HREF},
        )
        detail = workbench_repo.pack_detail(web.conn, self.org_id, self.brand_id, pack_id)
        assert detail is not None
        self.assertEqual(detail["origin_label"], ORIGIN_LABEL)
        self.assertEqual(detail["origin_href"], ORIGIN_HREF)


# -- 案例 2：沒有 origin 的 pack，仍然回今天的 source_label（自由工作不受影響）-------------------

class NoOriginFallsBackToSourceLabelTest(_WorkbenchOriginTestBase):
    def test_pack_without_origin_keeps_source_label(self):
        pack_id = self._submit_pack([self._one_set("1", {"copy": 1})])
        detail = workbench_repo.pack_detail(web.conn, self.org_id, self.brand_id, pack_id)
        assert detail is not None
        self.assertIsNone(detail["origin_label"])
        self.assertIsNone(detail["origin_href"])
        self.assertEqual(detail["source_label"], "廣告排程")


# -- 案例 3：核准整包前後，origin_label 不變、status 變成 done——前端靠這兩個事實組出
# 「已同步至 <origin_label>」------------------------------------------------------------------

class OriginSurvivesApproveTest(_WorkbenchOriginTestBase):
    def test_origin_label_stable_across_approve_and_status_flips_to_done(self):
        pack_id = self._submit_pack(
            [self._one_set("1", {"copy": 1})],
            context={"origin_label": ORIGIN_LABEL, "origin_href": ORIGIN_HREF},
        )
        before = workbench_repo.pack_detail(web.conn, self.org_id, self.brand_id, pack_id)
        assert before is not None
        self.assertEqual(before["origin_label"], ORIGIN_LABEL)
        self.assertNotEqual(before["status"], "done")

        self._tick_all(pack_id)
        approved = self._approve(pack_id)
        self.assertEqual(approved.status_code, 200)

        after = workbench_repo.pack_detail(web.conn, self.org_id, self.brand_id, pack_id)
        assert after is not None
        self.assertEqual(after["status"], "done")
        self.assertEqual(after["origin_label"], ORIGIN_LABEL)


# -- 案例 4：set_detail 也原樣帶 origin_label；pack_for_source／briefs_for_source 形狀不變 -------

class SetDetailAndExistingReadersUnchangedTest(_WorkbenchOriginTestBase):
    def test_set_detail_carries_origin_and_existing_readers_unchanged(self):
        pack_id = self._submit_pack(
            [self._one_set("2", {"copy": 1})],
            context={"origin_label": ORIGIN_LABEL, "origin_href": ORIGIN_HREF},
        )
        brief_row = web.conn.execute(
            "SELECT id FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s", (self.org_id, self.brand_id, pack_id),
        ).fetchone()
        assert brief_row is not None
        set_detail = workbench_repo.set_detail(
            web.conn, self.org_id, self.brand_id, brief_row["id"],
        )
        assert set_detail is not None
        self.assertEqual(set_detail["origin_label"], ORIGIN_LABEL)
        self.assertEqual(set_detail["origin_href"], ORIGIN_HREF)

        found = workbench_repo.pack_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", {"node_key": "no_such"},
        )
        self.assertIsNone(found)  # 形狀還是「找不到回 None」，沒有被這張票動到
        briefs = workbench_repo.briefs_for_source(
            web.conn, self.org_id, self.brand_id, "schedule_node", {"node_key": "2"},
        )
        self.assertEqual(len(briefs), 1)
        self.assertNotIn("origin_label", briefs[0])  # briefs_for_source 形狀沒有變


if __name__ == "__main__":
    unittest.main()
