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

    def _last_task(self) -> dict:
        row = web.conn.execute(
            "SELECT error, error_code FROM llm_task WHERE brand_id = %s"
            " AND task_type = 'workbench_free_parse' ORDER BY started_at DESC LIMIT 1",
            (self.brand_id,),
        ).fetchone()
        return dict(row)


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

    def test_validate_reply_never_reads_the_models_style_hint(self):
        # F07-I09（Decision 25，Y11）：舊全域風格庫退休——`_validate_reply` 的 `style_hint`
        # 永遠是 `None`，即使模型送了「ugc」（改回讀模型的值要讓這條紅），鍵本身仍在（給腳本化
        # 的 e2e 回覆合併，drop 掉這個鍵要讓下面的 `assertIn` 紅）。
        validated = free_parse._validate_reply({
            "topic": "夜跑廣告", "outputs": [{"part": "image_prompt", "count": 5}],
            "style_hint": "ugc",
        })
        self.assertIsNotNone(validated)
        self.assertIn("style_hint", validated)
        self.assertIsNone(validated["style_hint"])


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
        self.assertEqual(result["reason"], "reply_invalid")
        self.assertIsNone(result["error_code"])
        self.assertEqual(
            result["note"], "AI 這次沒有讀懂（回覆裡沒有可以用的產出項目），先照預設往下。",
        )
        self.assertEqual(result["spec"], self.defaults)
        self.assertEqual(self._task_count(), 1)
        self.assertEqual(self._last_task()["error_code"], "program_refused")
        self.assertTrue(self._last_task()["error"].startswith("reply_invalid: "))


class NonJsonReplyTest(_FreeParseTestBase):
    def test_non_json_reply_falls_back_to_defaults(self):
        free_parse.PROVIDER = _fake("這是一段散文，不是 JSON。")

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="做一些東西",
            defaults=self.defaults,
        )

        self.assertFalse(result["parsed"])
        self.assertEqual(result["reason"], "reply_unreadable")
        self.assertEqual(
            result["note"], "AI 這次沒有讀懂（回覆不是看得懂的格式），先照預設往下。",
        )
        self.assertEqual(result["spec"], self.defaults)
        self.assertEqual(self._task_count(), 1)
        self.assertEqual(self._last_task()["error_code"], "program_refused")


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
        # F50 Contract J: the fallback keeps why — the provider timed out.
        self.assertEqual(result["reason"], "llm_failed")
        self.assertEqual(result["error_code"], "timeout")
        self.assertEqual(result["note"], "AI 這次沒有讀懂（等太久沒有回應），先照預設往下。")
        self.assertEqual(result["spec"], self.defaults)
        # The provider's own error is kept on the row, never replaced.
        self.assertEqual(self._last_task()["error"], "AI 服務逾時未回應，請再試一次。")
        # max_retries=0：逾時只寫一列，不因為 gateway 預設的重試邏輯多花一次錢
        # （票面理由：使用者盯著轉圈圈的按鈕，不是背景 worker 排隊）。
        self.assertEqual(self._task_count(), 1)


class ScriptedReplyParsesTest(_FreeParseTestBase):
    """形狀絆線（F06-I05）：`providers.SCRIPTED_REPLIES["workbench_free_parse"]` 必須通過
    `free_parse.parse` 自己的驗證，e2e 才不會在這裡默默掉進 parsed=False 的退路。"""

    def test_scripted_reply_parses(self):
        reply = json.dumps(providers.SCRIPTED_REPLIES["workbench_free_parse"], ensure_ascii=False)
        free_parse.PROVIDER = _fake(reply)

        result = free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="做一些東西",
            defaults=self.defaults,
        )

        self.assertTrue(result["parsed"])
        self.assertEqual(result["spec"]["outputs"], [{"part": "image_prompt", "count": 1}])


class NoStyleQuestionInPromptTest(_FreeParseTestBase):
    def test_prompt_never_asks_the_model_to_map_an_existing_style(self):
        """Y12（F07-I09）：舊 `free_parse.md` 曾要模型把描述「對應到哪一種既有風格」——
        風格庫退休後，送給模型的 prompt 不再問這件事。"""
        reply = json.dumps({
            "topic": "夜跑廣告", "outputs": [{"part": "image_prompt", "count": 5}],
            "style_hint": "ugc", "platform": "Meta", "size": "4:5",
            "audience": None, "key_message": None,
        }, ensure_ascii=False)
        provider = _fake(reply)
        free_parse.PROVIDER = provider

        free_parse.parse(
            web.conn, brand_id=self.brand_id, free_text="幫我做幾張圖", defaults=self.defaults,
        )

        self.assertNotIn("既有風格", str(provider.calls))


if __name__ == "__main__":
    unittest.main()
