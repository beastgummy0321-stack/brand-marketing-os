"""app/tests/test_intake_research.py — 建檔精靈系統自跑品牌調研（F05-I09）。

見 app/intake/research.py。全程用 FakeProvider（跟 test_intake_api.py 同風格），不發任何
真實網路請求；品牌名一律虛構。隔離 DB、假金鑰。
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-research-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.background as background_module  # noqa: E402
import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.intake import ai as intake_ai  # noqa: E402
from app.intake import repository as ir  # noqa: E402
from app.intake import research, script, state  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

_SEQ = [0]


def _fake_response(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = research.fetch_url
        research.fetch_url = lambda url: (False, "")

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        research.fetch_url = self._orig_fetch
        self._envpatch.stop()

    def _brand_name(self) -> str:
        _SEQ[0] += 1
        return f"虛構建檔調研測試品牌{_SEQ[0]}"

    def _create_full(self) -> str:
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "description": "一句測試用的品牌描述文字。",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        return body["brand_id"]

    def _poll(self, bid: str) -> dict:
        web.conn.commit()
        background_module.app().run_worker(wait=False)
        return self.client.get(f"/api/intake/brands/{bid}/research/status").json()["data"]


class ResearchBackgroundTest(_Base):
    def test_success_creates_items_reaching_confirm(self):
        bid = self._create_full()
        bi_repo.create_product(web.conn, bid, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(script.PASTE_SAMPLE_SUCCESS))

        resp = self.client.post(f"/api/intake/brands/{bid}/research/start")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["limit_block"])

        status = self._poll(bid)
        self.assertEqual(status["status"], "done")

        draft = state.get_draft(bid)
        items = ir.list_pending_items(web.conn, bid, draft["id"])
        self.assertEqual(len(items), 23)

        # 唯一的寫入者：confirm 一筆走到既有的 target_table（跟貼回頁同一條路，不是第二條）。
        item = items[0]
        resp = self.client.post(f"/api/intake/brands/{bid}/review/{item['i']}", json={
            "outcome": "confirm", "kind": item["kind"], "category": item["category"],
            "title": item["title"], "content": item["content"], "scope": item["scope"],
            "severity": "soft",
        })
        self.assertEqual(resp.status_code, 204)
        row = web.conn.execute(
            "SELECT outcome, target_table FROM intake_item WHERE brand_id = %s AND row_no = %s",
            (bid, item["i"])).fetchone()
        self.assertEqual(row["outcome"], "confirmed")
        self.assertIsNotNone(row["target_table"])

    def test_bad_format_keeps_paste_raw_and_reports_failed(self):
        bid = self._create_full()
        garbage = "這次調研有點趕，先把重點寫給你，細節之後再補。"
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(garbage))

        resp = self.client.post(f"/api/intake/brands/{bid}/research/start")
        self.assertEqual(resp.status_code, 200)
        status = self._poll(bid)
        self.assertEqual(status["status"], "failed")
        self.assertIsNotNone(status["error"])

        draft = state.get_draft(bid)
        self.assertEqual(draft["paste_raw"], garbage)

    def test_over_budget_blocks_before_calling_ai_or_queueing(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 0.05})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))

        resp = self.client.post(f"/api/intake/brands/{bid}/research/start")
        self.assertEqual(resp.status_code, 200)
        block = resp.json()["limit_block"]
        self.assertIsNotNone(block)
        self.assertEqual(block["kind"], "research")
        self.assertEqual(block["budget_limit"], 0.05)
        self.assertEqual(intake_ai.PROVIDER.calls, [])

        row = web.conn.execute(
            "SELECT COUNT(*) AS n FROM llm_task WHERE brand_id = %s "
            "AND task_type = 'intake_research'",
            (bid,),
        ).fetchone()
        self.assertEqual(row["n"], 0)


class _SeqProvider(FakeProvider):
    """Replies with `texts` in order (the last one repeats); records calls like FakeProvider."""

    def __init__(self, texts, *, tokens: int = 10):
        super().__init__()
        self._texts = list(texts)
        self._tokens = tokens

    def complete(self, **kwargs):
        super().complete(**kwargs)
        text = self._texts[min(len(self.calls), len(self._texts)) - 1]
        return ProviderResponse(output_text=text, structured=None,
                                usage=Usage(input_tokens=self._tokens, output_tokens=self._tokens),
                                stop_reason="end_turn")


class ResearchReaskAndJobStatusTest(_Base):
    """F31-I02: one automatic re-ask when the table cannot be read, and the Contract J
    status rule (the newest queued job decides before any `llm_task` row)."""

    _GARBAGE = "這次調研有點趕，先把重點寫給你，細節之後再補。"

    def test_unreadable_first_reply_is_reasked_once_then_lands(self):
        """Red on master: no re-ask, the status read `failed` after one call."""
        bid = self._create_full()
        bi_repo.create_product(web.conn, bid, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        intake_ai.PROVIDER = _SeqProvider([self._GARBAGE, script.PASTE_SAMPLE_SUCCESS])

        self.client.post(f"/api/intake/brands/{bid}/research/start")
        status = self._poll(bid)

        self.assertEqual(status["status"], "done")
        self.assertEqual(len(intake_ai.PROVIDER.calls), 2)
        reask = intake_ai.PROVIDER.calls[1]["messages"][0]["content"]
        self.assertIn("上一次的回覆讀不出來", reask)
        draft = state.get_draft(bid)
        self.assertEqual(len(ir.list_pending_items(web.conn, bid, draft["id"])), 23)

    def test_reask_is_skipped_when_the_cost_limit_blocks_it(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/budget",
                         json={"limit": script.COST_RESEARCH_STANDARD})
        intake_ai.PROVIDER = _SeqProvider([self._GARBAGE, script.PASTE_SAMPLE_SUCCESS],
                                          tokens=20000)

        resp = self.client.post(f"/api/intake/brands/{bid}/research/start")
        self.assertIsNone(resp.json()["limit_block"])
        status = self._poll(bid)

        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)
        self.assertEqual(status["status"], "failed")
        self.assertEqual(state.get_draft(bid)["paste_raw"], self._GARBAGE)

    def test_new_job_queued_behind_a_failed_row_reads_running(self):
        """Red on master: the older failed `llm_task` row won and the status read `failed`."""
        from app.llm.providers import AnthropicProvider
        bid = self._create_full()
        intake_ai.PROVIDER = AnthropicProvider()  # no key: the AI call fails, row = failed
        self.client.post(f"/api/intake/brands/{bid}/research/start")
        self.assertEqual(self._poll(bid)["status"], "failed")

        self.client.post(f"/api/intake/brands/{bid}/research/start")  # queued, not yet run
        web.conn.commit()
        status = self.client.get(f"/api/intake/brands/{bid}/research/status").json()["data"]

        self.assertEqual(status["status"], "running")
        self._poll(bid)  # drain the queued job so no later test's worker picks it up

    def test_job_failing_before_the_ai_call_reads_failed_with_worker_hint(self):
        """Red on master: the handler swallowed the exception, no `llm_task` row existed and
        the status read idle `done` with an empty stage."""
        bid = self._create_full()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        before_ai = RuntimeError("模擬呼叫前出錯")
        with mock.patch.object(research, "build_prompt", side_effect=before_ai):
            self.client.post(f"/api/intake/brands/{bid}/research/start")
            status = self._poll(bid)

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], background_module.JOB_FAILED_MESSAGE)
        self.assertEqual(intake_ai.PROVIDER.calls, [])


class ResearchPromptTest(_Base):
    def test_prompt_forbids_customer_quotes_and_states_no_internet(self):
        bid = self._create_full()
        draft = state.require_draft(bid)
        existing = ir.existing_confirmed_data(web.conn, bid)
        prompt = research.build_prompt(web.conn, draft, existing)

        self.assertIn("你沒有網路", prompt)
        self.assertIn("這一輪不整理「顧客原話」", prompt)
        # 不是照抄 script.build_prompt——那份是寫給能上網的外部 AI 用的，會要求逐句挖顧客原話。
        self.assertNotIn("接案前的調研", prompt)
        self.assertNotIn("引用至少 5 句原文", prompt)


if __name__ == "__main__":
    unittest.main()
