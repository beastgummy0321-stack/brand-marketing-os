"""app/tests/test_llm_gateway.py — LLM Gateway 骨架、Context Compiler。

三份原始文件皆已被 5eca0db 清除；llm_task 欄位權威見 supabase/migrations/ 本身。
全程只用 FakeProvider，不發出任何真實網路請求。
"""

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import anthropic

from app.brand_intelligence import repository as repo
from app.core import config, db, rule_cards, vocab
from app.core import settings as coresettings
from app.llm import context_compiler, gateway, pricing, providers
from app.llm.providers import (
    FakeProvider,
    ProviderError,
    ProviderResponse,
    ProviderTimeoutError,
    SpendCapExceededError,
    Usage,
)


class LLMGatewayTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌A（Gateway測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

    def _context(self):
        return gateway.TaskContext(
            context_scope={"brand_id": self.brand["id"]},
            knowledge_item_ids=["bft_dummy1", "bft_dummy2"],
            brand_version=self.brand["knowledge_version"],
            product_version=None,
        )

    def _rows_for_brand(self):
        return [
            dict(r) for r in self.conn.execute(
                "SELECT * FROM llm_task WHERE brand_id = %s ORDER BY attempt_no", (self.brand["id"],)
            ).fetchall()
        ]

    def test_success_flow_writes_full_llm_task_row(self):
        fake_response = ProviderResponse(
            output_text="這是模型的完整輸出內容",
            structured={"summary": "重點摘要", "score": 87},
            usage=Usage(input_tokens=1000, output_tokens=2000,
                        cache_read_input_tokens=100, cache_creation_input_tokens=50),
            stop_reason="end_turn",
        )
        provider = FakeProvider(response=fake_response)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="analyzeBrandContext",
            prompt_template_id="tpl_brand_context", prompt_template_version="v1",
            system="你是品牌分析助手", messages=[{"role": "user", "content": "請分析品牌 A"}],
            context=self._context(),
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["attempt_no"], 1)
        self.assertEqual(row["brand_id"], self.brand["id"])
        self.assertEqual(row["task_type"], "analyzeBrandContext")
        self.assertEqual(row["provider"], "fake")
        self.assertEqual(row["model"], "claude-opus-5")
        self.assertEqual(row["prompt_template_id"], "tpl_brand_context")
        self.assertEqual(row["prompt_template_version"], "v1")
        self.assertIsNone(row["error"])
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["finished_at"])

        # 輸出逐字保留，不改寫（principles 第 2 條）
        self.assertEqual(row["rendered_output"], "這是模型的完整輸出內容")
        self.assertEqual(row["structured_output_json"], {"summary": "重點摘要", "score": 87})

        usage = row["usage_json"]
        self.assertEqual(usage["input_tokens"], 1000)
        self.assertEqual(usage["output_tokens"], 2000)
        self.assertEqual(usage["cache_read_input_tokens"], 100)
        self.assertEqual(usage["cache_creation_input_tokens"], 50)

        # 上下文稽核欄位
        self.assertEqual(row["context_scope_json"], {"brand_id": self.brand["id"]})
        self.assertEqual(row["knowledge_item_ids_json"], ["bft_dummy1", "bft_dummy2"])
        self.assertEqual(row["brand_version"], self.brand["knowledge_version"])
        self.assertIsNone(row["product_version"])

        # 只有一次呼叫，且沒有帶 temperature/top_p/top_k/thinking 之類的參數；effort（票 #27
        # 思考等級解析結果）與 tools（ADR 0005 網路搜尋）是後來新增的欄位——任務型別不在
        # 任務預設對照表裡，思考等級退回中檔；沒指定工具時 tools 是 None（預設不開）。
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(set(provider.calls[0].keys()),
                         {"model", "system", "messages", "max_tokens", "timeout_s", "effort",
                          "tools"})
        self.assertEqual(provider.calls[0]["effort"], "medium")
        self.assertIsNone(provider.calls[0]["tools"])

    def test_cost_calculated_from_usage_and_price_table(self):
        fake_response = ProviderResponse(
            output_text="x", structured=None,
            usage=Usage(input_tokens=200_000, output_tokens=10_000),
            stop_reason="end_turn",
        )
        provider = FakeProvider(response=fake_response)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="generateScripts",
            prompt_template_id="tpl_scripts", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "產生腳本"}],
            context=self._context(),
        )

        expected_cost = pricing.calculate_cost("claude-opus-5", 200_000, 10_000)
        self.assertAlmostEqual(row["cost"], expected_cost, places=9)
        self.assertAlmostEqual(row["cost"], (200_000 / 1_000_000) * 5.0 + (10_000 / 1_000_000) * 25.0, places=9)

    def test_failure_then_retry_creates_second_row_with_attempt_no_2(self):
        provider = FakeProvider(exception=ProviderError("暫時連線失敗"), fail_first_n=1)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="createCampaignPlan",
            prompt_template_id="tpl_plan", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "擬計畫"}],
            context=self._context(),
        )

        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["attempt_no"], 2)

        rows = self._rows_for_brand()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["attempt_no"], 1)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["error"], "暫時連線失敗")
        self.assertIsNone(rows[0]["rendered_output"])
        self.assertEqual(rows[1]["attempt_no"], 2)
        self.assertEqual(rows[1]["status"], "succeeded")
        # 兩列是不同的 id——重試是新的一列，不冒充前次（principles 第 6 條）
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_refusal_is_reported_as_failure_and_capped_at_one_retry(self):
        provider = FakeProvider(exception=ProviderError("模型婉拒本次請求（分類：cyber）"), fail_first_n=2)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="analyzeBrandContext",
            prompt_template_id="tpl_brand_context", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "分析"}],
            context=self._context(),
        )

        # 全部嘗試皆婉拒：回傳最後一次的失敗列，不偽裝成功、不編造內容
        self.assertEqual(row["status"], "failed")
        self.assertIn("婉拒", row["error"])
        self.assertIsNone(row["rendered_output"])
        self.assertIsNone(row["structured_output_json"])

        rows = self._rows_for_brand()
        self.assertEqual(len(rows), 2)  # 重試 1 次＝總共最多 2 次嘗試
        self.assertTrue(all(r["status"] == "failed" for r in rows))
        self.assertEqual(provider.calls.__len__(), 2)

    def test_timeout_status_distinct_from_generic_failure(self):
        provider = FakeProvider(exception=ProviderTimeoutError("AI 服務逾時未回應"), fail_first_n=2)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="analyzePerformance",
            prompt_template_id="tpl_perf", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "判讀成效"}],
            context=self._context(),
        )

        self.assertEqual(row["status"], "timeout")
        rows = self._rows_for_brand()
        self.assertTrue(all(r["status"] == "timeout" for r in rows))

    def test_large_prompt_is_not_retried_even_with_max_retries_set(self):
        # 輸入長度 > LARGE_PROMPT_CHARS（24000）＋一定逾時的 provider：重送同樣的大 prompt
        # 只會再付一次同樣的錢，所以這個 brand_id 下只能多出 1 列，不是 max_retries+1 列。
        provider = FakeProvider(exception=ProviderTimeoutError("AI 服務逾時未回應"), fail_first_n=0)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="analyzePerformance",
            prompt_template_id="tpl_perf", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "x" * (gateway.LARGE_PROMPT_CHARS + 1)}],
            context=self._context(), options=gateway.TaskOptions(max_retries=2),
        )

        self.assertEqual(row["status"], "timeout")
        self.assertEqual(row["attempt_no"], 1)
        self.assertIn("不自動重試", row["error"])

        rows = self._rows_for_brand()
        self.assertEqual(len(rows), 1)

    def test_small_prompt_retry_behaviour_unchanged(self):
        # 對照組：短 message ＋ max_retries=1 ＋一定逾時的 provider → 照舊 2 列，
        # 錯誤訊息一個字不變（不含「不自動重試」）。
        provider = FakeProvider(exception=ProviderTimeoutError("AI 服務逾時未回應"), fail_first_n=0)

        row = gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="analyzePerformance",
            prompt_template_id="tpl_perf", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "判讀成效"}],
            context=self._context(), options=gateway.TaskOptions(max_retries=1),
        )

        self.assertEqual(row["status"], "timeout")
        self.assertEqual(row["error"], "AI 服務逾時未回應")

        rows = self._rows_for_brand()
        self.assertEqual(len(rows), 2)

    def test_llm_task_cost_stores_sub_cent_precision(self):
        # numeric(14,2) 會把不到半分錢的呼叫記成 0.00；migration 20260913000003 改成
        # numeric(14,6) 之後這裡必須讀回原值，不是被四捨五入成 0。
        row = gateway._insert_running_row(
            self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand["id"], task_type="analyzeBrandContext",
            context=self._context(), prompt_template_id="tpl_brand_context", prompt_template_version="v1",
            provider_name="fake", model="claude-opus-5", attempt_no=1,
        )
        gateway._mark_succeeded(
            self.conn, row["id"], structured_output=None, rendered_output="x",
            usage={"input_tokens": 1, "output_tokens": 1}, cost=0.000123,
        )
        stored = gateway.get_task(self.conn, row["id"])
        self.assertEqual(float(stored["cost"]), 0.000123)


class AnthropicStructuredToolTest(unittest.TestCase):
    def test_forced_tool_input_becomes_structured_response(self):
        captured = []
        structured = {"rows": [{"kind": "品牌事實"}]}
        sdk_response = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", name="submit_rows", input=structured)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=20, server_tool_use=None),
        )

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            def with_options(self, **_kwargs):
                return self

            @property
            def messages(self):
                return self

            def create(self, **kwargs):
                captured.append(kwargs)
                return sdk_response

        tool = {
            "name": "submit_rows",
            "description": "提交整理列。",
            "input_schema": {"type": "object", "properties": {"rows": {"type": "array"}},
                             "required": ["rows"]},
        }
        with mock.patch.object(
                providers.settings, "get_api_key", lambda *a, **k: "sk-ant-fake-test"), \
                mock.patch.object(anthropic, "Anthropic", FakeClient):
            response = providers.AnthropicProvider().complete(
                model="claude-opus-5", system=None,
                messages=[{"role": "user", "content": "整理"}], max_tokens=1000,
                tools=[tool], org_id=db.DEV_ORG_ID,
            )

        self.assertEqual(captured[0]["tools"], [tool])
        self.assertEqual(captured[0]["tool_choice"], {"type": "tool", "name": "submit_rows"})
        self.assertEqual(response.structured, structured)
        self.assertEqual(response.output_text, "")


class AnthropicRetryPolicyTest(unittest.TestCase):
    """守金額：SDK 不准自己偷偷重試。

    SDK 預設重試 2 次，一次 complete() 就是最多 3 個 HTTP 請求——逾時變成 3×timeout_s
    （實測 llm_01M167R89MVG8F7JK6YCQWM1NW 設 120 秒跑了 361.58 秒），而被放棄卻已經在
    伺服器端產生的回應照樣計費，永遠不會變成一列 llm_task。每月花費上限加總的就是
    llm_task.cost，看不到的那幾次生成＝上限漏算。重試歸 gateway 管，一次一列。
    """

    def test_sdk_retries_are_disabled_so_every_try_is_its_own_llm_task_row(self):
        captured = {}

        class FakeClient:
            def __init__(self, **_kwargs):
                pass

            def with_options(self, **kwargs):
                captured.update(kwargs)
                return self

            @property
            def messages(self):
                return self

            def create(self, **_kwargs):
                return SimpleNamespace(
                    stop_reason="end_turn", content=[],
                    usage=SimpleNamespace(input_tokens=1, output_tokens=1, server_tool_use=None))

        with mock.patch.object(
                providers.settings, "get_api_key", lambda *a, **k: "sk-ant-fake-test"), \
                mock.patch.object(anthropic, "Anthropic", FakeClient):
            providers.AnthropicProvider().complete(
                model="claude-opus-5", system=None, messages=[{"role": "user", "content": "嗨"}],
                max_tokens=100, timeout_s=7.0, org_id=db.DEV_ORG_ID)

        self.assertEqual(captured["max_retries"], 0)
        self.assertEqual(captured["timeout"], 7.0)


class TaskModelThinkingDefaultsTest(unittest.TestCase):
    """票 #27：任務 →（模型、思考等級）對照表、優先鏈（本次覆寫 > 任務預設 > 全域設定）、
    覆寫只生效一次、非法值退回預設不噴錯。全程 FakeProvider，不發任何真實網路請求。
    """

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌E（模型思考測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

    def _context(self):
        return gateway.TaskContext(
            context_scope={"brand_id": self.brand["id"]},
            knowledge_item_ids=[], brand_version=self.brand["knowledge_version"],
        )

    def _run(self, task_type):
        provider = FakeProvider()
        row = gateway.run_task(
            self.conn, provider, brand_id=self.brand["id"], task_type=task_type,
            prompt_template_id="tpl", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": "測試"}],
            context=self._context(),
        )
        return row, provider

    def test_resolve_thinking_uses_task_default(self):
        self.assertEqual(providers.resolve_thinking(task_type="schedule_plan"), "high")
        self.assertEqual(providers.resolve_thinking(task_type="workbench_image_prompt"), "medium")
        self.assertEqual(providers.resolve_thinking(task_type="intake_scan"), "low")

    def test_resolve_thinking_unknown_task_falls_back_to_medium(self):
        self.assertEqual(providers.resolve_thinking(task_type="不存在的任務"), "medium")
        self.assertEqual(providers.resolve_thinking(), "medium")

    def test_resolve_thinking_invalid_override_falls_back_without_error(self):
        # 表單被動手腳送了非法值，不噴錯，退回任務預設
        self.assertEqual(providers.resolve_thinking("亂打的值", task_type="schedule_plan"), "high")

    def test_gateway_uses_task_default_thinking_when_no_override(self):
        _row, provider = self._run("schedule_plan")
        self.assertEqual(provider.calls[0]["effort"], "high")
        _row, provider = self._run("intake_scan")
        self.assertEqual(provider.calls[0]["effort"], "low")

    def test_request_override_thinking_affects_only_one_call_then_reverts(self):
        with providers.request_overrides(thinking="max"):
            _row, provider = self._run("workbench_image_prompt")
        self.assertEqual(provider.calls[0]["effort"], "max")

        # 離開 with 區塊後，下一次呼叫回到任務預設（中）——覆寫值不落地
        _row2, provider2 = self._run("workbench_image_prompt")
        self.assertEqual(provider2.calls[0]["effort"], "medium")

    def test_request_override_model_affects_only_one_call_then_reverts(self):
        with providers.request_overrides(model="claude-sonnet-5"):
            row, _provider = self._run("schedule_plan")
        self.assertEqual(row["model"], "claude-sonnet-5")

        # 下一次呼叫回到全域設定（schedule_plan 本身沒有指定模型預設）
        row2, _provider2 = self._run("schedule_plan")
        self.assertEqual(row2["model"], "claude-opus-5")

    def test_request_override_invalid_thinking_ignored_not_raised(self):
        with providers.request_overrides(thinking="不是五檔之一"):
            _row, provider = self._run("workbench_image_prompt")
        self.assertEqual(provider.calls[0]["effort"], "medium")

    # 破壞者情境補洞：手改網址塞不存在的 model（例如 model=hacked-model-xyz），要退回
    # 預設不噴錯，不能一路通到 AnthropicProvider 真的打 API（驗證抓到的缺口）。

    def test_resolve_model_invalid_override_falls_back_without_error(self):
        self.assertEqual(
            providers.resolve_model("hacked-model-xyz", task_type="schedule_plan", conn=self.conn,
                                    brand_id=self.brand["id"]),
            "claude-opus-5")

    def test_resolve_model_valid_override_still_used(self):
        self.assertEqual(
            providers.resolve_model("claude-sonnet-5", task_type="schedule_plan", conn=self.conn,
                                    brand_id=self.brand["id"]),
            "claude-sonnet-5")

    def test_request_override_invalid_model_ignored_falls_back_without_error(self):
        with providers.request_overrides(model="hacked-model-xyz"):
            row, _provider = self._run("schedule_plan")
        self.assertEqual(row["model"], "claude-opus-5")

    def test_request_override_valid_model_still_effective(self):
        with providers.request_overrides(model="claude-fable-5"):
            row, _provider = self._run("schedule_plan")
        self.assertEqual(row["model"], "claude-fable-5")


class ContextCompilerTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def test_only_confirmed_facts_included_and_isolated_by_brand(self):
        brand_a = repo.create_brand(self.conn, name="品牌A（Compiler測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)
        brand_b = repo.create_brand(self.conn, name="品牌B（Compiler測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

        confirmed = repo.create_brand_fact(
            self.conn, brand_a["id"], fact_type="positioning", label="定位",
            value="A牌已確認的定位事實", status="confirmed", confirmed_by="小陳", actor="小陳",
        )
        pending = repo.create_brand_fact(
            self.conn, brand_a["id"], fact_type="tone", label="語氣",
            value="A牌待確認事實內容", status="pending", actor="小陳",
        )
        rule = repo.create_rule(
            self.conn, brand_a["id"], rule_type="visual", content="A牌硬規則內容",
            severity="hard", actor="小陳",
        )
        claim = repo.create_claim(
            self.conn, brand_a["id"], claim_text="A牌核准宣稱內容", claim_type="approved", actor="小陳",
        )

        # 品牌 B 塞入截然不同、易辨識的內容，確保絕不外洩進品牌 A 的組裝結果
        repo.create_brand_fact(
            self.conn, brand_b["id"], fact_type="positioning", label="定位",
            value="B牌獨有機密事實", status="confirmed", confirmed_by="小陳", actor="小陳",
        )
        repo.create_rule(
            self.conn, brand_b["id"], rule_type="visual", content="B牌獨有機密規則",
            severity="hard", actor="小陳",
        )
        repo.create_claim(
            self.conn, brand_b["id"], claim_text="B牌獨有機密宣稱", claim_type="approved", actor="小陳",
        )

        repo.create_rule(
            self.conn, brand_a["id"], rule_type=vocab.EXPERIMENT_RULE_TYPE,
            content="A牌要測的實驗內容", severity="soft", actor="小陳",
        )

        text, knowledge_item_ids, brand_version, product_version = context_compiler.compile(
            self.conn, brand_a["id"]
        )

        self.assertIn(confirmed["id"], knowledge_item_ids)
        self.assertIn(rule["id"], knowledge_item_ids)
        self.assertIn(claim["id"], knowledge_item_ids)
        self.assertNotIn(pending["id"], knowledge_item_ids)

        self.assertIn("A牌已確認的定位事實", text)
        self.assertIn("A牌硬規則內容", text)
        self.assertIn("A牌核准宣稱內容", text)
        self.assertNotIn("A牌待確認事實內容", text)
        self.assertNotIn("B牌獨有機密事實", text)
        self.assertNotIn("B牌獨有機密規則", text)
        self.assertNotIn("B牌獨有機密宣稱", text)

        # dead-code-sweep 票 04 刪了學習／猜想兩段之後，其餘段落標題不變（回歸鐵條）。
        self.assertIn("【限制】規則", text)
        # issue adopted-advice-can-invert：採用一條成效判讀寫出來的規則是「這一期要去做的
        # 事」，必須自己一段，不准混進【限制】——混在一起時模型會把「去測試 X」讀成「先不
        # 要用 X」（2026-09-06 演練，三個角色反了一個）。
        self.assertIn("【本期要測的】", text)
        self.assertIn("A牌要測的實驗內容", text)
        self.assertNotIn("A牌要測的實驗內容", text.split("【本期要測的】")[0])
        self.assertIn("【可以講】宣稱", text)
        self.assertIn("【事實】品牌事實", text)
        self.assertNotIn("已驗證的學習", text)
        self.assertNotIn("尚未驗證的猜想", text)

        self.assertEqual(brand_version, repo.get_brand(self.conn, brand_a["id"])["knowledge_version"])
        self.assertIsNone(product_version)

    def test_product_scope_includes_brand_level_but_excludes_other_products(self):
        brand = repo.create_brand(self.conn, name="品牌C（Compiler測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)
        product_1 = repo.create_product(self.conn, brand["id"], name="產品C-1", actor="小陳")
        product_2 = repo.create_product(self.conn, brand["id"], name="產品C-2", actor="小陳")

        brand_level_rule = repo.create_rule(
            self.conn, brand["id"], rule_type="visual", content="品牌整體規則內容",
            severity="hard", actor="小陳",
        )
        fact_1 = repo.create_product_fact(
            self.conn, brand["id"], product_1["id"], fact_type="ingredient", label="成分",
            value="產品1專屬事實內容", status="confirmed", confirmed_by="小陳", actor="小陳",
        )
        repo.create_product_fact(
            self.conn, brand["id"], product_2["id"], fact_type="ingredient", label="成分",
            value="產品2專屬事實內容", status="confirmed", confirmed_by="小陳", actor="小陳",
        )
        rule_1 = repo.create_rule(
            self.conn, brand["id"], product_id=product_1["id"], rule_type="claim",
            content="產品1專屬規則內容", severity="hard", actor="小陳",
        )
        repo.create_rule(
            self.conn, brand["id"], product_id=product_2["id"], rule_type="claim",
            content="產品2專屬規則內容", severity="hard", actor="小陳",
        )

        text, knowledge_item_ids, brand_version, product_version = context_compiler.compile(
            self.conn, brand["id"], product_1["id"]
        )

        self.assertIn(brand_level_rule["id"], knowledge_item_ids)
        self.assertIn(fact_1["id"], knowledge_item_ids)
        self.assertIn(rule_1["id"], knowledge_item_ids)

        self.assertIn("品牌整體規則內容", text)
        self.assertIn("產品1專屬事實內容", text)
        self.assertIn("產品1專屬規則內容", text)
        self.assertNotIn("產品2專屬事實內容", text)
        self.assertNotIn("產品2專屬規則內容", text)

        self.assertEqual(
            product_version, repo.get_product(self.conn, brand["id"], product_1["id"])["knowledge_version"]
        )

    def test_brand_only_scope_excludes_all_products_specific_items(self):
        brand = repo.create_brand(self.conn, name="品牌D（Compiler測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)
        product = repo.create_product(self.conn, brand["id"], name="產品D-1", actor="小陳")
        repo.create_rule(
            self.conn, brand["id"], product_id=product["id"], rule_type="claim",
            content="產品專屬規則不該出現在品牌層", severity="hard", actor="小陳",
        )
        repo.create_claim(
            self.conn, brand["id"], product_id=product["id"],
            claim_text="產品專屬宣稱不該出現在品牌層", claim_type="approved", actor="小陳",
        )

        text, knowledge_item_ids, _brand_version, product_version = context_compiler.compile(
            self.conn, brand["id"]
        )

        self.assertNotIn("產品專屬規則不該出現在品牌層", text)
        self.assertNotIn("產品專屬宣稱不該出現在品牌層", text)
        self.assertIsNone(product_version)

    def test_unknown_brand_raises_value_error(self):
        with self.assertRaises(ValueError):
            context_compiler.compile(self.conn, "brd_不存在")


class RuleNeverExpiresTest(unittest.TestCase):
    """dead-code-sweep 票 04：規則不再自動過期（曾經的 sweep 已刪，唯一救回來的入口只長
    在已刪除的累積智慧頁）。紅一次：把 sweep 呼叫加回 list_rules_for_brand() 開頭會轉紅。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌H（規則不過期測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

    def test_soft_rule_older_than_90_days_still_active_and_in_prompt(self):
        rule = repo.create_rule(
            self.conn, self.brand["id"], rule_type="tone", content="很久以前確認過的偏好規則",
            severity="soft", actor="小陳",
        )
        ancient = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        self.conn.execute(
            "UPDATE rule SET confirmed_at = %s, updated_at = %s WHERE id = %s",
            (ancient, ancient, rule["id"]),
        )
        self.conn.commit()

        rules = repo.list_rules_for_brand(self.conn, self.brand["id"])
        self.assertEqual({r["id"] for r in rules}, {rule["id"]})
        self.assertEqual(rules[0]["status"], "active")

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        self.assertIn("很久以前確認過的偏好規則", text)
        self.assertIn(rule["id"], knowledge_item_ids)


class ContextCompilerPromptCapTest(unittest.TestCase):
    """票 02-prompt-cap-and-overflow-list（決策 0012 第二、三節）：進 prompt 上限與未生效清單。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌F（規則上限測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

    def _make_rules(self, brand_id, hard_count, soft_count):
        """建 hard_count 條 hard ＋ soft_count 條 soft 規則。soft 規則的 confirmed_at 直接
        指定成遞增的固定字串（第 i 條比第 i-1 條晚 1 秒），不靠 now_iso() 的時間精度賭排序斷言。
        基準時間用「現在往前推 1 分鐘」，只要新到舊排序的相對關係不變即可。"""
        base = datetime.now(UTC) - timedelta(minutes=1)
        hard_rules = [
            repo.create_rule(self.conn, brand_id, rule_type="tone", content=f"hard規則{i}",
                             severity="hard", actor="小陳")
            for i in range(1, hard_count + 1)
        ]
        soft_rules = []
        for i in range(1, soft_count + 1):
            rule = repo.create_rule(self.conn, brand_id, rule_type="tone", content=f"soft規則{i:02d}",
                                    severity="soft", actor="小陳")
            confirmed_at = (base + timedelta(seconds=i)).isoformat()
            self.conn.execute("UPDATE rule SET confirmed_at = %s WHERE id = %s",
                              (confirmed_at, rule["id"]))
            self.conn.commit()
            soft_rules.append(rule)
        return hard_rules, soft_rules

    def test_25_rules_top_20_hard_first_enter_prompt(self):
        """25 條 active 規則（3 條 hard＋22 條 soft），只有前 20 條（hard 優先＋soft 依
        confirmed_at 新到舊）進提示詞組裝結果，其餘 5 條不進。"""
        hard_rules, soft_rules = self._make_rules(self.brand["id"], hard_count=3, soft_count=22)

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        # 3 條 hard 全部保留 + 17 條最新 soft（confirmed_at 最新的那 17 條）＝ 20 條進 prompt。
        newest_17 = soft_rules[-17:]
        oldest_5 = soft_rules[:5]
        for r in hard_rules + newest_17:
            self.assertIn(r["content"], text)
            self.assertIn(r["id"], knowledge_item_ids)
        for r in oldest_5:
            self.assertNotIn(r["content"], text)
            self.assertNotIn(r["id"], knowledge_item_ids)

    def test_hard_rules_never_truncated_even_past_cap(self):
        """hard 規則全部保留是硬性不變量：就算 hard 數量本身就超過上限也不截斷 hard。"""
        hard_rules, _soft_rules = self._make_rules(self.brand["id"], hard_count=21, soft_count=2)
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        for r in hard_rules:
            self.assertIn(r["content"], text)

    def test_cap_threshold_reads_per_brand_rule_cards_override(self):
        """上限門檻不寫死常數，讀 rule_cards「rule_prompt_cap」的品牌覆寫值（settings-hub/01
        分品牌機制）：改小上限後同一批規則裡較舊的幾條立刻不再進 prompt，不用重開程式。"""
        _hard, soft_rules = self._make_rules(self.brand["id"], hard_count=0, soft_count=5)
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        for r in soft_rules:
            self.assertIn(r["content"], text)

        rule_cards.set_value(self.conn, self.brand["id"], "rule_prompt_cap", "max_active_rules",
                             3.0, actor="小陳", org_id=db.DEV_ORG_ID)
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        for r in soft_rules[:2]:  # 最舊 2 條超過新上限 3，不再進 prompt
            self.assertNotIn(r["content"], text)
        for r in soft_rules[2:]:
            self.assertIn(r["content"], text)

    def test_product_scope_merges_brand_rules_before_applying_cap(self):
        """品牌整體規則本身在上限內，但加上某產品的專屬規則後合併超過上限時，compile()
        對該產品生成會排除幾條品牌整體規則——不是「只看品牌整體規則」躲過上限。"""
        rule_cards.set_value(self.conn, self.brand["id"], "rule_prompt_cap", "max_active_rules",
                             3.0, actor="小陳", org_id=db.DEV_ORG_ID)
        _hard, brand_soft = self._make_rules(self.brand["id"], hard_count=0, soft_count=2)

        product = repo.create_product(self.conn, self.brand["id"], name="測試產品", actor="小陳")
        base = datetime.now(UTC) - timedelta(minutes=1)
        product_rules = []
        for i in range(1, 3):
            rule = repo.create_rule(self.conn, self.brand["id"], rule_type="tone",
                                    content=f"僅限產品限定規則{i:02d}", severity="soft",
                                    product_id=product["id"], actor="小陳")
            confirmed_at = (base + timedelta(seconds=10 + i)).isoformat()
            self.conn.execute("UPDATE rule SET confirmed_at = %s WHERE id = %s",
                              (confirmed_at, rule["id"]))
            self.conn.commit()
            product_rules.append(rule)

        # compile() 對這個產品生成時，品牌 2 條 + 產品 2 條合併＝4 條 > 上限 3，
        # 產品規則 confirmed_at 較新、排前面，品牌最舊的 1 條被排除。
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"], product["id"])
        for r in product_rules:
            self.assertIn(r["content"], text)
        self.assertNotIn(brand_soft[0]["content"], text)


class FactClaimPromptCapTest(unittest.TestCase):
    """票 F04-I01：事實／宣稱各自讀 rule_prompt_cap 同一張卡截斷，forbidden 不截斷、
    截斷時尾端補一行講出「還有更舊的」。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌G（事實宣稱上限測試）",
                                       client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)

    def _make_brand_facts(self, brand_id, count):
        base = datetime.now(UTC) - timedelta(minutes=1)
        facts = []
        for i in range(1, count + 1):
            fact = repo.create_brand_fact(
                self.conn, brand_id, fact_type="positioning", label=f"事實{i:02d}",
                value=f"品牌事實內容{i:02d}", status="confirmed", confirmed_by="小陳", actor="小陳",
            )
            confirmed_at = (base + timedelta(seconds=i)).isoformat()
            self.conn.execute("UPDATE brand_fact SET confirmed_at = %s WHERE id = %s",
                              (confirmed_at, fact["id"]))
            self.conn.commit()
            facts.append(fact)
        return facts

    def _make_claims(self, brand_id, claim_type, count):
        base = datetime.now(UTC) - timedelta(minutes=1)
        claims = []
        for i in range(1, count + 1):
            claim = repo.create_claim(
                self.conn, brand_id, claim_text=f"{claim_type}宣稱{i:02d}",
                claim_type=claim_type, actor="小陳",
            )
            created_at = (base + timedelta(seconds=i)).isoformat()
            self.conn.execute("UPDATE claim SET created_at = %s WHERE id = %s",
                              (created_at, claim["id"]))
            self.conn.commit()
            claims.append(claim)
        return claims

    def test_45_brand_facts_top_20_newest_enter_prompt_with_overflow_note(self):
        facts = self._make_brand_facts(self.brand["id"], 45)
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        newest_20 = facts[-20:]
        oldest_25 = facts[:25]
        for f in newest_20:
            self.assertIn(f["value"], text)
        for f in oldest_25:
            self.assertNotIn(f["value"], text)
        self.assertIn("（另有 25 筆較舊的品牌事實沒有列出）", text)

    def test_30_approved_claims_capped_but_3_forbidden_all_kept(self):
        approved = self._make_claims(self.brand["id"], "approved", 30)
        forbidden = self._make_claims(self.brand["id"], "forbidden", 3)

        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        newest_20 = approved[-20:]
        oldest_10 = approved[:10]
        for c in newest_20:
            self.assertIn(c["claim_text"], text)
        for c in oldest_10:
            self.assertNotIn(c["claim_text"], text)
        for c in forbidden:
            self.assertIn(c["claim_text"], text)
        self.assertIn("（另有 10 筆較舊的宣稱沒有列出）", text)

    def test_15_facts_under_cap_no_overflow_note_and_all_ids_present(self):
        facts = self._make_brand_facts(self.brand["id"], 15)
        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        for f in facts:
            self.assertIn(f["value"], text)
            self.assertIn(f["id"], knowledge_item_ids)
        self.assertNotIn("沒有列出", text)


class CostCeilingTest(unittest.TestCase):
    """票 M2：呼叫前保守天花板——沒有真實用量校準資料的呼叫端（廣告分支）用這個攔花費上限。"""

    def test_uses_output_rate_times_max_tokens(self):
        # claude-opus-5 輸出費率 US$25／每百萬 token（app/llm/pricing.py）
        self.assertAlmostEqual(pricing.cost_ceiling("claude-opus-5", 24_000), 0.6)

    def test_unknown_model_returns_zero_not_a_crash(self):
        self.assertEqual(pricing.cost_ceiling("不存在的模型", 10_000), 0.0)

    def test_same_unit_as_calculate_cost(self):
        """天花板估計跟呼叫後的真實成本同一幣別（美元）、同一費率表，才能直接相加比較。"""
        real = pricing.calculate_cost("claude-haiku-4-5", 0, 5_000)
        ceiling = pricing.cost_ceiling("claude-haiku-4-5", 5_000)
        self.assertAlmostEqual(real, ceiling)


ORG_A_04_1A = "org_04_1a_test_a"
ORG_B_04_1A = "org_04_1a_test_b"


class AiSpendCapGateTest(unittest.TestCase):
    """票 04-1a（D4-2／D4-3）：組織每月 AI 花費上限是硬性關卡，`run_task()` 是全站
    唯一的把關處——命中上限時，命中前不能有任何一筆 llm_task 紀錄、也不能真的打到
    provider（這是操作者的錢，不是警告）。

    刻意不用 db.DEV_ORG_ID：這個檔案裡其他測試類別也拿 DEV_ORG_ID 跑真的 run_task()、
    寫下真的 llm_task 成功列，跟這裡要精算的「這個月花了多少」算同一個組織會互相汙染
    （撞過：算出來的花費多了其他測試種下去的錢）。改用兩個本票專屬、跟既有測試完全不共用
    的組織 id，比照 test_settings_org_scope.py 的 ORG_A／ORG_B 寫法。"""

    def setUp(self):
        self.conn = db.current()
        for org_id in (ORG_A_04_1A, ORG_B_04_1A):
            self.conn.execute(
                "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
                " ON CONFLICT (id) DO NOTHING",
                (org_id, org_id),
            )
        self.conn.commit()
        self.brand = repo.create_brand(
            self.conn, name="品牌A（花費上限測試）", client_name=None, actor="小陳",
            org_id=ORG_A_04_1A)
        self.brand_b = repo.create_brand(
            self.conn, name="品牌B（另一組織，花費上限測試）", client_name=None, actor="小李",
            org_id=ORG_B_04_1A)

    def tearDown(self):
        self.conn.execute(
            "DELETE FROM llm_task WHERE org_id IN (%s, %s)", (ORG_A_04_1A, ORG_B_04_1A))
        self.conn.execute(
            "DELETE FROM app_setting WHERE org_id IN (%s, %s)", (ORG_A_04_1A, ORG_B_04_1A))
        # repo.create_brand() 順手寫了一筆 audit_log（org_id 有 FK 指回 organisation），
        # 刪 organisation 前要先清掉，否則違反外鍵約束（實測撞過）。
        self.conn.execute(
            "DELETE FROM audit_log WHERE org_id IN (%s, %s)", (ORG_A_04_1A, ORG_B_04_1A))
        self.conn.execute(
            "DELETE FROM brand WHERE org_id IN (%s, %s)", (ORG_A_04_1A, ORG_B_04_1A))
        self.conn.execute(
            "DELETE FROM organisation WHERE id IN (%s, %s)", (ORG_A_04_1A, ORG_B_04_1A))
        self.conn.commit()

    def _context(self, brand: dict) -> gateway.TaskContext:
        return gateway.TaskContext(
            context_scope={"brand_id": brand["id"]}, knowledge_item_ids=[],
            brand_version=brand["knowledge_version"], product_version=None)

    def _seed_spend(self, org_id: str, brand_id: str, cost: float, started_at: str) -> None:
        """比照 app/tests/test_dashboard_cockpit.py `_spend()` 同一套直接種 llm_task 列
        （succeeded、任意 task_type），不經 run_task()——這裡要驗的是「已經花掉的錢」，
        不是某一次呼叫本身。"""
        self.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, cost, started_at, finished_at)"
            " VALUES (%s, %s, %s, 't', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'succeeded', 1, %s, %s, %s)",
            (db.new_id("llm"), org_id, brand_id, cost, started_at, started_at),
        )
        self.conn.commit()

    def _run(self, brand: dict, provider) -> dict:
        return gateway.run_task(
            self.conn, provider, brand_id=brand["id"], task_type="analyzeBrandContext",
            prompt_template_id="tpl_cap_test", prompt_template_version="v1", system=None,
            messages=[{"role": "user", "content": "hi"}], context=self._context(brand),
        )

    # -- 驗收 4：超過上限就擋，擋在打 provider 跟寫 running 列之前 -----------------------

    def test_over_cap_refuses_before_any_charge(self):
        coresettings.set_setting(
            self.conn, coresettings.AI_MONTHLY_COST_LIMIT_SETTING, "10", org_id=ORG_A_04_1A)
        now = db.now_utc()
        self._seed_spend(ORG_A_04_1A, self.brand["id"], 10.0, now.strftime("%Y-%m-02T00:00:00"))
        fake = FakeProvider()

        with self.assertRaises(SpendCapExceededError) as ctx:
            self._run(self.brand, fake)

        self.assertIn("US$ 10.00／US$ 10.00", str(ctx.exception))
        self.assertEqual(fake.calls, [], "命中上限不該真的打到 provider")
        rows = self.conn.execute(
            "SELECT count(*) AS n FROM llm_task WHERE brand_id = %s", (self.brand["id"],)
        ).fetchone()
        self.assertEqual(rows["n"], 1, "只該有 setUp 種下去那一列，不該多一筆 running 列")

    # -- 驗收 5：跨月不算，只看當月 1 號以後 --------------------------------------------

    def test_month_rollover_only_counts_this_months_spend(self):
        coresettings.set_setting(
            self.conn, coresettings.AI_MONTHLY_COST_LIMIT_SETTING, "10", org_id=ORG_A_04_1A)
        now = db.now_utc()
        # 顯式算上個月的邊界（跨年也對）：這個月 1 號往前一天，一定是上個月的某一天；
        # 固定塞成 15 號──每個月都有 15 號，不必擔心 2 月 30 號這種不存在的日期。
        last_month_boundary = now.replace(day=1) - timedelta(days=1)
        self._seed_spend(
            ORG_A_04_1A, self.brand["id"], 999.0,
            last_month_boundary.strftime("%Y-%m-15T00:00:00"))
        self._seed_spend(
            ORG_A_04_1A, self.brand["id"], 3.0, now.strftime("%Y-%m-02T00:00:00"))
        fake = FakeProvider()

        row = self._run(self.brand, fake)

        self.assertEqual(row["status"], "succeeded", "上個月花的 999 不該算進這個月的上限")
        self.assertEqual(len(fake.calls), 1)

    # -- 驗收 6：各組織互不影響 ----------------------------------------------------------

    def test_org_over_cap_does_not_block_another_org(self):
        coresettings.set_setting(
            self.conn, coresettings.AI_MONTHLY_COST_LIMIT_SETTING, "10", org_id=ORG_A_04_1A)
        now = db.now_utc()
        self._seed_spend(ORG_A_04_1A, self.brand["id"], 999.0, now.strftime("%Y-%m-02T00:00:00"))
        fake = FakeProvider()

        with self.assertRaises(SpendCapExceededError):
            self._run(self.brand, fake)

        row = self._run(self.brand_b, fake)  # 另一個組織，沒種過任何花費，用預設上限
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(len(fake.calls), 1)

    # -- 驗收 7：'own' 層不受上限阻擋（上限只是參考數字） --------------------------------

    def test_own_tier_is_never_gated_even_when_over_cap(self):
        coresettings.set_setting(
            self.conn, coresettings.AI_KEY_SOURCE_SETTING, "own", org_id=ORG_A_04_1A)
        coresettings.set_setting(
            self.conn, coresettings.AI_MONTHLY_COST_LIMIT_SETTING, "1", org_id=ORG_A_04_1A)
        now = db.now_utc()
        self._seed_spend(ORG_A_04_1A, self.brand["id"], 999.0, now.strftime("%Y-%m-02T00:00:00"))
        fake = FakeProvider()

        row = self._run(self.brand, fake)

        self.assertEqual(row["status"], "succeeded", "'own' 層的上限只是參考數字，不該被擋")
        self.assertEqual(len(fake.calls), 1)
        # 「用組織自己的金鑰，不是操作者的環境變數金鑰」這個主張本身在資源層直接驗證
        # （見 app/tests/test_settings_api.py::test_ai_key_source_own_tier_reports_advisory_cap，
        # 用真的操作者 env 值＋org 存的 DB 值同框，證明 get_api_key() 回的是後者）——
        # 這裡只驗「不擋」，兩層各自證各自的主張，不重複組一份一樣的斷言。


class FailInterruptedTasksTest(unittest.TestCase):
    """票 05-1 frozen decision 2：process 重啟時，上一個 process 死掉留下的 `llm_task`
    running 列要標記失敗，絕不自動重跑——`succeeded` 的列原封不動。守的是資料正確性：
    一列真的中斷的工作，重啟後不能還顯示「還在跑」（畫面永遠出不了那個狀態，就是這張票
    要修的 bug）。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(
            self.conn, name="品牌（interrupted 測試）", client_name=None, actor="小陳",
            org_id=db.DEV_ORG_ID,
        )

    def _insert(self, status: str, *, worker=True) -> str:
        row_id = db.new_id("llm")
        self.conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, 'schedule_plan', %s, '[]', '', '[]', 1, 'p', 'v1',"
            " 'seed', 'seed', %s, 1, %s)",
            (row_id, db.DEV_ORG_ID, self.brand["id"],
             db.jsonb({"runtime_owner": "worker"} if worker else {}), status, db.now_utc()),
        )
        self.conn.commit()
        return row_id

    def test_running_becomes_failed_succeeded_is_left_alone(self):
        running_id = self._insert("running")
        succeeded_id = self._insert("succeeded")

        count = gateway.fail_interrupted_tasks(self.conn)
        self.assertGreaterEqual(count, 1)

        running_row = gateway.get_task(self.conn, running_id)
        self.assertEqual(running_row["status"], "failed")
        self.assertEqual(running_row["error"], gateway.INTERRUPTED_TASK_ERROR)
        self.assertIsNotNone(running_row["finished_at"])

        succeeded_row = gateway.get_task(self.conn, succeeded_id)
        self.assertEqual(succeeded_row["status"], "succeeded")
        self.assertIsNone(succeeded_row["error"])

    def test_web_and_legacy_tasks_are_not_assumed_dead(self):
        legacy = self._insert("running", worker=False)
        gateway.fail_interrupted_tasks(self.conn)
        self.assertEqual(gateway.get_task(self.conn, legacy)["status"], "running")

    def test_worker_context_records_owner_without_mutating_context_or_prompt(self):
        context = gateway.TaskContext({"brand_id": self.brand["id"]}, [], 1)
        fake = FakeProvider()
        def run():
            return gateway.run_task(
                self.conn, fake, brand_id=self.brand["id"], task_type="schedule_plan",
                prompt_template_id="p", prompt_template_version="v1", system="system",
                messages=[{"role": "user", "content": "hello"}], context=context,
            )
        with gateway.worker_execution():
            worker = run()
        web = run()
        self.assertEqual(worker["context_scope_json"]["runtime_owner"], "worker")
        self.assertNotIn("runtime_owner", web["context_scope_json"])
        self.assertNotIn("runtime_owner", context.context_scope)
        found = gateway.find_tasks_for_scope(
            self.conn, org_id=db.DEV_ORG_ID, brand_id=self.brand["id"], task_type="schedule_plan",
            context_scope={"runtime_owner": "worker"},
        )
        self.assertEqual([row["id"] for row in found], [worker["id"]])
        self.assertEqual(gateway.find_tasks_for_scope(
            self.conn, org_id="other", brand_id=self.brand["id"], task_type="schedule_plan",
            context_scope={"runtime_owner": "worker"},
        ), [])

    def test_cleanup_during_live_web_provider_does_not_fail_it(self):
        fake = FakeProvider()
        original = fake.complete
        def complete(**kwargs):
            gateway.fail_interrupted_tasks(self.conn)
            row = self.conn.execute(
                "SELECT status FROM llm_task WHERE brand_id=%s ORDER BY started_at DESC LIMIT 1",
                (self.brand["id"],),
            ).fetchone()
            self.assertEqual(row["status"], "running")
            return original(**kwargs)
        with mock.patch.object(fake, "complete", side_effect=complete):
            task = gateway.run_task(
                self.conn, fake, brand_id=self.brand["id"], task_type="schedule_plan",
                prompt_template_id="p", prompt_template_version="v1", system="system",
                messages=[{"role": "user", "content": "hello"}],
                context=gateway.TaskContext({}, [], 1),
            )
        self.assertEqual(task["status"], "succeeded")


class ScriptedProviderTest(unittest.TestCase):
    """`BRAND_OS_LLM_PROVIDER=scripted`（F06-I05，e2e 後端專用）：select_provider() 換上
    ScriptedProvider，不理會呼叫端傳進來的 provider；沒有腳本的 task_type 大聲丟 LookupError，
    不留孤兒 `running` 列。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(
            self.conn, name="品牌B（Scripted測試）", client_name=None, actor="小陳",
            org_id=db.DEV_ORG_ID,
        )
        config.settings.cache_clear()
        self._patcher = mock.patch.dict(os.environ, {"BRAND_OS_LLM_PROVIDER": "scripted"})
        self._patcher.start()
        config.settings.cache_clear()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(config.settings.cache_clear)

    def _context(self):
        return gateway.TaskContext(
            context_scope={"brand_id": self.brand["id"]},
            knowledge_item_ids=[], brand_version=self.brand["knowledge_version"],
            product_version=None,
        )

    def _rows_for_brand(self):
        return [
            dict(r) for r in self.conn.execute(
                "SELECT * FROM llm_task WHERE brand_id = %s ORDER BY attempt_no", (self.brand["id"],)
            ).fetchall()
        ]

    def test_scripted_reply_used_fake_provider_never_called(self):
        fake = FakeProvider()
        row = gateway.run_task(
            self.conn, fake, brand_id=self.brand["id"], task_type="ads_brief_parse",
            prompt_template_id="tpl", prompt_template_version="v1",
            system="sys", messages=[{"role": "user", "content": "hi"}],
            context=self._context(),
        )
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["provider"], "scripted")
        self.assertEqual(
            gateway.parse_json_reply(row["rendered_output"]),
            providers.SCRIPTED_REPLIES["ads_brief_parse"],
        )
        self.assertEqual(fake.calls, [])

    def test_unknown_task_type_raises_lookup_error_no_orphan_row(self):
        fake = FakeProvider()
        with self.assertRaises(LookupError) as cm:
            gateway.run_task(
                self.conn, fake, brand_id=self.brand["id"], task_type="not_scripted",
                prompt_template_id="tpl", prompt_template_version="v1",
                system="sys", messages=[{"role": "user", "content": "hi"}],
                context=self._context(),
            )
        self.assertIn("not_scripted", str(cm.exception))
        self.assertEqual(self._rows_for_brand(), [])

    def _strategy_reply(self, content):
        row = gateway.run_task(
            self.conn, FakeProvider(), brand_id=self.brand["id"], task_type="ads_strategy",
            prompt_template_id="tpl", prompt_template_version="v1",
            system="sys", messages=[{"role": "user", "content": content}],
            context=self._context(),
        )
        self.assertEqual(row["status"], "succeeded")
        return gateway.parse_json_reply(row["rendered_output"])

    def test_strategy_reply_allocates_only_the_offered_roles(self):
        # Contract P (F33): `【可用角色】` + one line of keys; content may also be text blocks.
        blocks = [{"type": "text", "text": "前言\n\n【可用角色】\nnew、explore\n\n【其他】"}]
        reply = self._strategy_reply(blocks)
        self.assertEqual(
            [(row["role"], row["pct"]) for row in reply["allocation"]],
            [("new", 60), ("explore", 40)],
        )
        self.assertEqual(reply["why"], providers.SCRIPTED_REPLIES["ads_strategy"]["why"])

    def test_strategy_reply_without_offered_roles_keeps_the_fixed_three(self):
        reply = self._strategy_reply("提示裡沒有可用角色段落")
        self.assertEqual(reply, providers.SCRIPTED_REPLIES["ads_strategy"])

    def test_delivery_plan_reply_uses_the_first_listed_offer(self):
        # F44-I02: `- offer=<key>｜<sentence>` lines under 【這期可用的優惠】; the first group's ad
        # takes the first key, the other groups keep the template's.
        blocks = [{"type": "text", "text": (
            "部門提示\n\n## 這次投放已採用的角色分配\n\n- new（新客）：60%\n- explore（探索）：40%"
            "\n\n【這期可用的優惠】\n- offer=bundle｜三盒組優惠價 NT$999（原價 NT$1,197）"
            "\n\n【座標詞彙】\n- offer｜bundle｜組合優惠"
        )}]
        row = gateway.run_task(
            self.conn, FakeProvider(), brand_id=self.brand["id"], task_type="ads_delivery_plan",
            prompt_template_id="tpl", prompt_template_version="v1",
            system=None, messages=[{"role": "user", "content": blocks}],
            context=self._context(),
        )
        self.assertEqual(row["status"], "succeeded")
        reply = gateway.parse_json_reply(row["rendered_output"])
        self.assertEqual(
            [(g["role"], g["ads"][0]["coordinates"]["offer"]) for g in reply["groups"]],
            [("new", "bundle"), ("explore", "e2e")],
        )


class ParseJsonReplyShapeTest(unittest.TestCase):
    """守 API 契約：parse_json_reply 絕不回傳模型沒送出的形狀（六個呼叫端共用這一支）。

    兩個斷言都取自真實故障：截斷的 intake_question 回覆（5 個 {、4 個 }）被舊解析器
    退回 [ ] 分支，撿到內層 branches 陣列；合法的單元素頂層陣列被 { } 分支切成第一個元素。
    """

    _TRUNCATED = (
        '{"done": false, "aspect": "產品線", "question": "主力是哪一條產品線？", '
        '"suggested": {"label": "a", "desc": "b"}, '
        '"branches": [{"label": "c", "desc": "d"}, {"label": "e", "desc": "f"}, '
        '{"label": "g", "desc": "h"}]'
    )

    def test_truncated_object_is_none_not_the_inner_array(self):
        self.assertIsNone(gateway.parse_json_reply(self._TRUNCATED))

    def test_single_element_top_level_array_stays_a_list(self):
        self.assertEqual(gateway.parse_json_reply('[{"task_layer": "functional"}]'),
                         [{"task_layer": "functional"}])


if __name__ == "__main__":
    unittest.main()


def test_sonnet_five_current_official_price():
    assert pricing.calculate_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0
