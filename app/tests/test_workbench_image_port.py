"""app/tests/test_workbench_image_port.py — F02-I05 (ARCHITECTURE.md §5.11) and F07-I08
(§5.7/§5.11 rework): the reserved image-generation seat, and
`SetDetail.products.image_prompt.versions[].prompt_cards` reading the §5.8 row shape through
`app/workbench/image_cards.py`, never re-rendering. Fixture shape borrowed from
`test_workbench_pack_api.py`."""

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


def _fingerprint(*, slot="exploit", slot_label="主力"):
    return {
        "image_task": {"key": "convert", "label": "讓猶豫的人下單"},
        "device": {"key": "contrast", "label": "對照"},
        "layout": {"key": "candid_scene", "label": "情境畫面"},
        "look": {"key": "phone_raw", "label": "手機原生抓拍"},
        "subject_role": {"key": "hero", "label": "主角"},
        "persuasion": {"key": "none", "label": "無"},
        "slot": {"key": slot, "label": slot_label},
    }


def _round(*, recommended_index=1):
    return {
        "format": "single_image", "audience_key": "warm_engaged", "image_task": "convert",
        "identity_id": "wvi_1", "identity_text": "品牌識別文字",
        "plan": [{"look": "phone_raw", "slot": "exploit"}],
        "look_order": {"exploit": ["phone_raw"], "explore": []},
        "recommended_index": recommended_index, "recommended_slot": "exploit",
        "learning_ids": [],
    }


def _body(**overrides):
    prompt = "這是一張畫面描述，「主標」放在畫面上方。"
    body = {
        "title": "情境對照", "headline": "主標",
        "prompt": prompt, "text": f"{prompt}\n\n品牌視覺規範：X\n風格規範：Y",
        "fingerprint": _fingerprint(), "cards": None, "round": _round(),
        "validation": [], "warnings": [],
    }
    body.update(overrides)
    return body


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

    def test_selected_single_gets_variant_card_and_badges(self):
        pack_id = self._submit_pack([{
            "name": "單元 1", "source_ref": {"node_key": "1"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1, "variant_count": 3},
        }])
        brief_id = self._one_brief_id(pack_id)
        outputs = workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1, body_json=[_body()],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

        detail = self._get_set(brief_id)
        versions = detail["products"]["image_prompt"]["versions"]
        self.assertEqual(len(versions), 1)
        cards = versions[0]["prompt_cards"]
        self.assertEqual(cards[0], {"label": "01｜情境對照", "text": _body()["text"]})
        self.assertEqual(cards[1]["label"], "② 變體")
        self.assertEqual(versions[0]["badges"], ["主力", "建議選這張"])
        self.assertEqual(versions[0]["fingerprint_text"], "手機原生抓拍 · 情境畫面 · 對照")

    def test_generation_settings_for_image_prompt_is_empty_dict(self):
        # P06: `_generation_settings("image_prompt", …) == {}` — the legacy `{"count": …}`
        # shape is gone (§5.13 moved everything into the top-level `generation_settings` rows).
        pack_id = self._submit_pack([{
            "name": "單元 P06", "source_ref": {"node_key": "p06"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        detail = self._get_set(brief_id)
        self.assertEqual(detail["products"]["image_prompt"]["generation_settings"], {})

    def test_missing_out_of_range_or_string_variant_count_defaults_to_0(self):
        # P02: `variant_count` is only an int 0-9 from `request_json`; anything else -> 0 (no ②).
        cases = [
            ("missing", {"image_prompt_count": 1}),
            ("out_of_range", {"image_prompt_count": 1, "variant_count": 10}),
            ("string", {"image_prompt_count": 1, "variant_count": "6"}),
        ]
        for label, request in cases:
            pack_id = self._submit_pack([{
                "name": f"單元 P02 {label}", "source_ref": {"node_key": f"p02-{label}"},
                "coordinates": {}, "style_key": "ugc",
                "required_outputs": {"image_prompt": 1}, "request": request,
            }])
            brief_id = self._one_brief_id(pack_id)
            outputs = workbench_repo.write_output(
                web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
                part="image_prompt", generation_round=1, body_json=[_body()],
                coordinates_json=None, llm_task_id=None,
            )
            workbench_repo.select_version(web.conn, self.org_id, self.brand_id, outputs[0]["id"])

            detail = self._get_set(brief_id)
            versions = detail["products"]["image_prompt"]["versions"]
            self.assertEqual(len(versions[0]["prompt_cards"]), 1, label)

    def test_unselected_has_no_variant_card(self):
        pack_id = self._submit_pack([{
            "name": "單元 2", "source_ref": {"node_key": "2"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1, "variant_count": 3},
        }])
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1, body_json=[_body()],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        versions = detail["products"]["image_prompt"]["versions"]
        self.assertEqual(len(versions[0]["prompt_cards"]), 1)

    def test_pre_f07_row_renders_no_cards_and_no_crash(self):
        pack_id = self._submit_pack([{
            "name": "單元 3", "source_ref": {"node_key": "3"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1,
            body_json=[{
                "mode": "variant",
                "rendered": {"hero": "hero text", "variant": "variant text"},
            }],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        versions = detail["products"]["image_prompt"]["versions"]
        self.assertEqual(versions[0]["prompt_cards"], [])
        self.assertIsNone(versions[0]["fingerprint_text"])
        self.assertEqual(versions[0]["badges"], [])

    def test_no_image_round_is_empty_list_and_未生成(self):
        pack_id = self._submit_pack([{
            "name": "單元 4", "source_ref": {"node_key": "4"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)

        detail = self._get_set(brief_id)
        product = detail["products"]["image_prompt"]
        self.assertEqual(product["versions"], [])
        self.assertEqual(product["state"], "未生成")
        self.assertIsNone(product["copy_all_text"])
        self.assertEqual(detail["image_generation"], {
            "connected": False,
            "reason": "圖片生成服務未接上，這裡先保留席位；接上後同一個畫面直接顯示成果。",
        })


if __name__ == "__main__":
    unittest.main()
