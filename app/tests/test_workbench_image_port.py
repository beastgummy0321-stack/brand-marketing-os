"""app/tests/test_workbench_image_port.py — F02-I05 (ARCHITECTURE.md §5.11): the reserved
image-generation seat. `image_port` never spends money (`connected()` is `False`,
`generate()` raises); `SetDetail.products.image_prompt.versions[].prompt_cards` reads the
①/②/③ pair straight out of `prompts.py`'s already-rendered `body_json["rendered"]`, never
re-rendering. Fixture shape borrowed from `test_workbench_pack_api.py`."""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import image_port
from app.workbench import repository as workbench_repo

ACTOR = "測試員"


class ImagePortTest(unittest.TestCase):
    def test_connected_is_false_and_generate_raises(self):
        self.assertFalse(image_port.connected())
        with self.assertRaises(NotImplementedError):
            image_port.generate()


class SetDetailPromptCardsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：圖片席位", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _submit_pack(self, sets: list) -> str:
        pack = {
            "source_kind": "schedule_node",
            "source_ref": {"source_tree_task_id": str(uuid.uuid4())},
            "name": "測試任務包", "summary": {}, "sets": sets,
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

    def test_variant_mode_cards_match_rendered_text(self):
        pack_id = self._submit_pack([{
            "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        hero_text = "hero prompt text"
        variant_text = "variant prompt text"
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1,
            body_json=[{
                "mode": "variant",
                "rendered": {"hero": hero_text, "variant": variant_text},
            }],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        versions = detail["products"]["image_prompt"]["versions"]
        self.assertEqual(len(versions), 1)
        self.assertEqual(
            versions[0]["prompt_cards"],
            [
                {"label": "① 主圖", "text": hero_text},
                {"label": "② 變體", "text": variant_text},
            ],
        )

    def test_exploration_mode_cards_are_ordered_探索_then_變體(self):
        pack_id = self._submit_pack([{
            "name": "單元 2", "source_ref": {"node_key": "2"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        exploration_text = "exploration prompt text"
        variant_text = "variant prompt text"
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1,
            body_json=[{
                "mode": "exploration",
                "rendered": {"exploration": exploration_text, "variant": variant_text},
            }],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        versions = detail["products"]["image_prompt"]["versions"]
        self.assertEqual(
            versions[0]["prompt_cards"],
            [
                {"label": "③ 探索", "text": exploration_text},
                {"label": "② 變體", "text": variant_text},
            ],
        )

    def test_no_image_round_is_empty_list_and_未生成(self):
        pack_id = self._submit_pack([{
            "name": "單元 3", "source_ref": {"node_key": "3"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)

        detail = self._get_set(brief_id)
        product = detail["products"]["image_prompt"]
        self.assertEqual(product["versions"], [])
        self.assertEqual(product["state"], "未生成")
        self.assertEqual(detail["image_generation"], {
            "connected": False,
            "reason": "圖片生成服務未接上，這裡先保留席位；接上後同一個畫面直接顯示成果。",
        })


if __name__ == "__main__":
    unittest.main()
