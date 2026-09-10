"""app/tests/test_workbench_parts.py — F01-T01-I01: `request_json.parts` is the single
authority for what a brief asks for; `workbench_brief.kind` is derived for display only
(ARCHITECTURE.md §5.4). Workbench-only fixture (`workbench.may_depend_on` is `[]` — no
`app.schedule` import, see the issue's own note on why `schedule_module.register_tasks()`
and `ensure_coordinates_seeded()` are both unnecessary here: briefs are submitted with
`"coordinates": {}` and `source_ref: {}`, and every case here is pure route validation or a
manual `status` UPDATE, never a coordinate read).
"""

import unittest

from fastapi.testclient import TestClient

import app.background as background_module
import app.main as main
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb

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
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：parts 合約", actor=ACTOR,
        )
        web.conn.commit()

    def _new_brief_body(self, **overrides) -> dict:
        body = {
            "product_id": self.product["id"], "coordinates": None,
            "visual_tone": None, "visual_concept": None, "style_key": "ugc",
            "request": {"parts": ["copy"]},
        }
        body.update(overrides)
        return body

    def _create(self, **overrides):
        return self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs",
            json=self._new_brief_body(**overrides),
        )


# -- 多個 part -> kind='ad_creative'，每個 part 各自排一個 job -----------------------------

class MultiPartDerivesAdCreativeTest(_WorkbenchPartsTestBase):
    def test_two_parts_derive_ad_creative_and_enqueue_both(self):
        resp = self._create(request={
            "parts": ["copy", "image_prompt"], "image_prompt_count": 3,
        })
        self.assertEqual(resp.status_code, 201)
        brief = resp.json()["brief"]
        self.assertEqual(brief["kind"], "ad_creative")
        brief_id = brief["id"]
        self.assertTrue(background_module.is_active(f"workbench:{brief_id}:copy"))
        self.assertTrue(background_module.is_active(f"workbench:{brief_id}:image_prompt"))


# -- 單一 part -> kind 就是那個 part 名 -----------------------------------------------------

class SinglePartDerivesItsOwnKindTest(_WorkbenchPartsTestBase):
    def test_video_script_only_derives_video_script_kind(self):
        resp = self._create(request={"parts": ["video_script"], "video_script_count": 2})
        self.assertEqual(resp.status_code, 201)
        brief = resp.json()["brief"]
        self.assertEqual(brief["kind"], "video_script")
        self.assertTrue(
            background_module.is_active(f"workbench:{brief['id']}:video_script")
        )


# -- parts_unknown／copy_length_unknown 是 400 ----------------------------------------------

class PartsAndCopyLengthValidationTest(_WorkbenchPartsTestBase):
    def test_missing_parts_is_parts_unknown(self):
        resp = self._create(request={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "parts_unknown")

    def test_empty_parts_list_is_parts_unknown(self):
        resp = self._create(request={"parts": []})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "parts_unknown")

    def test_unknown_part_name_is_parts_unknown(self):
        resp = self._create(request={"parts": ["copy", "typo_part"]})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "parts_unknown")

    def test_unknown_copy_length_is_copy_length_unknown(self):
        resp = self._create(request={"parts": ["copy"], "copy_length": "extra_long"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "copy_length_unknown")


# -- run_part("image_prompt") on a copy-only brief with no adopted output enqueues, does not
# -- raise, and never rewrites request_json.parts (it records what was requested, not what
# -- was produced) --------------------------------------------------------------------------

class RunPartWithoutAdoptedCopyTest(_WorkbenchPartsTestBase):
    def test_run_image_prompt_on_copy_only_brief_enqueues_and_leaves_parts_unchanged(self):
        create_resp = self._create(request={"parts": ["copy"]})
        self.assertEqual(create_resp.status_code, 201)
        brief_id = create_resp.json()["brief"]["id"]

        # 模擬「送出那一輪已經跑完」（比照 test_workbench_api.py 同名手法）——這裡只驗
        # `run_part()` 本身的行為，不需要真的跑一輪 worker。
        web.conn.execute(
            "UPDATE workbench_brief SET status = 'done' WHERE id = %s", (brief_id,)
        )
        web.conn.commit()

        run_resp = self.client.post(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}/parts/image_prompt/run",
            json={"count": 2},
        )
        self.assertEqual(run_resp.status_code, 200)
        self.assertTrue(background_module.is_active(f"workbench:{brief_id}:image_prompt"))

        detail = self.client.get(
            f"/api/workbench/brands/{self.brand_id}/briefs/{brief_id}"
        ).json()["brief"]
        self.assertEqual(detail["request"]["parts"], ["copy"])


if __name__ == "__main__":
    unittest.main()
