"""app/tests/test_llm_web_search.py — ADR 0005：開通 LLM 網路搜尋；票 08：把搜尋結果收成
`search_sources`。

全程假金鑰＋攔截掉的假 SDK client，不發任何真實網路請求、不花任何錢
（agent-safety：API 呼叫的錢是真的且不可逆）。驗六件事：

1. 不傳 tools 時，送給供應商的 request body 裡沒有 tools 這個鍵——既有呼叫端行為零改變。
2. 傳 tools 時，body 裡的形狀逐欄符合官方定義（type／name／max_uses／user_location）。
3. usage.server_tool_use.web_search_requests 有被讀出來，沒開搜尋時是 0。
4. 搜尋次數費有進 llm_task.cost（全站花費上限讀的就是這個欄位）。
5. 票 08：`web_search_tool_result` 區塊成功時 `content` 是清單，逐筆收成
   `{"title", "url"}` 進 `ProviderResponse.search_sources`。
6. 票 08 兩條不可妥協規則第 2 條：`content` 是出錯物件（帶 `error_code`，不是清單）時不拋
   例外、`search_sources` 維持空清單——這支測試先改壞程式碼看它真的紅過一次
   （對物件盲目索引 `[0]` 會拋 `TypeError`），再復原，證明擋住的是這個回歸。

官方定義來源（查證日 2026-08-11）：
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool.md
web_search_tool_result 的成功／出錯兩種形狀對照 .venv 內建的 SDK 型別定義（查證日
2026-08-29）：anthropic/types/web_search_tool_result_block_content.py（
`Union[WebSearchToolResultError, List[WebSearchResultBlock]]`）、
web_search_result_block.py（`.title`／`.url`／`.encrypted_content`／`.page_age`）、
web_search_tool_result_error.py（`.error_code`）。
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import anthropic

from app.brand_intelligence import repository as repo
from app.core import db
from app.llm import gateway, pricing, providers
from app.llm.providers import FakeProvider, ProviderResponse, Usage

FAKE_KEY = "sk-ant-fake-key-for-tests"  # 假金鑰：這把不會、也不該打得出任何真實請求


def _sdk_response(web_search_requests=None):
    """模仿 anthropic SDK 的回應物件（只放本檔用得到的欄位）。

    web_search_requests=None 代表這次沒開工具，SDK 的 usage.server_tool_use 會是 None。
    """
    server_tool_use = (SimpleNamespace(web_search_requests=web_search_requests)
                       if web_search_requests is not None else None)
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="（假回覆）測試用輸出")],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=2000,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0,
                              server_tool_use=server_tool_use),
    )


def _capturing_client(captured, response):
    """回傳一個假的 anthropic.Anthropic 類別：把 messages.create() 的 kwargs 原樣錄下來
    就回假回應，不連線。"""

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def with_options(self, **_kwargs):
            return self

        @property
        def messages(self):
            return self

        def create(self, **kwargs):
            captured.append(kwargs)
            return response

    return _Client


def _complete(*, tools=None, web_search_requests=None):
    """跑一次 AnthropicProvider.complete()，回 (送出的 request body, ProviderResponse)。"""
    captured = []
    client_cls = _capturing_client(captured, _sdk_response(web_search_requests))
    with mock.patch.object(providers.settings, "get_api_key", lambda *a, **k: FAKE_KEY), \
            mock.patch.object(anthropic, "Anthropic", client_cls):
        response = providers.AnthropicProvider().complete(
            model="claude-opus-5", system="你是助手",
            messages=[{"role": "user", "content": "測試"}],
            max_tokens=1000, tools=tools, org_id=db.DEV_ORG_ID,
        )
    return captured[0], response


def _sdk_response_with_content(content):
    """跟 `_sdk_response` 同形狀，但整個 `content` 由呼叫端指定——票 08 用來塞一個
    `web_search_tool_result` 區塊（成功的清單形狀，或出錯的物件形狀）進去。"""
    return SimpleNamespace(
        stop_reason="end_turn",
        content=content,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=2000,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0,
                              server_tool_use=SimpleNamespace(web_search_requests=1)),
    )


def _complete_with_content(content):
    """跟 `_complete` 同一套假 client，但直接指定 `response.content`（票 08 的搜尋結果
    解析測試不需要送出的 request body，只要 ProviderResponse）。"""
    client_cls = _capturing_client([], _sdk_response_with_content(content))
    with mock.patch.object(providers.settings, "get_api_key", lambda *a, **k: FAKE_KEY), \
            mock.patch.object(anthropic, "Anthropic", client_cls):
        return providers.AnthropicProvider().complete(
            model="claude-opus-5", system="你是助手",
            messages=[{"role": "user", "content": "測試"}],
            max_tokens=1000, tools=[providers.WEB_SEARCH_TOOL], org_id=db.DEV_ORG_ID,
        )


class WebSearchToolDefinitionTest(unittest.TestCase):
    """常數本身要逐欄對得上官方定義——這是同一份外部規格的唯一真相來源。"""

    def test_constant_matches_official_definition(self):
        tool = providers.WEB_SEARCH_TOOL
        # 官方三個版本之一；型別字串與 name 不得自創
        self.assertEqual(tool["type"], "web_search_20250305")
        self.assertEqual(tool["name"], "web_search")
        # ADR 0005 指定 max_uses 2–3
        self.assertIn(tool["max_uses"], (2, 3))
        # user_location：type 必須是 approximate，country 是 ISO 3166-1 alpha-2 兩碼
        self.assertEqual(tool["user_location"]["type"], "approximate")
        self.assertEqual(tool["user_location"]["country"], "TW")
        # 不得出現官方沒定義的欄位
        self.assertEqual(set(tool), {"type", "name", "max_uses", "user_location"})
        self.assertEqual(set(tool["user_location"]), {"type", "country"})


class AnthropicProviderToolsTest(unittest.TestCase):
    def test_body_has_no_tools_key_when_tools_not_passed(self):
        """最重要的一條：既有呼叫端（不傳 tools）送出的 body 一個字都不變。"""
        body, _ = _complete()
        self.assertNotIn("tools", body)
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertEqual(body["max_tokens"], 1000)
        self.assertEqual(body["system"], "你是助手")
        self.assertEqual(body["messages"], [{"role": "user", "content": "測試"}])

    def test_body_carries_web_search_tool_when_passed(self):
        body, _ = _complete(tools=[providers.WEB_SEARCH_TOOL])
        self.assertEqual(body["tools"], [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": providers.WEB_SEARCH_TOOL["max_uses"],
            "user_location": {"type": "approximate", "country": "TW"},
        }])

    def test_empty_tools_list_is_treated_as_not_requested(self):
        body, _ = _complete(tools=[])
        self.assertNotIn("tools", body)

    def test_usage_reads_web_search_requests(self):
        _, response = _complete(tools=[providers.WEB_SEARCH_TOOL], web_search_requests=2)
        self.assertEqual(response.usage.web_search_requests, 2)

    def test_usage_web_search_requests_is_zero_without_server_tool_use(self):
        _, response = _complete()
        self.assertEqual(response.usage.web_search_requests, 0)


class WebSearchResultParsingTest(unittest.TestCase):
    """票 08：`web_search_tool_result` 區塊的兩種形狀——成功（清單）／出錯（帶
    error_code 的物件）——都要先判斷型別再處理，不能對 `content` 盲目索引。"""

    def test_successful_results_become_search_sources(self):
        result_block = SimpleNamespace(
            type="web_search_tool_result",
            content=[
                SimpleNamespace(type="web_search_result", title="雙十一活動頁",
                                url="https://example.com/1111",
                                encrypted_content="x", page_age=None),
                SimpleNamespace(type="web_search_result", title="品牌週年慶",
                                url="https://example.com/anniversary",
                                encrypted_content="y", page_age="3 天前"),
            ],
        )
        text_block = SimpleNamespace(type="text", text="（假回覆）")
        response = _complete_with_content([result_block, text_block])
        self.assertEqual(response.search_sources, [
            {"title": "雙十一活動頁", "url": "https://example.com/1111"},
            {"title": "品牌週年慶", "url": "https://example.com/anniversary"},
        ])

    def test_error_shaped_result_does_not_raise_and_keeps_sources_empty(self):
        """票 08 兩條不可妥協規則第 2 條的紅一次證明：`content` 是物件，不是清單。
        改成對它做 `content[0]` 這種盲目索引會拋 `TypeError`——本測試就是擋住這個回歸的
        那一支（實作時已手動改壞、看它炸掉、再復原，見票 08 交付報告）。"""
        error_block = SimpleNamespace(
            type="web_search_tool_result",
            content=SimpleNamespace(type="web_search_tool_result_error", error_code="unavailable"),
        )
        text_block = SimpleNamespace(type="text", text="（假回覆，搜尋失敗但照樣出方案）")
        response = _complete_with_content([error_block, text_block])
        self.assertEqual(response.search_sources, [])
        self.assertEqual(response.output_text, "（假回覆，搜尋失敗但照樣出方案）")

    def test_no_result_block_at_all_leaves_sources_empty(self):
        """模型這次沒有真的呼叫搜尋工具（或工具沒開）：完全沒有 web_search_tool_result
        區塊，一樣不是失敗，search_sources 只是空清單。"""
        response = _complete_with_content([SimpleNamespace(type="text", text="（假回覆）")])
        self.assertEqual(response.search_sources, [])


class _LegacyProvider:
    """舊版 Provider 實作：只認既有參數，不認得 tools／effort。gateway 不得因為新參數而
    把它打壞（測試檔裡就有好幾個這種手寫假 Provider）。"""

    name = "legacy"

    def __init__(self):
        self.calls = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0):
        self.calls.append({"model": model, "max_tokens": max_tokens})
        return ProviderResponse(output_text="舊版回覆", structured=None,
                                usage=Usage(input_tokens=10, output_tokens=10),
                                stop_reason="end_turn")


class GatewayWebSearchCostTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = repo.create_brand(self.conn, name="虛構晨星燕麥",
                                       client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)

    def _run(self, provider, tools=None):
        return gateway.run_task(
            self.conn, provider,
            brand_id=self.brand["id"], task_type="schedule_plan",
            prompt_template_id="tpl_test", prompt_template_version="v1",
            system="系統提示", messages=[{"role": "user", "content": "測試"}],
            context=gateway.TaskContext(
                context_scope={"brand_id": self.brand["id"]}, knowledge_item_ids=[],
                brand_version=self.brand["knowledge_version"]),
            options=gateway.TaskOptions(model="claude-opus-5", tools=tools),
        )

    def _provider(self, web_search_requests=0):
        return FakeProvider(response=ProviderResponse(
            output_text="回覆", structured=None,
            usage=Usage(input_tokens=1_000_000, output_tokens=0,
                        web_search_requests=web_search_requests),
            stop_reason="end_turn"))

    def test_tools_reach_the_provider_only_when_requested(self):
        provider = self._provider()
        self._run(provider)
        self.assertIsNone(provider.calls[0]["tools"])

        provider = self._provider()
        self._run(provider, tools=[providers.WEB_SEARCH_TOOL])
        self.assertEqual(provider.calls[0]["tools"], [providers.WEB_SEARCH_TOOL])

    def test_cost_includes_web_search_requests(self):
        """搜尋按次另計（US$10／1000 次），要加進 llm_task.cost，花費上限才擋得準。"""
        token_only = float(self._run(self._provider(web_search_requests=0))["cost"])
        with_search = float(self._run(self._provider(web_search_requests=3))["cost"])
        self.assertAlmostEqual(with_search - token_only,
                               3 * pricing.WEB_SEARCH_USD_PER_SEARCH, places=9)
        self.assertAlmostEqual(pricing.WEB_SEARCH_USD_PER_SEARCH, 0.01, places=9)

    def test_usage_json_records_web_search_requests(self):
        row = self._run(self._provider(web_search_requests=2), tools=[providers.WEB_SEARCH_TOOL])
        self.assertEqual(row["usage_json"]["web_search_requests"], 2)

    def test_legacy_provider_without_tools_parameter_still_works(self):
        provider = _LegacyProvider()
        row = self._run(provider, tools=[providers.WEB_SEARCH_TOOL])
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(len(provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
