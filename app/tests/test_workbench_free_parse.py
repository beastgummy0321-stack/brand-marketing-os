"""app/tests/test_workbench_free_parse.py — F02-I06: 自由創作「AI 解析結果」的唯一入口
(`app/workbench/free_parse.py`). FakeProvider only, no real network request — the falsifier
this ticket asks for. Covers: a valid reply parses into the shape the caller needs, an unknown
`part`/non-JSON reply/provider timeout all fall back to the caller's `defaults` with no
exception, and exactly one `llm_task` row lands per call (`max_retries=0`, ticket rationale:
a person is watching a spinner, not a worker queue).
"""

import json
import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.workbench import free_parse

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


class _FreeParseTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：自由創作解析", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.defaults = {"outputs": [{"part": "image_prompt", "count": 1}]}
        self._orig_provider = free_parse.PROVIDER

    def tearDown(self):
        free_parse.PROVIDER = self._orig_provider

    def _task_count(self) -> int:
        row = web.conn.execute(
            "SELECT COUNT(*) AS c FROM llm_task WHERE brand_id = %s"
            " AND task_type = 'workbench_free_parse'",
            (self.brand_id,),
        ).fetchone()
        return row["c"]


class ValidReplyTest(_FreeParseTestBase):
    def test_valid_reply_returns_parsed_spec(self):
        reply = json.dumps({
            "topic": "夜跑廣告", "outputs": [{"part": "image_prompt", "count": 5}],
            "style_hint": "ugc", "platform": "Meta", "size": "4:5",
            "audience": None, "key_message": None,
        }, ensure_ascii=False)
        free_parse.PROVIDER = _fake(reply)

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id,
            free_text="幫 Beast Gummy 做五張夜跑廣告，風格真實、有競技感，適合 Meta 4:5",
            defaults=self.defaults,
        )

        self.assertTrue(result["parsed"])
        self.assertIsNone(result["note"])
        self.assertEqual(result["spec"]["outputs"], [{"part": "image_prompt", "count": 5}])
        self.assertEqual(result["spec"]["size"], "4:5")
        self.assertEqual(result["spec"]["platform"], "Meta")
        self.assertEqual(self._task_count(), 1)


class UnknownPartTest(_FreeParseTestBase):
    def test_unknown_part_falls_back_to_defaults(self):
        reply = json.dumps({
            "topic": "夜跑廣告", "outputs": [{"part": "storyboard", "count": 2}],
        }, ensure_ascii=False)
        free_parse.PROVIDER = _fake(reply)

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="做一些東西",
            defaults=self.defaults,
        )

        self.assertFalse(result["parsed"])
        self.assertEqual(result["note"], free_parse.NOT_PARSED_NOTE)
        self.assertEqual(result["spec"], self.defaults)
        self.assertEqual(self._task_count(), 1)


class NonJsonReplyTest(_FreeParseTestBase):
    def test_non_json_reply_falls_back_to_defaults(self):
        free_parse.PROVIDER = _fake("這是一段散文，不是 JSON。")

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="做一些東西",
            defaults=self.defaults,
        )

        self.assertFalse(result["parsed"])
        self.assertEqual(result["note"], free_parse.NOT_PARSED_NOTE)
        self.assertEqual(result["spec"], self.defaults)
        self.assertEqual(self._task_count(), 1)


class ProviderTimeoutTest(_FreeParseTestBase):
    def test_timeout_falls_back_to_defaults_with_exactly_one_task_row(self):
        free_parse.PROVIDER = providers.FakeProvider(
            exception=providers.ProviderTimeoutError("AI 服務逾時未回應，請再試一次。"),
        )

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="做一些東西",
            defaults=self.defaults,
        )

        self.assertFalse(result["parsed"])
        self.assertEqual(result["note"], free_parse.NOT_PARSED_NOTE)
        self.assertEqual(result["spec"], self.defaults)
        # max_retries=0：逾時只寫一列，不因為 gateway 預設的重試邏輯多花一次錢
        # （票面理由：使用者盯著轉圈圈的按鈕，不是背景 worker 排隊）。
        self.assertEqual(self._task_count(), 1)


if __name__ == "__main__":
    unittest.main()
