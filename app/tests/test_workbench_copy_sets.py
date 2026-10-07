"""app/tests/test_workbench_copy_sets.py — ticket F02-I01: one copy round is 5 complete sets
(ARCHITECTURE.md §5.6), not three pools (`short`／`medium`／`long` bodies + a shared
`headlines`／`descriptions` pool). Falsifier for `validate.check_copy`'s new `sets` shape.

Pure-function tests, no DB (follows `test_workbench_image_prompt.py`'s structure): `check_copy`
takes data + vocabulary + copy_length as plain arguments. `workbench.may_depend_on == []` — no
`app.schedule` import here; the `_copy_summary()` index-aligned read of `sets` is covered in
`test_workbench.py` (one of the declared legacy seam tests that already imports both sides,
ARCHITECTURE.md §2).
"""

import json
import unittest
from unittest.mock import patch

from app import workbench
from app.brand_intelligence import repository as brands
from app.core import db
from app.llm import gateway, providers
from app.workbench import jobs, repository, validate

ACTOR = "測試員"


def _cjk(n: int) -> str:
    """n 個中文字（不含換行）——灌出剛好落在某個字數帶的假文案，不必手動數字數。"""
    base = "測試文案內容真實好用推薦體驗品質細節故事風格"
    return (base * (n // len(base) + 1))[:n]


def _set(body_len: int = 140, headline_len: int = 10, description_len: int = 15) -> dict:
    return {
        "body": _cjk(body_len), "headline": _cjk(headline_len),
        "description": _cjk(description_len),
    }


class CheckCopySetsShapeTest(unittest.TestCase):
    def test_five_valid_sets_all_green(self):
        data = {
            "coordinates": {}, "sets": [_set() for _ in range(5)],
            "visual_tone": None, "visual_concept": "一句話的畫面概念",
        }
        results = validate.check_copy(data, vocabulary={}, copy_length="short")
        self.assertTrue(all(r["ok"] for r in results), results)

    def test_four_sets_fails_on_sets(self):
        data = {
            "coordinates": {}, "sets": [_set() for _ in range(4)],
            "visual_tone": None, "visual_concept": "一句話的畫面概念",
        }
        results = validate.check_copy(data, vocabulary={}, copy_length="short")
        item = next(r for r in results if r["path"] == "sets")
        self.assertFalse(item["ok"])
        self.assertEqual(item["message"], "數量應為 5，實際 4")
        # 數量不對時，逐項的 body／headline／description 不會另外報一輪。
        self.assertFalse(any(r["path"].startswith("sets[") for r in results))

    def test_body_out_of_band_fails_only_that_items_body(self):
        sets = [_set() for _ in range(5)]
        sets[2]["body"] = _cjk(200)  # 短版帶是 100～150，200 超出。
        data = {
            "coordinates": {}, "sets": sets,
            "visual_tone": None, "visual_concept": "一句話的畫面概念",
        }
        results = validate.check_copy(data, vocabulary={}, copy_length="short")
        by_path = {r["path"]: r for r in results}
        self.assertFalse(by_path["sets[3].body"]["ok"])
        self.assertTrue(by_path["sets[3].headline"]["ok"])
        self.assertTrue(by_path["sets[3].description"]["ok"])
        # 其他 4 組的 body 不受影響。
        for i in (1, 2, 4, 5):
            self.assertTrue(by_path[f"sets[{i}].body"]["ok"], by_path[f"sets[{i}].body"])

    def test_headline_over_limit_fails_only_that_headline(self):
        sets = [_set() for _ in range(5)]
        sets[0]["headline"] = _cjk(30)  # 上限 27 字。
        data = {
            "coordinates": {}, "sets": sets,
            "visual_tone": None, "visual_concept": "一句話的畫面概念",
        }
        results = validate.check_copy(data, vocabulary={}, copy_length="short")
        by_path = {r["path"]: r for r in results}
        self.assertFalse(by_path["sets[1].headline"]["ok"])
        self.assertTrue(by_path["sets[1].body"]["ok"])
        self.assertTrue(by_path["sets[1].description"]["ok"])


class CreativeGatewayContractTest(unittest.TestCase):
    def test_stored_brief_reaches_one_gateway_call_and_keeps_five_candidates(self):
        conn = db.current()
        brand = brands.create_brand(
            conn, org_id=db.DEV_ORG_ID, name="Fixture shop", actor="test", client_name=None
        )["id"]
        workbench.register_tasks()
        creative = {
            "provenance": {
                "state": "adopted",
                "current_revision": "revision",
                "accepted_revision": "revision",
                "operation_id": "operation",
                "slot_id": "slot",
            },
            "assignment": {
                "ad_id": "actual-ad",
                "group_id": "actual-group",
                "role": "explore",
                "customer_group_id": "actual-customer",
                "scene": "buyer-situation",
                "offer_key": "none",
            },
            "test_intent": "Test a different buyer situation, not a headline substitution",
            "evidence_refs": [{"kind": "result", "id": "prior-ad"}],
            "comparison": {
                "controls": [
                    {
                        "creative": {
                            "asset_id": "original-image",
                            "placement_revision": 4,
                            "copy_fields": {"body": "exact original control"},
                        }
                    }
                ],
                "results": [{"ad_id": "prior-ad", "flags": ["small sample"]}],
                "calendar": [{"id": "known-event", "name": "known period event"}],
                "selected_offer": {"key": "none", "sentence": None},
                "omitted": {"results": 18},
            },
            "input_hash": "full-comparison-hash",
        }
        workbench.submit_pack(
            conn,
            db.DEV_ORG_ID,
            brand,
            {
                "source_kind": "schedule_node",
                "source_ref": {"fixture": "creative"},
                "sets": [
                    {
                        "name": "Creative test",
                        "source_ref": {"fixture": "creative", "ad": "actual-ad"},
                        "required_outputs": {"copy": 1},
                        "request": {"copy_length": "short", "creative_brief": creative},
                    }
                ],
            },
        )
        brief = workbench.briefs_for_source(
            conn, db.DEV_ORG_ID, brand, "schedule_node", {"fixture": "creative"}
        )[0]
        output = {
            "coordinates": {},
            "sets": [_set() for _ in range(5)],
            "visual_tone": None,
            "visual_concept": "Fixture concept",
            "warnings": ["Fixture response; semantic quality is unverified"],
        }
        raw = json.dumps(output, ensure_ascii=False)
        fake = providers.FakeProvider(
            response=providers.ProviderResponse(
                output_text=raw,
                structured=output,
                usage=providers.Usage(input_tokens=100, output_tokens=100),
                stop_reason="end_turn",
            )
        )
        with patch.object(jobs, "PROVIDER", fake):
            jobs._run(conn, db.DEV_ORG_ID, brand, brief["id"], "copy", None)
        self.assertEqual(len(fake.calls), 1)
        prompt = fake.calls[0]["messages"][0]["content"]
        for expected in (
            "actual-ad",
            "actual-customer",
            "buyer-situation",
            "original-image",
            "exact original control",
            "small sample",
            "known period event",
            creative["test_intent"],
        ):
            self.assertIn(expected, prompt)
        self.assertEqual(prompt.count("exact original control"), 1)
        self.assertNotIn("full-comparison-hash", prompt)
        tasks = gateway.find_tasks_for_scope(
            conn,
            org_id=db.DEV_ORG_ID,
            brand_id=brand,
            task_type="workbench_copy",
            context_scope={"brief_id": brief["id"]},
        )
        self.assertEqual(tasks[0]["rendered_output"], raw)
        self.assertEqual(
            tasks[0]["context_scope_json"]["creative_input_hash"], "full-comparison-hash"
        )
        self.assertEqual(
            tasks[0]["context_scope_json"]["strategy_provenance"], creative["provenance"]
        )
        detail = repository.set_detail(conn, db.DEV_ORG_ID, brand, brief["id"])
        self.assertEqual(len(detail["products"]["copy"]["versions"]), 5)
        self.assertEqual(
            detail["products"]["copy"]["versions"][0]["body"]["body"], output["sets"][0]["body"]
        )


if __name__ == "__main__":
    unittest.main()
