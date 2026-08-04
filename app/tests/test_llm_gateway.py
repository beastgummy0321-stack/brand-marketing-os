# -*- coding: utf-8 -*-
"""app/tests/test_llm_gateway.py — LLM Gateway 骨架、Context Compiler。

見 docs/design/06-llm-gateway.md、docs/design/04-context-scope.md、docs/design/03-data-model.md
§3.1 llm_task。全程只用 FakeProvider，不發出任何真實網路請求。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as repo
from app.core import db
from app.llm import context_compiler, gateway, pricing, providers
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, ProviderTimeoutError, Usage


class LLMGatewayTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = repo.create_brand(self.conn, name="品牌A（Gateway測試）", client_name=None, actor="小陳")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

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
                "SELECT * FROM llm_task WHERE brand_id = ? ORDER BY attempt_no", (self.brand["id"],)
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
        self.assertEqual(json.loads(row["structured_output_json"]), {"summary": "重點摘要", "score": 87})

        usage = json.loads(row["usage_json"])
        self.assertEqual(usage["input_tokens"], 1000)
        self.assertEqual(usage["output_tokens"], 2000)
        self.assertEqual(usage["cache_read_input_tokens"], 100)
        self.assertEqual(usage["cache_creation_input_tokens"], 50)

        # 上下文稽核欄位
        self.assertEqual(json.loads(row["context_scope_json"]), {"brand_id": self.brand["id"]})
        self.assertEqual(json.loads(row["knowledge_item_ids_json"]), ["bft_dummy1", "bft_dummy2"])
        self.assertEqual(row["brand_version"], self.brand["knowledge_version"])
        self.assertIsNone(row["product_version"])

        # 只有一次呼叫，且沒有帶 temperature/top_p/top_k/thinking 之類的參數；effort（票 #27
        # 思考等級解析結果）是唯一新增的欄位——任務型別不在任務預設對照表裡，退回中檔。
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(set(provider.calls[0].keys()),
                         {"model", "system", "messages", "max_tokens", "timeout_s", "effort"})
        self.assertEqual(provider.calls[0]["effort"], "medium")

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


class TaskModelThinkingDefaultsTest(unittest.TestCase):
    """票 #27：任務 →（模型、思考等級）對照表、優先鏈（本次覆寫 > 任務預設 > 全域設定）、
    覆寫只生效一次、非法值退回預設不噴錯。全程 FakeProvider，不發任何真實網路請求。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = repo.create_brand(self.conn, name="品牌E（模型思考測試）", client_name=None, actor="小陳")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

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
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

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


class ContextCompilerLearningLoopTest(unittest.TestCase):
    """GitHub issue #54（決策 0030）：learning_ledger／strategy_hypothesis 讀取通電。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = repo.create_brand(self.conn, name="品牌E（學習迴路測試）", client_name=None, actor="小陳")
        self.product = repo.create_product(self.conn, self.brand["id"], name="產品E-1", actor="小陳")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

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
        self.assertIn("樣本數 42", text)
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
        self.conn.execute("UPDATE learning_ledger SET expired = 1 WHERE id = ?", (entry["id"],))
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
