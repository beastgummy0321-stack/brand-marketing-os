"""app/tests/test_workbench_copy_length.py — F01-T01-I02: one copy run produces one length,
the one the brief asked for, and records which one in `body_json.copy_length`
(ARCHITECTURE.md §5.5). Workbench-only fixture (`workbench.may_depend_on` is `[]` — no
`app.schedule` import; `validate.check_copy` never compares coordinates against a seeded
vocabulary here since every brief is submitted with `"coordinates": {}`, so an empty
vocabulary is fine, see `app/workbench/validate.py:93-103`).
"""

import json
import unittest

import app.background as background_module
import app.shared.web as web
import app.workbench as workbench_module
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.workbench import jobs as workbench_jobs

ACTOR = "測試員"


def _cjk(n: int) -> str:
    base = "測試文案內容真實好用推薦體驗品質細節故事風格"
    return (base * (n // len(base) + 1))[:n]


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=500, output_tokens=200), stop_reason="end_turn",
    ))


_BODIES = {
    "short": lambda: [_cjk(140) for _ in range(5)],
    "medium": lambda: [_cjk(450) for _ in range(3)],
    "long": lambda: [_cjk(950) for _ in range(2)],
}


class _CopyLengthTestBase(unittest.TestCase):
    def setUp(self):
        workbench_module.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：文案長度", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(
            web.conn, self.brand_id, name="測試產品：文案長度", actor=ACTOR,
        )
        self._orig_provider = workbench_jobs.PROVIDER

    def tearDown(self):
        workbench_jobs.PROVIDER = self._orig_provider

    def _submit(self, copy_length: str) -> str:
        brief = {
            "source_kind": "manual", "source_ref": {},
            "product_id": self.product["id"], "coordinates": {}, "visual_tone": None,
            "visual_concept": None, "style_key": "ugc",
            "request": {"parts": ["copy"], "copy_length": copy_length},
        }
        return workbench_module.submit_brief(web.conn, self.org_id, self.brand_id, brief)

    def _run_worker(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _output(self, brief_id: str) -> dict:
        row = web.conn.execute(
            "SELECT * FROM workbench_output WHERE brief_id = %s AND part = 'copy'",
            (brief_id,),
        ).fetchone()
        return dict(row)


# -- 三個長度各自送一次，回覆只帶那一個長度鍵 -> 全綠、body_json.copy_length 記對長度 -----

class EachLengthRoundTripTest(_CopyLengthTestBase):
    def test_each_length_passes_and_records_itself(self):
        for copy_length in ("short", "medium", "long"):
            with self.subTest(copy_length=copy_length):
                brief_id = self._submit(copy_length)
                reply = {
                    "coordinates": {}, copy_length: _BODIES[copy_length](),
                    "headlines": [_cjk(10) for _ in range(5)],
                    "descriptions": [_cjk(15) for _ in range(5)],
                    "visual_tone": None, "visual_concept": "測試視覺概念", "warnings": [],
                }
                workbench_jobs.PROVIDER = _fake(json.dumps(reply, ensure_ascii=False))
                self._run_worker()

                output = self._output(brief_id)
                body = output["body_json"]
                self.assertEqual(body["copy_length"], copy_length)
                validation = body["validation"]
                self.assertTrue(validation)
                self.assertTrue(all(line.startswith("✅") for line in validation), validation)


# -- 回覆帶錯的長度鍵（工單要 medium，回覆只有 short）-> 失敗項目的 path 就是要求的長度 -----

class WrongLengthKeyFailsAtRequestedPathTest(_CopyLengthTestBase):
    def test_wrong_band_fails_with_item_at_requested_path(self):
        brief_id = self._submit("medium")
        reply = {
            "coordinates": {}, "short": _BODIES["short"](),  # 工單要 medium，回覆只給 short
            "headlines": [_cjk(10) for _ in range(5)],
            "descriptions": [_cjk(15) for _ in range(5)],
            "visual_tone": None, "visual_concept": "測試視覺概念", "warnings": [],
        }
        workbench_jobs.PROVIDER = _fake(json.dumps(reply, ensure_ascii=False))
        self._run_worker()

        output = self._output(brief_id)
        body = output["body_json"]
        self.assertEqual(body["copy_length"], "medium")
        validation = body["validation"]
        fail = next(line for line in validation if line.split("：", 1)[0].endswith("medium"))
        self.assertTrue(fail.startswith("❌"), fail)


if __name__ == "__main__":
    unittest.main()
