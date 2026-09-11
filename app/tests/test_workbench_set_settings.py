"""app/tests/test_workbench_set_settings.py — F02-I12 (ARCHITECTURE.md §5.13): `SetDetail`'s
top-level `generation_settings`, always seven `{label, text}` rows, `—` for anything empty.
Fixture shape borrowed from `test_workbench_image_port.py`."""

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


class SetGenerationSettingsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：生成設定", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _submit_pack(self, sets: list, summary: dict | None = None) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包", "summary": summary or {}, "sets": sets,
        }
        return workbench_repo.submit_pack(web.conn, self.org_id, self.brand_id, pack)

    def _one_brief_id(self, pack_id: str) -> str:
        rows = web.conn.execute(
            "SELECT id FROM workbench_brief WHERE org_id = %s AND brand_id = %s"
            " AND pack_id = %s ORDER BY created_at",
            (self.org_id, self.brand_id, pack_id),
        ).fetchall()
        return rows[0]["id"]

    def _get_set(self, brief_id: str) -> dict:
        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/sets/{brief_id}")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["set"]

    def test_with_product_and_image_round(self):
        product = bi_repo.create_product(
            web.conn, brand_id=self.brand_id, name="測試商品", actor=ACTOR,
        )
        web.conn.commit()
        pack_id = self._submit_pack(
            [{
                "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
                "style_key": "ugc", "product_id": product["id"],
                "required_outputs": {"image_prompt": 1},
                "request": {"image_prompt_count": 1},
            }],
            summary={"重點訊息": "第一行\n第二行\n"},
        )
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1,
            body_json=[{
                "mode": "variant",
                "hero": {"person": "年輕女性", "scene": "居家客廳"},
                "rendered": {"hero": "hero text", "variant": "variant text"},
            }],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        rows = detail["generation_settings"]
        labels = [r["label"] for r in rows]
        self.assertEqual(labels, ["品牌／商品", "平台", "尺寸", "風格", "人物", "場景", "主要訊息"])
        by_label = {r["label"]: r["text"] for r in rows}
        self.assertEqual(by_label["品牌／商品"], "測試品牌：生成設定 · 測試商品")
        self.assertEqual(by_label["人物"], "年輕女性")
        self.assertEqual(by_label["場景"], "居家客廳")
        self.assertEqual(by_label["主要訊息"], "第一行；第二行")

    def test_without_product_or_image_round(self):
        pack_id = self._submit_pack([{
            "name": "單元 2", "source_ref": {"node_key": "2"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"copy": 1},
            "request": {"copy_length": "short"},
        }])
        brief_id = self._one_brief_id(pack_id)

        detail = self._get_set(brief_id)
        rows = detail["generation_settings"]
        labels = [r["label"] for r in rows]
        self.assertEqual(labels, ["品牌／商品", "平台", "尺寸", "風格", "人物", "場景", "主要訊息"])
        by_label = {r["label"]: r["text"] for r in rows}
        self.assertEqual(by_label["品牌／商品"], "測試品牌：生成設定 · 不指定")
        self.assertEqual(by_label["人物"], "—")
        self.assertEqual(by_label["場景"], "—")
        self.assertEqual(by_label["主要訊息"], "—")


if __name__ == "__main__":
    unittest.main()
