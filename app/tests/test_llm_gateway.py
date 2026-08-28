"""app/tests/test_llm_gateway.py — LLM Gateway 骨架、Context Compiler。

見 docs/design/06-llm-gateway.md、docs/design/04-context-scope.md、docs/design/03-data-model.md
§3.1 llm_task。全程只用 FakeProvider，不發出任何真實網路請求。
"""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import anthropic

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as repo
from app.core import db, rule_cards
from app.llm import context_compiler, gateway, pricing, providers
from app.llm.providers import (
    FakeProvider,
    ProviderError,
    ProviderResponse,
    ProviderTimeoutError,
    Usage,
)


class LLMGatewayTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌A（Gateway測試）", client_name=None, actor="小陳")

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
        with mock.patch.object(providers.settings, "get_api_key", lambda: "sk-ant-fake-test"), \
                mock.patch.object(anthropic, "Anthropic", FakeClient):
            response = providers.AnthropicProvider().complete(
                model="claude-opus-5", system=None,
                messages=[{"role": "user", "content": "整理"}], max_tokens=1000,
                tools=[tool],
            )

        self.assertEqual(captured[0]["tools"], [tool])
        self.assertEqual(captured[0]["tool_choice"], {"type": "tool", "name": "submit_rows"})
        self.assertEqual(response.structured, structured)
        self.assertEqual(response.output_text, "")


class TaskModelThinkingDefaultsTest(unittest.TestCase):
    """票 #27：任務 →（模型、思考等級）對照表、優先鏈（本次覆寫 > 任務預設 > 全域設定）、
    覆寫只生效一次、非法值退回預設不噴錯。全程 FakeProvider，不發任何真實網路請求。
    """

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌E（模型思考測試）", client_name=None, actor="小陳")

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
        self.assertEqual(providers.resolve_thinking(task_type="campaign_plan"), "high")
        self.assertEqual(providers.resolve_thinking(task_type="creative_batch"), "medium")
        self.assertEqual(providers.resolve_thinking(task_type="intake_scan"), "low")

    def test_resolve_thinking_unknown_task_falls_back_to_medium(self):
        self.assertEqual(providers.resolve_thinking(task_type="不存在的任務"), "medium")
        self.assertEqual(providers.resolve_thinking(), "medium")

    def test_resolve_thinking_invalid_override_falls_back_without_error(self):
        # 表單被動手腳送了非法值，不噴錯，退回任務預設
        self.assertEqual(providers.resolve_thinking("亂打的值", task_type="campaign_plan"), "high")

    def test_gateway_uses_task_default_thinking_when_no_override(self):
        _row, provider = self._run("campaign_plan")
        self.assertEqual(provider.calls[0]["effort"], "high")
        _row, provider = self._run("intake_scan")
        self.assertEqual(provider.calls[0]["effort"], "low")

    def test_request_override_thinking_affects_only_one_call_then_reverts(self):
        with providers.request_overrides(thinking="max"):
            _row, provider = self._run("creative_batch")
        self.assertEqual(provider.calls[0]["effort"], "max")

        # 離開 with 區塊後，下一次呼叫回到任務預設（中）——覆寫值不落地
        _row2, provider2 = self._run("creative_batch")
        self.assertEqual(provider2.calls[0]["effort"], "medium")

    def test_request_override_model_affects_only_one_call_then_reverts(self):
        with providers.request_overrides(model="claude-sonnet-5"):
            row, _provider = self._run("campaign_plan")
        self.assertEqual(row["model"], "claude-sonnet-5")

        # 下一次呼叫回到全域設定（campaign_plan 本身沒有指定模型預設）
        row2, _provider2 = self._run("campaign_plan")
        self.assertEqual(row2["model"], "claude-opus-5")

    def test_request_override_invalid_thinking_ignored_not_raised(self):
        with providers.request_overrides(thinking="不是五檔之一"):
            _row, provider = self._run("creative_batch")
        self.assertEqual(provider.calls[0]["effort"], "medium")

    # 破壞者情境補洞：手改網址塞不存在的 model（例如 model=hacked-model-xyz），要退回
    # 預設不噴錯，不能一路通到 AnthropicProvider 真的打 API（驗證抓到的缺口）。

    def test_resolve_model_invalid_override_falls_back_without_error(self):
        self.assertEqual(
            providers.resolve_model("hacked-model-xyz", task_type="campaign_plan", conn=self.conn),
            "claude-opus-5")

    def test_resolve_model_valid_override_still_used(self):
        self.assertEqual(
            providers.resolve_model("claude-sonnet-5", task_type="campaign_plan", conn=self.conn),
            "claude-sonnet-5")

    def test_request_override_invalid_model_ignored_falls_back_without_error(self):
        with providers.request_overrides(model="hacked-model-xyz"):
            row, _provider = self._run("campaign_plan")
        self.assertEqual(row["model"], "claude-opus-5")

    def test_request_override_valid_model_still_effective(self):
        with providers.request_overrides(model="claude-fable-5"):
            row, _provider = self._run("campaign_plan")
        self.assertEqual(row["model"], "claude-fable-5")


class ContextCompilerTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def test_only_confirmed_facts_included_and_isolated_by_brand(self):
        brand_a = repo.create_brand(self.conn, name="品牌A（Compiler測試）", client_name=None, actor="小陳")
        brand_b = repo.create_brand(self.conn, name="品牌B（Compiler測試）", client_name=None, actor="小陳")

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

        self.assertEqual(brand_version, repo.get_brand(self.conn, brand_a["id"])["knowledge_version"])
        self.assertIsNone(product_version)

    def test_product_scope_includes_brand_level_but_excludes_other_products(self):
        brand = repo.create_brand(self.conn, name="品牌C（Compiler測試）", client_name=None, actor="小陳")
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
        brand = repo.create_brand(self.conn, name="品牌D（Compiler測試）", client_name=None, actor="小陳")
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


class ContextCompilerPromptCapTest(unittest.TestCase):
    """票 02-prompt-cap-and-overflow-list（決策 0012 第二、三節）：進 prompt 上限與未生效清單。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌F（規則上限測試）", client_name=None, actor="小陳")

    def _make_rules(self, brand_id, hard_count, soft_count):
        """建 hard_count 條 hard ＋ soft_count 條 soft 規則。soft 規則的 confirmed_at 直接
        指定成遞增的固定字串（第 i 條比第 i-1 條晚 1 秒），不靠 now_iso() 的時間精度賭排序斷言。

        基準時間用「現在往前推 1 分鐘」而不是固定日曆日期：票 01-rule-expiry-reconfirm
        （ADR 0012 第一節）之後，`list_rules_for_brand`／`list_rules_for_product` 讀取前
        會先掃一次逾期未確認的規則，固定寫死的舊日期一旦超過門檻期數（系統預設 6 期＝84
        天）就會被判定逾期、退回 pending_reconfirm，不再是這裡要測的「active 但排序較後
        面」——兩個機制刻意保持互不依賴，這裡只要新到舊排序的相對關係不變，基準點是多久
        以前不影響本測試類要驗的行為。"""
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

    def test_25_rules_top_20_hard_first_enter_prompt_rest_overflow(self):
        """驗收條件：25 條 active 規則（3 條 hard＋22 條 soft），只有前 20 條（hard 優先＋
        soft 依 confirmed_at 新到舊）進提示詞組裝結果，另外 5 條出現在未生效清單。"""
        hard_rules, soft_rules = self._make_rules(self.brand["id"], hard_count=3, soft_count=22)

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        overflow = context_compiler.list_overflow_rules(self.conn, self.brand["id"])

        # 3 條 hard 全部保留 + 17 條最新 soft（confirmed_at 最新的那 17 條）＝ 20 條進 prompt。
        newest_17 = soft_rules[-17:]
        oldest_5 = soft_rules[:5]
        for r in hard_rules + newest_17:
            self.assertIn(r["content"], text)
            self.assertIn(r["id"], knowledge_item_ids)
        for r in oldest_5:
            self.assertNotIn(r["content"], text)
            self.assertNotIn(r["id"], knowledge_item_ids)

        self.assertEqual(len(overflow), 5)
        self.assertEqual({o["id"] for o in overflow}, {r["id"] for r in oldest_5})

    def test_overflow_rules_are_not_deactivated(self):
        """未生效不等於刪除或下架：overflow 清單裡的規則狀態仍是 active（決策 0012 第三節）。"""
        _hard, soft_rules = self._make_rules(self.brand["id"], hard_count=0, soft_count=21)
        overflow = context_compiler.list_overflow_rules(self.conn, self.brand["id"])
        self.assertEqual(len(overflow), 1)
        self.assertEqual(overflow[0]["id"], soft_rules[0]["id"])
        row = repo.get_rule(self.conn, self.brand["id"], overflow[0]["id"])
        self.assertEqual(row["status"], "active")

    def test_hard_rules_never_truncated_even_past_cap(self):
        """hard 規則全部保留是硬性不變量：就算 hard 數量本身就超過上限也不截斷 hard，
        這時所有 soft 規則全部進未生效清單。"""
        hard_rules, soft_rules = self._make_rules(self.brand["id"], hard_count=21, soft_count=2)
        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        for r in hard_rules:
            self.assertIn(r["content"], text)
        overflow = context_compiler.list_overflow_rules(self.conn, self.brand["id"])
        self.assertEqual({o["id"] for o in overflow}, {r["id"] for r in soft_rules})

    def test_cap_threshold_reads_per_brand_rule_cards_override(self):
        """上限門檻不寫死常數，讀 rule_cards「rule_prompt_cap」的品牌覆寫值（settings-hub/01
        分品牌機制）：改小上限後同一批規則的未生效清單立刻變多，不用重開程式。"""
        _hard, soft_rules = self._make_rules(self.brand["id"], hard_count=0, soft_count=5)
        self.assertEqual(context_compiler.list_overflow_rules(self.conn, self.brand["id"]), [])

        rule_cards.set_value(self.conn, self.brand["id"], "rule_prompt_cap", "max_active_rules",
                             3.0, actor="小陳")
        overflow = context_compiler.list_overflow_rules(self.conn, self.brand["id"])
        self.assertEqual({o["id"] for o in overflow}, {r["id"] for r in soft_rules[:2]})

    def test_product_only_overflow_not_hidden_when_brand_alone_is_within_cap(self):
        """品牌整體規則本身在上限內，但加上某產品的專屬規則後合併超過上限時，compile()
        對該產品生成會排除幾條產品專屬規則——這幾條要出現在未生效清單，不能因為「只看品牌
        整體規則」而回報 0 條（bug 回歸：compile() 跟 list_overflow_rules() 邏輯要一致）。"""
        rule_cards.set_value(self.conn, self.brand["id"], "rule_prompt_cap", "max_active_rules",
                             3.0, actor="小陳")
        _hard, brand_soft = self._make_rules(self.brand["id"], hard_count=0, soft_count=2)

        # 品牌整體 2 條 soft 本身在上限（3）內，未生效清單是空的。
        self.assertEqual(context_compiler.list_overflow_rules(self.conn, self.brand["id"]), [])

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

        overflow = context_compiler.list_overflow_rules(self.conn, self.brand["id"])
        self.assertIn(brand_soft[0]["id"], {o["id"] for o in overflow})


class ContextCompilerLearningLoopTest(unittest.TestCase):
    """GitHub issue #54（決策 0030）：learning_ledger／strategy_hypothesis 讀取通電。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌E（學習迴路測試）", client_name=None, actor="小陳")
        self.product = repo.create_product(self.conn, self.brand["id"], name="產品E-1", actor="小陳")

    def test_zero_learning_records_output_unchanged_regression(self):
        """回歸鐵條：零學習紀錄時，輸出必須與改動前逐字相同（不多出任何段落）。"""
        fact = repo.create_brand_fact(
            self.conn, self.brand["id"], fact_type="positioning", label="定位",
            value="E牌已確認的定位事實", status="confirmed", confirmed_by="小陳", actor="小陳",
        )
        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        self.assertEqual(text, "【事實】品牌事實\n- 定位：E牌已確認的定位事實")
        self.assertEqual(knowledge_item_ids, [fact["id"]])
        self.assertNotIn("已驗證的學習", text)
        self.assertNotIn("尚未驗證的猜想", text)

    def test_learning_ledger_included_with_source_note(self):
        entry = ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="早鳥優惠切角轉換率最高",
            applicability_scope="brand", created_by="小陳", actor="小陳",
            source_cycle_id=None, sample_size="42", confidence="B",
        )
        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        self.assertIn("【已驗證的學習】", text)
        self.assertIn("早鳥優惠切角轉換率最高", text)
        self.assertIn("對照樣本 42", text)  # 票 L2：收斂後文案「樣本數」改「對照樣本」，單列時結果等價
        self.assertIn(entry["id"], knowledge_item_ids)

    def test_hypothesis_proposed_and_testing_included_supported_excluded(self):
        proposed = repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="audience",
            statement="這群受眾在意睡眠品質", created_by="小陳",
        )
        testing = repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="angle",
            statement="用價格切角轉換較好", created_by="小陳",
        )
        repo.update_hypothesis_status(self.conn, self.brand["id"], testing["id"], status="testing", actor="小陳")
        supported = repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="angle",
            statement="已驗證不該出現在猜想段", created_by="小陳",
        )
        repo.update_hypothesis_status(self.conn, self.brand["id"], supported["id"], status="supported", actor="小陳")

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        self.assertIn("【尚未驗證的猜想】", text)
        self.assertIn("這群受眾在意睡眠品質", text)
        self.assertIn("用價格切角轉換較好", text)
        self.assertNotIn("已驗證不該出現在猜想段", text)
        self.assertIn(proposed["id"], knowledge_item_ids)
        self.assertIn(testing["id"], knowledge_item_ids)
        self.assertNotIn(supported["id"], knowledge_item_ids)
        self.assertNotIn("已驗證的學習", text)  # 未驗證段不得混進已驗證段

    def test_expired_learning_excluded(self):
        entry = ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="這條學習已下架",
            applicability_scope="brand", created_by="小陳", actor="小陳",
        )
        self.conn.execute("UPDATE learning_ledger SET expired = true WHERE id = %s", (entry["id"],))
        self.conn.commit()

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        self.assertNotIn("這條學習已下架", text)
        self.assertNotIn(entry["id"], knowledge_item_ids)

    def test_product_scope_includes_brand_wide_but_excludes_other_product(self):
        other_product = repo.create_product(self.conn, self.brand["id"], name="產品E-2", actor="小陳")
        brand_wide = ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="品牌整體都適用的學習",
            applicability_scope="brand", created_by="小陳", actor="小陳",
        )
        this_product = ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="只適用本產品的學習",
            applicability_scope="product", created_by="小陳", actor="小陳",
            product_id=self.product["id"],
        )
        ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="只適用另一個產品的學習不該外洩",
            applicability_scope="product", created_by="小陳", actor="小陳",
            product_id=other_product["id"],
        )
        brand_hyp = repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="audience",
            statement="品牌層級猜想", created_by="小陳",
        )
        repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="audience",
            statement="另一個產品的猜想不該外洩", created_by="小陳", product_id=other_product["id"],
        )

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(
            self.conn, self.brand["id"], self.product["id"]
        )

        self.assertIn("品牌整體都適用的學習", text)
        self.assertIn("只適用本產品的學習", text)
        self.assertIn("品牌層級猜想", text)
        self.assertNotIn("只適用另一個產品的學習不該外洩", text)
        self.assertNotIn("另一個產品的猜想不該外洩", text)
        self.assertIn(brand_wide["id"], knowledge_item_ids)
        self.assertIn(this_product["id"], knowledge_item_ids)
        self.assertIn(brand_hyp["id"], knowledge_item_ids)

    def test_brand_level_compile_excludes_product_specific_learning(self):
        ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="產品專屬學習不該出現在品牌層",
            applicability_scope="product", created_by="小陳", actor="小陳",
            product_id=self.product["id"],
        )
        repo.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="小陳", hypothesis_type="angle",
            statement="產品專屬猜想不該出現在品牌層", created_by="小陳", product_id=self.product["id"],
        )

        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        self.assertNotIn("產品專屬學習不該出現在品牌層", text)
        self.assertNotIn("產品專屬猜想不該出現在品牌層", text)


class ContextCompilerHypothesisPoolBoundTest(unittest.TestCase):
    """票 F2（B0-29／B0-36 重現）：一條從沒被判讀結案的 proposed 假設不得逐字重複出現在
    每一期的 prompt 裡。手法比照 `ContextCompilerPromptCapTest`：上限 + `list_excluded_*()`
    未生效清單，不悄悄丟棄。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="品牌G（假設上限測試）", client_name=None, actor="小陳")
        self.product = repo.create_product(self.conn, self.brand["id"], name="產品G-1", actor="小陳")

    def _seed_pool(self, product_id=None):
        """4 個假設分屬 4 個不同期別（ccy_c0～ccy_c3，依 created_at 遞增出現），
        第一個（ccy_c0）就是視窗上限外那個，其餘 3 個都在視窗內。"""
        base = datetime.now(UTC) - timedelta(minutes=1)
        statements = ["不是咖啡不需停下來", "猜想1", "猜想2", "最新的猜想"]
        hyps = []
        for i, (cid, statement) in enumerate(zip(["ccy_c0", "ccy_c1", "ccy_c2", "ccy_c3"], statements)):
            h = repo.create_strategy_hypothesis(
                self.conn, self.brand["id"], actor="小陳", hypothesis_type="message",
                statement=statement, created_by="小陳", product_id=product_id, source_cycle_id=cid,
            )
            created_at = (base + timedelta(seconds=i * 10)).isoformat()
            self.conn.execute("UPDATE strategy_hypothesis SET created_at = %s WHERE id = %s",
                              (created_at, h["id"]))
            self.conn.commit()
            hyps.append(h)
        return hyps

    def test_stale_hypothesis_dropped_at_brand_scope(self):
        stale, *rest = self._seed_pool(product_id=None)

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        excluded = context_compiler.list_excluded_hypotheses(self.conn, self.brand["id"])

        self.assertNotIn("不是咖啡不需停下來", text)
        self.assertNotIn(stale["id"], knowledge_item_ids)
        for h in rest:
            self.assertIn(h["statement"], text)
        self.assertEqual([e["id"] for e in excluded], [stale["id"]])
        self.assertIn("期", excluded[0]["reason"])

    def test_stale_hypothesis_dropped_at_product_scope_too(self):
        """契約明講：兩個分支都要套上限，不是只改品牌層那一支。"""
        stale, *rest = self._seed_pool(product_id=self.product["id"])

        text, knowledge_item_ids, _bv, _pv = context_compiler.compile(
            self.conn, self.brand["id"], self.product["id"])
        excluded = context_compiler.list_excluded_hypotheses(
            self.conn, self.brand["id"], self.product["id"])

        self.assertNotIn("不是咖啡不需停下來", text)
        self.assertNotIn(stale["id"], knowledge_item_ids)
        for h in rest:
            self.assertIn(h["statement"], text)
        self.assertEqual([e["id"] for e in excluded], [stale["id"]])


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


if __name__ == "__main__":
    unittest.main()
