# -*- coding: utf-8 -*-
"""app/tests/test_char_guard.py — 字數守門與重寫（票 05-char-guard）。

接縫一（引擎門口，app/ads/theme_engine.py `_apply_char_guard`）：假簡報進、假 gateway 回超字
文案 → 驗只重寫超字那幾則、未超字零呼叫、重寫後仍超就標 over_budget 且不截斷。全程假
Provider，不發任何真實網路請求。品牌與產品名一律虛構。

_Base／_SequencedProvider 兩個 setup 類比照 app/tests/test_theme_engine.py（票 04）與
app/tests/test_ads_creative.py `_SequencedProvider` 的既有寫法複製，不共用 import——
本專案測試檔一律自帶獨立 tmp DB，互不依賴彼此的私有類別。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_char_guard_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import brief_assembler  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import db  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm.providers import ProviderError, ProviderResponse, Usage  # noqa: E402


ROOT = Path(_tmpdir) / "creative"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "single_image",
                "selling_point": "quality"}

# body 字數預算 125（app/creative/format_specs.py）。160 字＝穩穩超字，且是獨一無二的字串，
# 拿來斷言「第二次呼叫只帶這一則，沒有其他短文案」。
LONG_BODY = "超字警報" * 40
SHORT_REWRITE = "已經壓過一次的短文案，還是很吸引人的第一杯"  # 遠低於 125 字
STILL_LONG_REWRITE = "壓過一次還是太長" * 20  # 160 字，重寫後仍超


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=250),
                            stop_reason="end_turn")


def _text_item(label: str, i: int) -> dict:
    return {"content": f"{label}{i}", "fingerprint": _AXES_VALUES}


def _reply_one_over_budget_body() -> str:
    """10 圖／5 文案（第 0 則超字）／5 標題／5 說明——除了那一則長文案，其餘全部短。"""
    payload = {
        "name": "虛構主題：字數守門測試",
        "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張" for i in range(10)],
        "body": [{"content": LONG_BODY, "fingerprint": _AXES_VALUES}]
                + [_text_item("文案", i) for i in range(1, 5)],
        "title": [_text_item("標題", i) for i in range(5)],
        "description": [_text_item("說明", i) for i in range(5)],
    }
    return json.dumps(payload, ensure_ascii=False)


def _reply_all_under_budget() -> str:
    payload = {
        "name": "虛構主題：全部沒超字",
        "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張" for i in range(10)],
        "body": [_text_item("文案", i) for i in range(5)],
        "title": [_text_item("標題", i) for i in range(5)],
        "description": [_text_item("說明", i) for i in range(5)],
    }
    return json.dumps(payload, ensure_ascii=False)


class _SequencedProvider:
    """依序回傳不同回覆的假 Provider（照抄 app/tests/test_ads_creative.py 同名類別的寫法）：
    第一次呼叫＝主生成，第二次以後＝字數守門的重寫呼叫，兩次要回不同內容才測得出重寫有沒有生效。
    """

    name = "fake-sequenced"

    def __init__(self, replies: list):
        self._responses = [_fake(text) for text in replies]
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0):
        self.calls.append({"model": model, "system": system, "messages": messages,
                           "max_tokens": max_tokens, "timeout_s": timeout_s})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class _FailRewriteProvider:
    """第一次呼叫（主生成）成功；第二次起（重寫呼叫，含 gateway 內建重試）一律失敗——
    驗證重寫呼叫本身掛掉時，整個生成不擋、原文照留、標超字（票 05 驗收「不擋採用」）。
    """

    name = "fake-fail-rewrite"

    def __init__(self, first_reply: str):
        self._first = _fake(first_reply)
        self.calls: list = []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0):
        self.calls.append({"model": model, "system": system, "messages": messages,
                           "max_tokens": max_tokens, "timeout_s": timeout_s})
        if len(self.calls) == 1:
            return self._first
        raise ProviderError("測試用：模擬重寫呼叫失敗")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（字數守門票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]

    def tearDown(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _ready_cell(self) -> tuple:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )
        cycle_id = cycle["id"]
        cell_id = db.new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " creative_angle, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (cell_id, db.DEV_ORG_ID, cycle_id, self.bid, self.product_id, "價格敏感：第一杯 39 元",
             db.now_iso()),
        )
        main.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, approved_by, approved_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'approved', %s, %s, %s)",
            (db.new_id("cpl"), db.DEV_ORG_ID, cycle_id, self.bid, 1,
             db.jsonb({"summary": "測試打法：主打省錢誘因"}),
             ACTOR, db.now_iso(), db.now_iso()),
        )
        main.conn.commit()
        return cycle_id, cell_id

    def _assemble(self, cycle_id: str, cell_id: str):
        brief, err = brief_assembler.assemble_brief(
            main.conn, self.bid, cycle_id, cell_id, "single_image", theme_count=1, actor=ACTOR)
        self.assertIsNone(err, err)
        return brief


class TriggersOneRewriteCallForOverBudgetOnlyTest(_Base):
    """驗收 1：回傳超字文案 → 觸發一次重寫呼叫，且只帶超字那一則。"""

    def test_one_extra_call_and_prompt_contains_only_the_over_budget_item(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = _SequencedProvider([
            _reply_one_over_budget_body(),
            json.dumps({"rewrites": [SHORT_REWRITE]}, ensure_ascii=False),
        ])
        theme_engine.PROVIDER = provider

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)

        self.assertEqual(len(provider.calls), 2)  # 主生成 1 次＋重寫 1 次，不多不少
        rewrite_prompt = provider.calls[1]["messages"][0]["content"]
        self.assertIn(LONG_BODY[:10], rewrite_prompt)  # 超字那則的原文有送進去
        # 其餘 24 則沒超字的都不該出現在重寫呼叫裡（不然等於逐則重寫，不是「只帶超字元件」）
        for i in range(1, 5):
            self.assertNotIn(f"文案{i}", rewrite_prompt)
        for i in range(5):
            self.assertNotIn(f"標題{i}", rewrite_prompt)
            self.assertNotIn(f"說明{i}", rewrite_prompt)

        body_components = [c for c in generated["components"] if c["component_type"] == "body"]
        rewritten = next(c for c in body_components if c["content"] == SHORT_REWRITE)
        self.assertFalse(rewritten.get("over_budget"))

        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)
        fetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        saved = next(c for c in fetched["components"] if c["content"] == SHORT_REWRITE)
        self.assertEqual(saved["over_budget"], 0)


class NoRewriteCallWhenNothingOverBudgetTest(_Base):
    """驗收 3：全部沒超字 → 零重寫呼叫（不多花錢）。"""

    def test_only_the_main_generation_call_happens(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = _SequencedProvider([_reply_all_under_budget()])
        theme_engine.PROVIDER = provider

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        self.assertEqual(len(provider.calls), 1)
        for c in generated["components"]:
            self.assertFalse(c.get("over_budget"))


class StillOverAfterRewriteTest(_Base):
    """驗收 2：重寫後仍超 → 存超字標記，內容不截斷（原樣存那個仍超長的重寫結果）。"""

    def test_flag_persisted_and_content_not_truncated(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = _SequencedProvider([
            _reply_one_over_budget_body(),
            json.dumps({"rewrites": [STILL_LONG_REWRITE]}, ensure_ascii=False),
        ])
        theme_engine.PROVIDER = provider

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)
        theme = theme_engine.save_generated_theme(main.conn, brief, generated, actor=ACTOR)

        fetched = theme_repo.get_theme(main.conn, self.bid, theme["id"])
        saved = next(c for c in fetched["components"] if c["content"] == STILL_LONG_REWRITE)
        self.assertEqual(saved["over_budget"], 1)
        self.assertEqual(len(saved["content"]), len(STILL_LONG_REWRITE))  # 沒被砍短

    def test_route_json_exposes_over_budget_flag(self):
        cycle_id, cell_id = self._ready_cell()
        provider = _SequencedProvider([
            _reply_one_over_budget_body(),
            json.dumps({"rewrites": [STILL_LONG_REWRITE]}, ensure_ascii=False),
        ])
        theme_engine.PROVIDER = provider

        resp = self.client.post(
            f"/api/ads/brands/{self.bid}/ads/{cycle_id}/cells/{cell_id}"
            f"/formats/single_image/themes")
        self.assertEqual(resp.status_code, 200)
        components = resp.json()["theme"]["components"]
        flagged = [c for c in components if c["content"] == STILL_LONG_REWRITE]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["over_budget"], 1)


class RewriteCallFailsFallbackTest(_Base):
    """重寫呼叫本身失敗（AI 沒回）：不擋整個生成，原文保留、標超字。"""

    def test_generation_still_succeeds_with_original_content_flagged(self):
        cycle_id, cell_id = self._ready_cell()
        brief = self._assemble(cycle_id, cell_id)
        provider = _FailRewriteProvider(_reply_one_over_budget_body())
        theme_engine.PROVIDER = provider

        generated, err = theme_engine.generate_single_image_theme(main.conn, brief, actor=ACTOR)
        self.assertIsNone(err, err)  # 重寫掛掉不等於整個生成失敗

        body_components = [c for c in generated["components"] if c["component_type"] == "body"]
        original = next(c for c in body_components if c["content"] == LONG_BODY)
        self.assertTrue(original.get("over_budget"))


if __name__ == "__main__":
    unittest.main()
