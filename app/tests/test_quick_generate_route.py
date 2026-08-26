# -*- coding: utf-8 -*-
"""app/tests/test_quick_generate_route.py — 快速生成端點（票 01-quick-generate-endpoint）。

接縫二（路由層，app/ads/routes_quick_generate.py）：不開檔期、不用切角格，四選一類型＋
可選產品＋一句話重點 → 生成結果，純顯示即棄。全程 FakeProvider，不發任何真實網路請求。
只測外部行為（端點回應的欄位形狀、DB 沒有新增資料列），不測 prompt 字串的精確內容
（那是既有生成引擎測試範圍，見 test_theme_engine.py／test_video_theme.py，不重複測）。
品牌與產品名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_quick_generate_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, Usage  # noqa: E402


ACTOR = "測試員"

# BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，budget_exceeded_message()
# 的 spent + cost 一律 TypeError（同一個 BUG，其他群組已標過）。
_BUG_DECIMAL_PLUS_FLOAT = pytest.mark.xfail(
    strict=True,
    reason='BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，'
           "budget_exceeded_message() 的 spent + cost 一律 TypeError",
)
# 同一個 BUG，但這個測試用 subTest 對同一個品牌連呼 4 次（post/image/video/script）：
# 中不中要看呼叫順序（哪一次是「這個品牌第一次成功生成」，此時 brand_llm_spent() 走
# `or 0.0` 分支不中；之後每一次都因為已有花費入帳變成 Decimal 而中）——單獨跑這個檔案
# 或整個目錄一起跑，pytest 收集測試的順序不同，「第一次」落在哪個 scope 也跟著變，
# 不是穩定必中。strict=True 在這裡不適用，用 strict=False 誠實描述。
_BUG_DECIMAL_PLUS_FLOAT_ORDER_DEPENDENT = pytest.mark.xfail(
    strict=False,
    reason='BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，'
           "budget_exceeded_message() 的 spent + cost 一律 TypeError；這個測試連呼 4 次，"
           "只有非「這個品牌第一次成功生成」的呼叫會中，會中在哪一次隨測試收集順序而變",
)
_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "single_image",
                "selling_point": "quality"}


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _text_item(label: str, i: int) -> dict:
    return {"content": f"{label}{i}", "fingerprint": _AXES_VALUES}


def _single_image_reply(*, name: str = "虛構主題：晨光第一杯") -> str:
    return json.dumps({
        "name": name,
        "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張" for i in range(10)],
        "body": [_text_item("文案", i) for i in range(5)],
        "title": [_text_item("標題", i) for i in range(5)],
        "description": [_text_item("說明", i) for i in range(5)],
    }, ensure_ascii=False)


def _video_reply(*, name: str = "虛構主題：送禮不失禮", framework: str = "PAS") -> str:
    segments = [{"label": label, "dialogue": f"{label}台詞", "visual": f"{label}畫面"}
               for label in ("痛點", "加壓", "解方", "行動")]
    return json.dumps({
        "name": name,
        "framework": framework,
        "segments": segments,
        "hook_pool": [f"Hook{i}：候選台詞{i}" for i in range(10)],
        "body": [_text_item("文案", i) for i in range(5)],
        "title": [_text_item("標題", i) for i in range(5)],
        "description": [_text_item("說明", i) for i in range(5)],
    }, ensure_ascii=False)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（快速生成票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _swap(self, reply: str, **kwargs) -> FakeProvider:
        provider = FakeProvider(response=_fake(reply), **kwargs)
        theme_engine.PROVIDER = provider
        return provider

    def _post(self, **body):
        return self.client.post(f"/api/creative/brands/{self.bid}/quick-generate", json=body)

    def _theme_row_count(self) -> int:
        return main.conn.execute(
            "SELECT COUNT(*) AS n FROM creative_theme WHERE brand_id = %s", (self.bid,)
        ).fetchone()["n"]


class ScopeFieldShapeTest(_Base):
    """票 01 驗收：四種 scope 各自回傳正確的欄位子集，title／description 一律不出現。"""

    def test_post_scope_returns_image_prompt_and_body_only(self):
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()["result"]
        types = {c["component_type"] for c in result["components"]}
        self.assertEqual(types, {"image_prompt", "body"})
        counts = {}
        for c in result["components"]:
            counts[c["component_type"]] = counts.get(c["component_type"], 0) + 1
        self.assertEqual(counts, {"image_prompt": 10, "body": 5})

    def test_image_scope_returns_image_prompt_only(self):
        self._swap(_single_image_reply())
        resp = self._post(scope="image", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()["result"]
        types = {c["component_type"] for c in result["components"]}
        self.assertEqual(types, {"image_prompt"})
        self.assertEqual(len(result["components"]), 10)

    @_BUG_DECIMAL_PLUS_FLOAT
    def test_video_scope_returns_hook_pool_script_and_body_only(self):
        self._swap(_video_reply())
        resp = self._post(scope="video", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()["result"]
        types = {c["component_type"] for c in result["components"]}
        self.assertEqual(types, {"hook_pool", "script", "body"})
        counts = {}
        for c in result["components"]:
            counts[c["component_type"]] = counts.get(c["component_type"], 0) + 1
        # 完整影片＝3 支腳本共用同一批 10 個 Hook；body 只來自第一支腳本那次呼叫（5 則，
        # 不是 3 次呼叫各 5 則疊出來的 15 則）。
        self.assertEqual(counts, {"hook_pool": 10, "script": 3, "body": 5})

    @_BUG_DECIMAL_PLUS_FLOAT
    def test_script_scope_returns_hook_pool_and_script_only(self):
        self._swap(_video_reply())
        resp = self._post(scope="script", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()["result"]
        types = {c["component_type"] for c in result["components"]}
        self.assertEqual(types, {"hook_pool", "script"})
        counts = {}
        for c in result["components"]:
            counts[c["component_type"]] = counts.get(c["component_type"], 0) + 1
        self.assertEqual(counts, {"hook_pool": 10, "script": 3})

    @_BUG_DECIMAL_PLUS_FLOAT_ORDER_DEPENDENT
    def test_no_scope_ever_returns_title_or_description(self):
        for scope, reply in (("post", _single_image_reply()), ("image", _single_image_reply()),
                             ("video", _video_reply()), ("script", _video_reply())):
            with self.subTest(scope=scope):
                self._swap(reply)
                resp = self._post(scope=scope, topic="測試重點", product_id=None)
                self.assertEqual(resp.status_code, 200, resp.text)
                types = {c["component_type"] for c in resp.json()["result"]["components"]}
                self.assertNotIn("title", types)
                self.assertNotIn("description", types)


@_BUG_DECIMAL_PLUS_FLOAT
class VideoThreeCallsSharedHookPoolTest(_Base):
    """票修復：完整影片／單則腳本要真的呼叫 3 次生成引擎（一支腳本＝一個主題，既有排程流程
    規則），且第二、三次要重用第一次的 hook_pool，不是各自重生一份。"""

    def test_video_scope_calls_ai_three_times(self):
        provider = self._swap(_video_reply())
        resp = self._post(scope="video", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(provider.calls), 3)

    def test_script_scope_calls_ai_three_times(self):
        provider = self._swap(_video_reply())
        resp = self._post(scope="script", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(len(provider.calls), 3)

    def test_only_first_call_asks_ai_to_generate_a_new_hook_pool(self):
        provider = self._swap(_video_reply())
        resp = self._post(scope="video", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        prompts = [call["messages"][0]["content"] for call in provider.calls]
        # needs_hook_pool=True 那次才會要求「另外請你也生成」Hook 池。
        self.assertIn("另外請你也生成這個切角共用的", prompts[0])
        for later_prompt in prompts[1:]:
            self.assertNotIn("另外請你也生成這個切角共用的", later_prompt)
            self.assertIn("這個切角已經有共用的 Hook 池了", later_prompt)

    def test_second_and_third_call_reuse_first_calls_hook_pool_content(self):
        provider = self._swap(_video_reply())
        resp = self._post(scope="video", topic="送禮不失禮", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        # _video_reply() 的 hook_pool 固定是 Hook0…Hook9；第二、三次呼叫的 prompt 要把
        # 這批 Hook 原樣列進「已經有的 Hook」，不是空的、也不是另一批。
        for later_prompt in (call["messages"][0]["content"] for call in provider.calls[1:]):
            for i in range(10):
                self.assertIn(f"Hook{i}：候選台詞{i}", later_prompt)


class DoesNotPersistTest(_Base):
    """票 01 驗收：不落地——回應成功也不寫入 creative_theme／creative_theme_component。"""

    def test_creative_theme_table_unchanged_after_success(self):
        before = self._theme_row_count()
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self._theme_row_count(), before)


class ProductSelectionTest(_Base):
    def test_product_id_none_defaults_to_brand_only_scope(self):
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_valid_product_id_succeeds(self):
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=self.product_id)
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_unknown_product_id_returns_404(self):
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id="prd_not_real")
        self.assertEqual(resp.status_code, 404)


class ProductListRouteTest(_Base):
    """契約 G12.0 產品 pills 的資料來源：只回這個品牌的產品、只回 id／name 兩欄。"""

    def test_lists_only_this_brands_products(self):
        other = bi_repo.create_brand(main.conn, name="虛構隔壁茶行（快速生成票）",
                                     client_name="測試客戶", actor=ACTOR)
        bi_repo.create_product(main.conn, other["id"], name="虛構隔壁產品", actor=ACTOR)
        resp = self.client.get(f"/api/creative/brands/{self.bid}/products")
        self.assertEqual(resp.status_code, 200, resp.text)
        products = resp.json()["products"]
        self.assertEqual([p["name"] for p in products], ["虛構濾掛組"])
        self.assertEqual(set(products[0]), {"id", "name"})

    def test_unknown_brand_returns_404(self):
        resp = self.client.get("/api/creative/brands/brd_not_real/products")
        self.assertEqual(resp.status_code, 404)


class InputValidationTest(_Base):
    def test_unknown_scope_returns_400(self):
        resp = self._post(scope="nonsense", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 400)

    def test_missing_topic_returns_400(self):
        resp = self._post(scope="post", topic="   ", product_id=None)
        self.assertEqual(resp.status_code, 400)

    def test_unknown_brand_returns_404(self):
        resp = self.client.post(
            "/api/creative/brands/brd_not_real/quick-generate",
            json={"scope": "post", "topic": "測試", "product_id": None})
        self.assertEqual(resp.status_code, 404)


class FailureModeTest(_Base):
    def test_ai_failure_returns_422(self):
        self._swap("", exception=ProviderError("模擬 AI 失敗"))
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("error", resp.json())

    def test_budget_exceeded_returns_422(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "0")
        self._swap(_single_image_reply())
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("error", resp.json())

    def test_unparseable_ai_reply_returns_422(self):
        self._swap("這不是 JSON")
        resp = self._post(scope="post", topic="第一杯 39 元", product_id=None)
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
