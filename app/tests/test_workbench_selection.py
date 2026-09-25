"""F31-I04 (Feature Contract L): an ads-dispatched image set holds at most the selections it
needs, and each version carries its own ❌ lines as `validation_warning`.

Sets are seeded through `workbench_repo.submit_pack()` with the same `source_ref` shape the ads
dispatch writes (`{"ads_campaign_id", "ads_ad_id"}`); selection goes over HTTP.
"""

import app.shared.web as web
from app.workbench import repository as workbench_repo

from .test_workbench_pack_api import _WorkbenchPackApiTestBase

_ADS_REF = {"ads_campaign_id": "cmp_selection_test", "ads_ad_id": "ad_selection_test"}


def _image_body(index: int, validation: list) -> dict:
    return {
        "title": f"提案 {index}", "headline": ["標題"], "prompt": "1:1 畫面", "text": "1:1 畫面",
        "fingerprint": None, "cards": None, "round": None, "validation": validation,
        "warnings": [],
    }


class _SelectionBase(_WorkbenchPackApiTestBase):
    def _set(self, required_outputs: dict, source_ref: dict) -> dict:
        pack_id = self._submit_pack([
            self._one_set("sel", required_outputs, source_ref=source_ref),
        ])
        return self._briefs(pack_id)[0]

    def _write(self, brief_id: str, part: str, bodies: list) -> list:
        return workbench_repo.write_output(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, brief_id=brief_id,
            part=part, generation_round=1, body_json=bodies, coordinates_json=None,
            llm_task_id=None,
        )

    def _url(self, set_id: str, version_id: str) -> str:
        return (
            f"/api/workbench/brands/{self.brand_id}/sets/{set_id}/versions/{version_id}/select"
        )

    def _selected_ids(self, set_id: str, part: str) -> list:
        rows = web.conn.execute(
            "SELECT id FROM workbench_output WHERE org_id = %s AND brand_id = %s"
            " AND brief_id = %s AND part = %s AND adopted_at IS NOT NULL ORDER BY id",
            (self.org_id, self.brand_id, set_id, part),
        ).fetchall()
        return [r["id"] for r in rows]


class SelectionCapTest(_SelectionBase):
    def test_second_image_on_one_image_ads_set_is_refused(self):
        brief = self._set({"image_prompt": 1}, _ADS_REF)
        first, second = self._write(
            brief["id"], "image_prompt", [_image_body(1, []), _image_body(2, [])],
        )

        ok = self.client.post(self._url(brief["id"], first["id"]))
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["set"]["products"]["image_prompt"]["selection_full"])

        refused = self.client.post(self._url(brief["id"], second["id"]))
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["error"]["code"], "selection_full")
        self.assertEqual(
            refused.json()["error"]["message"], "這一則只能選 1 張，先取消目前選的那張再選。",
        )
        self.assertEqual(self._selected_ids(brief["id"], "image_prompt"), [first["id"]])

        # Re-selecting the one already selected stays idempotent.
        again = self.client.post(self._url(brief["id"], first["id"]))
        self.assertEqual(again.status_code, 200)

        # Deselect frees the seat; the other version can then be selected.
        freed = self.client.delete(self._url(brief["id"], first["id"]))
        self.assertEqual(freed.status_code, 200)
        self.assertFalse(freed.json()["set"]["products"]["image_prompt"]["selection_full"])
        swapped = self.client.post(self._url(brief["id"], second["id"]))
        self.assertEqual(swapped.status_code, 200)
        self.assertEqual(self._selected_ids(brief["id"], "image_prompt"), [second["id"]])

    def test_copy_part_of_ads_set_still_accepts_two(self):
        brief = self._set({"copy": 1, "image_prompt": 1}, _ADS_REF)
        outputs = self._write(brief["id"], "copy", [{"sets": []}] * 2)
        for output in outputs:
            resp = self.client.post(self._url(brief["id"], output["id"]))
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["set"]["products"]["copy"]["selection_full"])
        self.assertEqual(len(self._selected_ids(brief["id"], "copy")), 2)

    def test_image_set_without_ads_ad_keeps_multi_select(self):
        brief = self._set({"image_prompt": 1}, {"node_key": "sel"})
        outputs = self._write(
            brief["id"], "image_prompt", [_image_body(1, []), _image_body(2, [])],
        )
        for output in outputs:
            resp = self.client.post(self._url(brief["id"], output["id"]))
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["set"]["products"]["image_prompt"]["selection_full"])
        self.assertEqual(len(self._selected_ids(brief["id"], "image_prompt")), 2)


class ValidationWarningTest(_SelectionBase):
    def test_image_versions_carry_only_their_own_failed_lines(self):
        brief = self._set({"image_prompt": 1}, _ADS_REF)
        round_lines = [
            "✅ items：符合",
            "❌ items[1].prompt_leak：圖上出現分類術語：['主力']",
            "✅ items[1].look：符合",
            "✅ items[2].look：符合",
            "❌ items[10].prompt_numbers：數字未出現在可用字句或品牌資料：['99']",
            "❌ items_layouts：版型應至少 3 種，實際 2",
        ]
        self._write(
            brief["id"], "image_prompt",
            [_image_body(i, round_lines) for i in range(1, 11)],
        )
        detail = workbench_repo.set_detail(web.conn, self.org_id, self.brand_id, brief["id"])
        assert detail is not None
        by_index = {
            v["version_index"]: v["validation_warning"]
            for v in detail["products"]["image_prompt"]["versions"]
        }
        self.assertEqual(
            by_index[1], {"lines": ["❌ items[1].prompt_leak：圖上出現分類術語：['主力']"]},
        )
        self.assertIsNone(by_index[2])
        self.assertEqual(
            by_index[10],
            {"lines": ["❌ items[10].prompt_numbers：數字未出現在可用字句或品牌資料：['99']"]},
        )

    def test_copy_versions_read_their_own_set_index(self):
        brief = self._set({"copy": 1}, {"node_key": "sel"})
        round_body = {
            "sets": [{"body": "b", "headline": "h", "description": "d"}] * 5,
            "validation": [
                "✅ sets[1].body：符合",
                "❌ sets[2].body：3 字，超出 20～80 字範圍",
                "✅ coordinates：全部合格",
            ],
        }
        self._write(brief["id"], "copy", [round_body] * 5)
        detail = workbench_repo.set_detail(web.conn, self.org_id, self.brand_id, brief["id"])
        assert detail is not None
        by_index = {
            v["version_index"]: v["validation_warning"]
            for v in detail["products"]["copy"]["versions"]
        }
        self.assertIsNone(by_index[1])
        self.assertEqual(by_index[2], {"lines": ["❌ sets[2].body：3 字，超出 20～80 字範圍"]})
