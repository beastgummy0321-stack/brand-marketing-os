"""app/tests/test_workbench_set_settings.py — F07-I08 (ARCHITECTURE.md §5.13): `SetDetail`'s
top-level `generation_settings`, always eight `{label, text}` rows, `—`／「無」 for anything
empty. Fixture shape borrowed from `test_workbench_image_port.py`."""

import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import repository as workbench_repo

ACTOR = "測試員"

_LABELS = [
    "品牌／商品", "平台", "尺寸", "品牌視覺", "這張圖的任務", "風格分配", "視覺學習", "主要訊息",
]


def _round(*, identity_text="品牌識別文字", learning_ids=None):
    return {
        "format": "single_image", "audience_key": "warm_engaged", "image_task": "convert",
        "identity_id": "wvi_1", "identity_text": identity_text,
        "plan": [{"look": "phone_raw", "slot": "exploit"}],
        "look_order": {"exploit": ["phone_raw"], "explore": ["studio_hero"]},
        "recommended_index": 1, "recommended_slot": "exploit",
        "learning_ids": ["lrn_1", "lrn_2"] if learning_ids is None else learning_ids,
    }


def _body(**round_overrides):
    prompt = "一張畫面描述。"
    return {
        "title": "情境對照", "headline": "主標",
        "prompt": prompt, "text": f"{prompt}\n\n品牌視覺規範：X\n風格規範：Y",
        "fingerprint": {
            "image_task": {"key": "convert", "label": "讓猶豫的人下單"},
            "device": {"key": "contrast", "label": "對照"},
            "layout": {"key": "candid_scene", "label": "情境畫面"},
            "look": {"key": "phone_raw", "label": "手機原生抓拍"},
            "subject_role": {"key": "hero", "label": "主角"},
            "persuasion": {"key": "none", "label": "無"},
            "slot": {"key": "exploit", "label": "主力"},
        },
        "cards": None, "round": _round(**round_overrides), "validation": [], "warnings": [],
    }


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
            # S08: 情境 differs from 重點訊息 so a mutant reading 情境 for 主要訊息 is caught.
            summary={"情境": "測試情境內容", "重點訊息": "第一行\n第二行\n"},
        )
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1, body_json=[_body()],
            coordinates_json=None, llm_task_id=None,
        )

        detail = self._get_set(brief_id)
        rows = detail["generation_settings"]
        labels = [r["label"] for r in rows]
        self.assertEqual(labels, _LABELS)
        by_label = {r["label"]: r["text"] for r in rows}
        self.assertEqual(by_label["品牌／商品"], "測試品牌：生成設定 · 測試商品")
        self.assertEqual(by_label["品牌視覺"], "品牌識別文字")
        self.assertEqual(by_label["這張圖的任務"], "讓猶豫的人下單")
        self.assertEqual(by_label["風格分配"], "主力：手機原生抓拍；探索：棚拍主視覺")
        self.assertEqual(by_label["視覺學習"], "2 條")
        self.assertEqual(by_label["主要訊息"], "第一行；第二行")
        # S09: chips.style is always None, never the (retired) style dict.
        self.assertIsNone(detail["chips"]["style"])

    def test_empty_learnings_read_無_not_0_條(self):
        # S05: an empty `learning_ids` list on a real round reads 「無」, not 「0 條」.
        pack_id = self._submit_pack([{
            "name": "單元 S05", "source_ref": {"node_key": "s05"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1, body_json=[_body(learning_ids=[])],
            coordinates_json=None, llm_task_id=None,
        )
        detail = self._get_set(brief_id)
        by_label = {r["label"]: r["text"] for r in detail["generation_settings"]}
        self.assertEqual(by_label["視覺學習"], "無")

    def test_settings_read_latest_round_not_oldest(self):
        # S06: two rounds with different `identity_text` — the settings must read round 2.
        pack_id = self._submit_pack([{
            "name": "單元 S06", "source_ref": {"node_key": "s06"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"image_prompt": 1},
            "request": {"image_prompt_count": 1},
        }])
        brief_id = self._one_brief_id(pack_id)
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=1,
            body_json=[_body(identity_text="舊識別文字")],
            coordinates_json=None, llm_task_id=None,
        )
        workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part="image_prompt", generation_round=2,
            body_json=[_body(identity_text="新識別文字")],
            coordinates_json=None, llm_task_id=None,
        )
        detail = self._get_set(brief_id)
        by_label = {r["label"]: r["text"] for r in detail["generation_settings"]}
        self.assertEqual(by_label["品牌視覺"], "新識別文字")

    def test_set_detail_never_calls_get_style(self):
        # S10: `get_style` must not be called any more — recompiling it to raise proves
        # `set_detail` never reaches it.
        pack_id = self._submit_pack([{
            "name": "單元 S10", "source_ref": {"node_key": "s10"}, "coordinates": {},
            "style_key": "ugc", "required_outputs": {"copy": 1},
            "request": {"copy_length": "short"},
        }])
        brief_id = self._one_brief_id(pack_id)
        with mock.patch.object(
            workbench_repo, "get_style",
            side_effect=AssertionError("get_style must not be called by set_detail"),
        ):
            detail = self._get_set(brief_id)
        self.assertIsNone(detail["chips"]["style"])

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
        self.assertEqual(labels, _LABELS)
        by_label = {r["label"]: r["text"] for r in rows}
        self.assertEqual(by_label["品牌／商品"], "測試品牌：生成設定 · 不指定")
        self.assertEqual(by_label["品牌視覺"], "—")
        self.assertEqual(by_label["這張圖的任務"], "—")
        self.assertEqual(by_label["風格分配"], "—")
        self.assertEqual(by_label["視覺學習"], "—")
        self.assertEqual(by_label["主要訊息"], "—")


if __name__ == "__main__":
    unittest.main()
