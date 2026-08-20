# -*- coding: utf-8 -*-
"""app/tests/test_ads_creative.py — 廣告分支票 6：素材包、反對制勾選、拒絕記憶與當場改寫。

全程 FakeProvider，不發任何真實網路請求；品牌與產品名一律虛構。
"""

import atexit
import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_creative_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import creative_matrix as cmx  # noqa: E402
from app.ads import fingerprint as fp  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm import methodology  # noqa: E402
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_AUDIENCE = {"cold": {"description": "測試受眾"}, "warm": {"description": ""},
            "hot": {"description": ""}, "exclusions": []}

# 票 4：計畫生成一次出多個方案，測試只挑第一個（AI 推薦、預設選定的那個）。
_PLAN_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "測試打法", "audience": _AUDIENCE,
            "angles": [{"title": "切角一", "message": "訊息一", "why": "", "product_id": None},
                       {"title": "切角二", "message": "訊息二", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
        {
            "is_recommended": False,
            "summary": "備用方案", "audience": _AUDIENCE,
            "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        },
    ]
}


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=500, output_tokens=300),
                            stop_reason="end_turn")


def _wait_progress(client, url, timeout=5.0):
    """票 M3：進度頁改背景執行緒後，?run=1 不再同步等完；短輪詢模擬瀏覽器 meta refresh，
    等到真的轉址（303）或逾時為止（FakeProvider 幾乎瞬間完成，正常情況幾毫秒內就會轉址）。"""
    deadline = time.time() + timeout
    resp = client.get(url, follow_redirects=False)
    while resp.status_code != 303 and time.time() < deadline:
        time.sleep(0.02)
        resp = client.get(url, follow_redirects=False)
    return resp


# 票 7：切法要跨多種（>= HOOK_CUT_TYPE_MIN_DISTINCT），依序輪流指派避免測試資料自己違規。
_CUT_TYPE_KEYS = list(cmx.CUT_TYPES)


def _variants_reply(cell_ids: list) -> str:
    variants = []
    for index, cell_id in enumerate(cell_ids):
        variants.append({"cell_id": cell_id, "variant_type": "image_prompt",
                         "content": f"A warm morning desk scene for {cell_id}",
                         "rationale": "情境感強",
                         "creative_angle_number": 9, "on_camera": False, "cut_type": None,
                         "quote_source": None,
                         "fingerprint": {"angle": "scene", "tone": "warm",
                                         "format": "single_image", "selling_point": "quality"}})
        variants.append({"cell_id": cell_id, "variant_type": "hook",
                         "content": f"每天第一杯，別再將就（{cell_id}）",
                         "rationale": "點出日常",
                         "creative_angle_number": 16, "on_camera": False,
                         "cut_type": _CUT_TYPE_KEYS[index % len(_CUT_TYPE_KEYS)],
                         "quote_source": None,
                         "fingerprint": {"angle": "pain", "tone": "blunt",
                                         "format": "text_focus", "selling_point": "quality"}})
    return json.dumps({"variants": variants}, ensure_ascii=False)


def _copy_reply(cell_ids: list) -> str:
    """票 30：只出 copy 型別的回覆，供缺型別補打測試當補打回覆用。"""
    variants = [
        {"cell_id": cell_id, "variant_type": "copy",
         "content": f"三分鐘沖一杯好咖啡（{cell_id}）", "rationale": "直接講賣點",
         "creative_angle_number": 9, "on_camera": False, "cut_type": "pain_visualized",
         "quote_source": None,
         "fingerprint": {"angle": "benefit", "tone": "warm", "format": "text_focus",
                         "selling_point": "quality"}}
        for cell_id in cell_ids
    ]
    return json.dumps({"variants": variants}, ensure_ascii=False)


class _SequencedProvider:
    """依序回傳不同回覆的假 Provider——票 30 測試「第一次生成」與「補打」要拿到不同內容，
    FakeProvider 每次呼叫都回同一份，不夠用。介面（.complete()／.calls）照 FakeProvider 的樣子，
    供 gateway.run_task 當一般 Provider 用，不發任何真實網路請求。
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


class _BaseCreativeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        bi_repo.create_brand_fact(main.conn, self.bid, actor=ACTOR, fact_type="positioning",
                                  label="定位", value="單一產區濾掛咖啡。",
                                  status="confirmed", confirmed_by=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan_provider = ads_plan.PROVIDER
        self._orig_creative_provider = ads_creative.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        self.cell_ids = [r["id"] for r in main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ? ORDER BY id",
            (self.cycle_id,))]

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan_provider
        ads_creative.PROVIDER = self._orig_creative_provider

    def _generate(self, reply=None):
        ads_creative.PROVIDER = FakeProvider(
            response=_fake(reply if reply is not None else _variants_reply(self.cell_ids)))
        return _wait_progress(
            self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")

    def _variants(self):
        return ads_creative.list_variants(main.conn, self.bid, self.cycle_id)


class FingerprintTableTest(unittest.TestCase):
    def test_four_axes_with_closed_enums(self):
        self.assertEqual(set(fp.AXES), {"angle", "tone", "format", "selling_point"})
        for spec in fp.AXES.values():
            self.assertTrue(spec["values"])

    def test_invalid_axis_values_are_dropped_not_guessed(self):
        cleaned = fp.normalize({"angle": "pain", "tone": "沒這個值", "format": "single_image"})
        self.assertEqual(cleaned, {"angle": "pain", "format": "single_image"})
        self.assertFalse(fp.is_valid(cleaned))

    def test_every_reject_reason_maps_to_an_axis_or_explicit_none(self):
        for code, _ in fp.REJECT_REASONS:
            self.assertIn(code, fp.REASON_TO_AXIS)

    def test_data_error_reason_does_not_become_a_style_rule(self):
        """「產品資訊不對」是資料錯誤，不該被學成長期的風格禁令。"""
        self.assertIsNone(fp.REASON_TO_AXIS["wrong_product"])

    def test_nine_reasons_and_four_do_not_upgrade_to_rules(self):
        """票 1（#52）驗收條件：9 條理由，其中 4 條刻意不對應任何軸。"""
        self.assertEqual(len(fp.REJECT_REASONS), 9)
        no_axis = {code for code, axis in fp.REASON_TO_AXIS.items() if axis is None}
        self.assertEqual(no_axis, {"too_similar", "visual_weird", "overclaim", "wrong_product"})

    def test_only_policy_reasons_are_upgradable_to_permanent_bans(self):
        """票 T1：白名單只有兩條使用者自己的政策能升級成永久禁令；猜消費者反應的三條
        （too_stiff、too_ad_like、hook_weak）雖然有軸，仍不在白名單內，永遠停在觀察中。"""
        self.assertEqual(fp.RULE_UPGRADABLE_REASONS, {"off_brand", "discount_too_deep"})
        for taste_reason in ("too_stiff", "too_ad_like", "hook_weak"):
            self.assertIsNotNone(fp.REASON_TO_AXIS[taste_reason])
            self.assertNotIn(taste_reason, fp.RULE_UPGRADABLE_REASONS)


class RejectReasonMenuTest(_BaseCreativeTest):
    """#52 驗收條件：理由選單要在頁面上實際渲染出全部 9 條，不是只改常數。"""

    def test_page_renders_all_nine_reject_reasons(self):
        self._generate()
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertEqual(page.text.count('name="reason_code"'), 9 * len(self._variants()))
        for _, label in fp.REJECT_REASONS:
            self.assertIn(label, page.text)


class CreativeBudgetCapTest(_BaseCreativeTest):
    """票 M2：素材生成呼叫前先擋花費上限（原本 app/ads/creative.py 完全沒有這道檢查）。

    先把全域上限調高才呼叫 super().setUp()：那裡面會先跑一次計畫生成，不能被前一個測試
    留下的低上限誤擋；測試結束也把設定還原，避免汙染同檔案後面其他測試類別。
    """

    def setUp(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        super().setUp()
        self.addCleanup(coresettings.set_setting, main.conn, "intake_budget_limit", "30")

    def test_over_limit_blocks_before_calling_provider(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "0.0001")
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        ok, err = ads_creative.generate(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertFalse(ok)
        self.assertIn("US$", err)
        self.assertIn("花費上限", err)
        self.assertEqual(provider.calls, [])  # 真的沒送出呼叫，沒花到錢
        self.assertEqual(self._variants(), [])

    def test_under_limit_still_generates_normally(self):
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        resp = self._generate()
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(self._variants())


class GenerationTest(_BaseCreativeTest):
    def test_generates_variants_per_cell_with_fingerprints(self):
        resp = self._generate()
        self.assertEqual(resp.status_code, 303)
        variants = self._variants()
        self.assertEqual(len(variants), 4)
        self.assertTrue(all(v["fingerprint"] for v in variants))
        self.assertTrue(all(v["experiment_cell_id"] in self.cell_ids for v in variants))

    def test_prompt_includes_methodology_content(self):
        """票 11：素材包生成的 prompt 要含對照表指定的方法論內容（Hook／文案＋圖片 Prompt 兩列）。"""
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("【方法論：ad-creative.md】", sent)
        self.assertIn("【方法論：copywriting.md】", sent)
        self.assertIn("【方法論：creative-matrix.md】", sent)
        self.assertIn("【方法論：customer-voice.md】", sent)
        self.assertIn("三種生成模式", sent)  # ad-creative.md 內文一角

    def test_include_methodology_false_skips_methodology_for_blind_test(self):
        """票 11 效果盲測：include_methodology=False 時同一條生產管線要略過方法論區塊，
        用來產生「接線前」對照組，其餘流程（顧客原話、拒絕記憶）不變。"""
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        ok, err = ads_creative.generate(main.conn, self.bid, self.cycle_id, ACTOR,
                                        include_methodology=False)
        self.assertTrue(ok, err)
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertNotIn("【方法論", sent)

    def test_missing_methodology_file_does_not_block_and_is_shown_honestly(self):
        """票 11：方法論檔缺失時，流程照走、頁面誠實標注、audit 有紀錄。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="brand_os_methodology_"))
        for name in ("copywriting.md", "creative-matrix.md", "customer-voice.md"):
            shutil.copy(methodology.METHODOLOGY_DIR / name, tmp_dir / name)  # 故意漏 ad-creative.md

        orig_dir = methodology.METHODOLOGY_DIR
        methodology.METHODOLOGY_DIR = tmp_dir
        try:
            resp = self._generate()
        finally:
            methodology.METHODOLOGY_DIR = orig_dir
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.assertEqual(resp.status_code, 303)  # 流程照走
        variants = self._variants()
        self.assertTrue(variants)
        self.assertEqual(variants[0]["methodology_missing"], ["ad-creative.md"])

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("ad-creative.md", page.text)
        self.assertIn("方法論參考資料缺席", page.text)

        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'methodology_file'"
            " AND entity_id = 'ad-creative.md'"
        )]
        self.assertTrue(any(r["brand_id"] == self.bid for r in rows))
        self.assertEqual(rows[-1]["action"], "missing")

    def test_requires_approved_plan(self):
        """計畫還沒確認就不該有素材——關卡順序不能繞過。"""
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 5000, "objective": "awareness"})
        other = resp.json()["cycle_id"]
        ads_creative.PROVIDER = FakeProvider(response=_fake("{}"))
        ok, err = ads_creative.generate(main.conn, self.bid, other, ACTOR)
        self.assertFalse(ok)
        self.assertIn("計畫還沒確認", err)

    def test_unknown_cell_ids_are_discarded(self):
        reply = json.dumps({"variants": [
            {"cell_id": "exc_NOT_REAL", "variant_type": "hook", "content": "亂掰的",
             "fingerprint": {}},
            {"cell_id": self.cell_ids[0], "variant_type": "hook", "content": "真的",
             "creative_angle_number": 16, "on_camera": False, "cut_type": "pain_visualized",
             "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt", "format": "text_focus",
                             "selling_point": "quality"}},
        ]}, ensure_ascii=False)
        self._generate(reply=reply)
        variants = self._variants()
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["content"], "真的")

    def test_bad_json_stores_nothing(self):
        resp = self._generate(reply="我幫你想了幾個切角……")
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(self._variants(), [])


class ProductScopedComplianceTest(unittest.TestCase):
    """修憲落地 L3（決策 0034 第 5、6 點）：產品層禁用宣稱要進生成 prompt，且要拆成
    「可以講／絕對不能講」兩個標題明確的區塊，英文狀態值不得進 prompt。"""

    FORBIDDEN_TEXT = "根治慢性疲勞"
    APPROVED_TEXT = "單一產區莊園豆"

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡二號",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構晨光濾掛咖啡",
                                              actor=ACTOR)
        self.pid = self.product["id"]
        bi_repo.create_claim(main.conn, self.bid, product_id=self.pid,
                             claim_text=self.FORBIDDEN_TEXT, claim_type="forbidden", actor=ACTOR)
        bi_repo.create_claim(main.conn, self.bid, product_id=self.pid,
                             claim_text=self.APPROVED_TEXT, claim_type="approved", actor=ACTOR)

        self._orig_plan_provider = ads_plan.PROVIDER
        self._orig_creative_provider = ads_creative.PROVIDER

        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.pid], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        plan_options = {
            "options": [
                {
                    "is_recommended": True,
                    "summary": "測試打法", "audience": _AUDIENCE,
                    "angles": [{"title": "切角一", "message": "訊息一", "why": "",
                               "product_id": self.pid}],
                    "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
                },
                {
                    "is_recommended": False,
                    "summary": "備用方案", "audience": _AUDIENCE,
                    "angles": [{"title": "備用切角", "message": "備用訊息", "why": "",
                               "product_id": self.pid}],
                    "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
                },
            ]
        }
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(plan_options, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        self.cell_ids = [r["id"] for r in main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ? ORDER BY id",
            (self.cycle_id,))]

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan_provider
        ads_creative.PROVIDER = self._orig_creative_provider

    def test_product_forbidden_claim_reaches_do_not_say_block(self):
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        resp = _wait_progress(
            self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.assertEqual(resp.status_code, 303)

        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("絕對不能講", sent)
        self.assertIn(self.FORBIDDEN_TEXT, sent)
        # 是「絕對不能講」那個區塊裡才有這句話，不是隨便哪裡出現一句禁用宣稱
        do_not_say_idx = sent.index("【絕對不能講")
        self.assertGreater(sent.index(self.FORBIDDEN_TEXT), do_not_say_idx)
        self.assertIn("可以講", sent)
        self.assertIn(self.APPROVED_TEXT, sent)
        # 英文狀態值不得進 prompt（決策 0034 第 6 點）
        self.assertNotIn("forbidden", sent)
        self.assertNotIn("high_risk", sent)
        self.assertNotIn("approved", sent)


class MultiProductScopedComplianceTest(unittest.TestCase):
    """一個檔期可含多個產品（決策 0022 第 5 點）：每個產品各自的禁用宣稱都要進 prompt，
    不能只顧到第一個產品、也不能互相外洩到對方名下（修憲落地 L3）。"""

    FORBIDDEN_A = "根治慢性疲勞"
    FORBIDDEN_B = "治療失眠"

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡三號",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_a = bi_repo.create_product(main.conn, self.bid, name="虛構晨光濾掛咖啡",
                                                actor=ACTOR)
        self.product_b = bi_repo.create_product(main.conn, self.bid, name="虛構晨光燕麥奶",
                                                actor=ACTOR)
        self.pid_a, self.pid_b = self.product_a["id"], self.product_b["id"]
        bi_repo.create_claim(main.conn, self.bid, product_id=self.pid_a,
                             claim_text=self.FORBIDDEN_A, claim_type="forbidden", actor=ACTOR)
        bi_repo.create_claim(main.conn, self.bid, product_id=self.pid_b,
                             claim_text=self.FORBIDDEN_B, claim_type="forbidden", actor=ACTOR)

        self._orig_plan_provider = ads_plan.PROVIDER
        self._orig_creative_provider = ads_creative.PROVIDER

        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.pid_a, self.pid_b], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        plan_options = {
            "options": [
                {
                    "is_recommended": True,
                    "summary": "測試打法", "audience": _AUDIENCE,
                    "angles": [{"title": "切角A", "message": "訊息A", "why": "",
                               "product_id": self.pid_a},
                              {"title": "切角B", "message": "訊息B", "why": "",
                               "product_id": self.pid_b}],
                    "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
                },
                {
                    "is_recommended": False,
                    "summary": "備用方案", "audience": _AUDIENCE,
                    "angles": [{"title": "備用切角", "message": "備用訊息", "why": "",
                               "product_id": self.pid_a}],
                    "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
                },
            ]
        }
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(plan_options, ensure_ascii=False)))
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/plan/progress?run=1")
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/select",
                         data={}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/plan/approve",
                         follow_redirects=False)
        self.cell_ids = [r["id"] for r in main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ? ORDER BY id",
            (self.cycle_id,))]

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan_provider
        ads_creative.PROVIDER = self._orig_creative_provider

    def test_both_products_forbidden_claims_reach_prompt(self):
        self.assertEqual(len(self.cell_ids), 2)  # 兩個切角各對應一個產品
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        resp = _wait_progress(
            self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.assertEqual(resp.status_code, 303)

        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn(self.FORBIDDEN_A, sent)
        self.assertIn(self.FORBIDDEN_B, sent)
        self.assertNotIn("forbidden", sent)


class ProgressHonestyTest(_BaseCreativeTest):
    """票 29：等待頁誠實化——階段清單反映真實狀態＋伺服器端計時，不引入前端計時器。"""

    def test_progress_page_stage_list_is_honest_before_running(self):
        text = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress").text
        for label in ("整理這期的資料與素材規則", "請 AI 生成素材", "檢查與存檔"):
            self.assertIn(label, text)
        self.assertIn("進行中", text)
        self.assertIn("還沒開始", text)
        self.assertNotIn("完成", text)
        self.assertNotIn("%", text)
        self.assertIn("已等", text)
        self.assertIn("通常範圍", text)

    def test_progress_elapsed_time_does_not_reset_on_reload(self):
        first = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress").text
        first_secs = int(re.search(r"(\d+) 秒／通常範圍", first).group(1))
        time.sleep(1.1)
        second = self.client.get(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress").text
        second_secs = int(re.search(r"(\d+) 秒／通常範圍", second).group(1))
        self.assertGreaterEqual(second_secs, first_secs + 1)

    def test_generate_reports_real_stages_in_order(self):
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        seen = []
        ok, err = ads_creative.generate(main.conn, self.bid, self.cycle_id, ACTOR,
                                        on_stage=seen.append)
        self.assertTrue(ok, err)
        self.assertEqual(seen, ["ask_ai", "save"])


class CreativeMatrixTest(_BaseCreativeTest):
    """票 7：素材生成接創意矩陣＋原話引用。"""

    def test_variants_carry_angle_number_cut_type_and_on_camera(self):
        resp = self._generate()
        self.assertEqual(resp.status_code, 303)
        variants = self._variants()
        for v in variants:
            self.assertEqual(v["creative_angle_number"], 16 if v["variant_type"] == "hook" else 9)
            self.assertFalse(v["on_camera"])  # 票 7 fixture 全部是非出鏡的情境素材
        hooks = [v for v in variants if v["variant_type"] == "hook"]
        self.assertTrue(all(h["cut_type"] in cmx.CUT_TYPES for h in hooks))
        self.assertTrue(all(h["cut_type_label"] for h in hooks))

    def test_prompt_includes_angle_vocabulary_and_on_camera_instruction(self):
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        # 只在人物出鏡才套 DNA、產圖硬規則——已隨 creative-matrix.md 整份塞進 prompt（票 11 接線）。
        # 承重字串：釘在 creative-matrix.md 第 2 節開頭，改那句話就要同步改這裡。
        self.assertIn("只套用在「人物出鏡」欄標示是／可", sent)
        self.assertIn("圖上文字用「」寫死", sent)
        self.assertIn("數字獨立成行", sent)
        self.assertIn("產品外觀以參照圖為準", sent)
        # 本票新增的硬約束：角度編號、出鏡欄位、切法枚舉都要進 prompt 指令本身，不只是背景文件。
        self.assertIn("creative_angle_number", sent)
        self.assertIn("on_camera", sent)
        for key in cmx.CUT_TYPES:
            self.assertIn(key, sent)

    def test_invalid_angle_number_is_discarded(self):
        reply = json.dumps({"variants": [
            {"cell_id": self.cell_ids[0], "variant_type": "copy", "content": "亂編角度",
             "creative_angle_number": 999, "on_camera": False, "cut_type": "pain_visualized",
             "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt", "format": "text_focus",
                             "selling_point": "quality"}},
        ]}, ensure_ascii=False)
        resp = self._generate(reply=reply)
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(self._variants(), [])

    def test_hook_cut_type_diversity_is_enforced_with_deliberate_violation(self):
        """故意違規案例：10 則 Hook 全部同一種切法，驗形要擋下、不入庫。"""
        variants = [
            {"cell_id": self.cell_ids[0], "variant_type": "hook", "content": f"換句話說 {i}",
             "creative_angle_number": 16, "on_camera": False, "cut_type": "pain_visualized",
             "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt", "format": "text_focus",
                             "selling_point": "quality"}}
            for i in range(4)
        ]
        resp = self._generate(reply=json.dumps({"variants": variants}, ensure_ascii=False))
        self.assertIn("kind=warn", resp.headers["location"])
        self.assertEqual(self._variants(), [])

    def test_on_camera_true_shows_dna_badge_on_page(self):
        variants = [
            {"cell_id": cid, "variant_type": "image_prompt", "content": f"人像情境 {cid}",
             "creative_angle_number": 12, "on_camera": True, "cut_type": None,
             "quote_source": None,
             "fingerprint": {"angle": "identity", "tone": "warm", "format": "single_image",
                             "selling_point": "uniqueness"}}
            for cid in self.cell_ids
        ]
        self._generate(reply=json.dumps({"variants": variants}, ensure_ascii=False))
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("人物出鏡（套用真人實拍 DNA）", page.text)
        self.assertIn("創意角度 #12", page.text)

    def test_customer_voice_quotes_are_injected_and_cited(self):
        bi_repo.create_customer_voice(
            main.conn, self.bid, actor=ACTOR, raw_text="每次喝完都覺得肚子暖暖的，不會脹氣。",
            source_channel="蝦皮評論", source_detail="2026-05-02", source_type="manual",
            extraction=[{"task_layer": "functional", "quote": "不會脹氣",
                        "insight": "顧客在意喝完不脹氣", "signal": "unprompted"}],
        )
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("不會脹氣", sent)
        self.assertIn("蝦皮評論", sent)

        variants = [
            {"cell_id": self.cell_ids[0], "variant_type": "copy", "content": "文案引用原話",
             "creative_angle_number": 7, "on_camera": False, "cut_type": "pain_visualized",
             "quote_source": "蝦皮評論，2026-05-02",
             "fingerprint": {"angle": "pain", "tone": "warm", "format": "text_focus",
                             "selling_point": "quality"}},
        ]
        self._generate(reply=json.dumps({"variants": variants}, ensure_ascii=False))
        cited = next(v for v in self._variants() if v["content"] == "文案引用原話")
        self.assertEqual(cited["quote_source"], "蝦皮評論，2026-05-02")
        self.assertTrue(cited["customer_voice_available"])

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("引用顧客原話，出處：蝦皮評論，2026-05-02", page.text)
        self.assertNotIn("無顧客原話支撐", page.text)

    def test_empty_customer_voice_corpus_is_honestly_labeled(self):
        """語料庫空時照樣生成，頁面標注「無顧客原話支撐」（決策 0023 第 18a 點）。"""
        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("沒有任何顧客原話語料", sent)

        variants = self._variants()
        self.assertTrue(variants)
        self.assertFalse(variants[0]["customer_voice_available"])

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("無顧客原話支撐", page.text)


class OppositionSelectionTest(_BaseCreativeTest):
    def test_page_says_default_is_adopt_all(self):
        self._generate()
        resp = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("預設全部採用", resp.text)
        self.assertIn("不調整也可以直接繼續", resp.text)

    def test_zero_clicks_adopts_everything(self):
        """反對制的核心：什麼都不點也能過關，採用的是「他沒有反對的」。"""
        self._generate()
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        rows = main.conn.execute(
            "SELECT decision, COUNT(*) c FROM adoption_decision WHERE campaign_cycle_id = ?"
            " GROUP BY decision", (self.cycle_id,)).fetchall()
        self.assertEqual({r["decision"]: r["c"] for r in rows}, {"adopted": 4})

    def test_rejected_variant_is_not_adopted(self):
        self._generate()
        target = self._variants()[0]
        ads_creative.PROVIDER = FakeProvider(response=_fake(json.dumps(
            {"content": "改寫後的版本", "rationale": "避開太生硬",
             "fingerprint": {"angle": "benefit", "tone": "warm",
                             "format": "text_focus", "selling_point": "quality"}},
            ensure_ascii=False)))
        self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/{target['id']}/reject",
            data={"reason_code": "too_stiff"}, follow_redirects=False)
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                         follow_redirects=False)
        adopted_ids = {r["target_id"] for r in main.conn.execute(
            "SELECT target_id FROM adoption_decision WHERE decision = 'adopted'"
            " AND campaign_cycle_id = ?", (self.cycle_id,))}
        self.assertNotIn(target["id"], adopted_ids)

    def test_approving_nothing_is_blocked_with_plain_message(self):
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                                follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])

    def test_approval_works_without_operator_cookie(self):
        """ADR 0004：關卡二（素材採用）不再要求先設定操作人。"""
        self._generate()
        self.client.cookies.clear()
        resp = self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/approve",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("/settings/operator", resp.headers["location"])
        row = main.conn.execute(
            "SELECT decided_by FROM adoption_decision WHERE campaign_cycle_id = ? LIMIT 1",
            (self.cycle_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["decided_by"], OPERATOR)


class RejectionMemoryTest(_BaseCreativeTest):
    def _reject(self, variant, reason_code, rewrite_ok=True):
        if rewrite_ok:
            ads_creative.PROVIDER = FakeProvider(response=_fake(json.dumps(
                {"content": "改寫後的版本", "rationale": "避開原本的問題",
                 "fingerprint": {"angle": "benefit", "tone": "friendly",
                                 "format": "text_focus", "selling_point": "quality"}},
                ensure_ascii=False)))
        else:
            ads_creative.PROVIDER = FakeProvider(exception=ProviderError("模型暫時無法回應"))
        return self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/{variant['id']}/reject",
            data={"reason_code": reason_code}, follow_redirects=False)

    def test_rejection_stores_structured_reason_and_fingerprint_snapshot(self):
        self._generate()
        target = self._variants()[0]
        self._reject(target, "too_stiff")
        row = main.conn.execute(
            "SELECT * FROM adoption_decision WHERE target_id = ?", (target["id"],)).fetchone()
        self.assertEqual(row["decision"], "rejected")
        self.assertEqual(row["reason_code"], "too_stiff")
        self.assertEqual(json.loads(row["fingerprint_json"]), target["fingerprint"])

    def test_rewrite_puts_a_replacement_back_in_place(self):
        self._generate()
        target = self._variants()[0]
        before = len(self._variants())
        self._reject(target, "too_stiff")
        after = self._variants()
        self.assertEqual(len(after), before + 1)
        replacement = [v for v in after if v["content"] == "改寫後的版本"][0]
        self.assertEqual(replacement["experiment_cell_id"], target["experiment_cell_id"])
        self.assertEqual(replacement["variant_type"], target["variant_type"])

    def test_user_is_told_what_the_system_learned(self):
        self._generate()
        resp = self._reject(self._variants()[0], "too_stiff")
        self.assertIn("%E6%88%91%E5%AD%B8%E5%88%B0%E4%BA%86", resp.headers["location"])

    def test_rewrite_failure_keeps_rejection_and_says_so(self):
        """改寫失敗不能吞掉——拒絕仍要記住，訊息要誠實說沒改成。"""
        self._generate()
        target = self._variants()[0]
        resp = self._reject(target, "too_stiff", rewrite_ok=False)
        self.assertIn("kind=warn", resp.headers["location"])
        row = main.conn.execute(
            "SELECT * FROM adoption_decision WHERE target_id = ?", (target["id"],)).fetchone()
        self.assertEqual(row["decision"], "rejected")

    def test_past_rejections_become_negative_constraints_in_next_prompt(self):
        """拒絕記憶的閉環：這期退掉的，下一批生成時會出現在「不要再出現」清單裡。"""
        self._generate()
        self._reject(self._variants()[0], "too_stiff")

        provider = FakeProvider(response=_fake(_variants_reply(self.cell_ids)))
        ads_creative.PROVIDER = provider
        _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("這次不要再出現", sent)
        self.assertIn("親切溫暖", sent)

    def test_data_error_rejection_does_not_become_a_constraint(self):
        """「產品資訊不對」不該變成風格禁令，否則約束越積越多但射偏。"""
        self._generate()
        self._reject(self._variants()[0], "wrong_product")
        constraints = ads_creative._rejection_constraints(main.conn, self.bid)
        self.assertEqual(constraints, [])

    def test_invalid_reason_is_rejected(self):
        self._generate()
        target = self._variants()[0]
        resp = self.client.post(
            f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/{target['id']}/reject",
            data={"reason_code": "亂填的"}, follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])


class CreativeIsolationTest(_BaseCreativeTest):
    def test_other_brand_sees_no_variants(self):
        self._generate()
        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙", client_name=None,
                                     actor=ACTOR)["id"]
        self.assertEqual(ads_creative.list_variants(main.conn, other, self.cycle_id), [])
        self.assertIsNone(
            ads_creative.get_variant(main.conn, other, self._variants()[0]["id"]))


class MissingTypeBackfillTest(_BaseCreativeTest):
    """票 30：驗形回報缺型別統計 → 自動只補缺的型別打一次 → 補不齊就在素材頁誠實標注。"""

    def test_missing_copy_triggers_one_backfill_and_fills_it(self):
        """第一次回覆缺 copy，補打回覆補上 copy：最終補齊、頁面不標注、只打了兩次 LLM。"""
        provider = _SequencedProvider(
            [_variants_reply(self.cell_ids), _copy_reply(self.cell_ids)])
        ads_creative.PROVIDER = provider
        resp = _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(len(provider.calls), 2)  # 一次原生成、一次補打，不迴圈重試

        variants = self._variants()
        copy_variants = [v for v in variants if v["variant_type"] == "copy"]
        self.assertEqual(len(copy_variants), len(self.cell_ids))
        self.assertTrue(all(v["missing_creative_types"] == [] for v in variants))

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertNotIn("已自動補打一次仍未產出", page.text)

    def test_still_missing_after_backfill_is_labeled_on_page(self):
        """第一次、補打都缺 copy：不再打第三次，頁面誠實標注缺了廣告文案。"""
        provider = _SequencedProvider(
            [_variants_reply(self.cell_ids), _variants_reply(self.cell_ids)])
        ads_creative.PROVIDER = provider
        resp = _wait_progress(self.client, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives/progress?run=1")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(len(provider.calls), 2)  # 補打了一次就不再重試

        variants = self._variants()
        self.assertFalse(any(v["variant_type"] == "copy" for v in variants))
        self.assertTrue(all(v["missing_creative_types"] == ["copy"] for v in variants))

        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertIn("已自動補打一次仍未產出", page.text)
        self.assertIn("廣告文案", page.text)

    def test_no_missing_type_does_not_trigger_backfill(self):
        """三個型別都齊全時不該多打一次補打——驗形沒偵測到缺型別。"""
        full_reply = json.dumps({"variants": json.loads(_variants_reply(self.cell_ids))["variants"]
                                 + json.loads(_copy_reply(self.cell_ids))["variants"]},
                                ensure_ascii=False)
        self._generate(reply=full_reply)
        self.assertEqual(len(ads_creative.PROVIDER.calls), 1)  # 沒缺型別，不觸發補打

        variants = self._variants()
        self.assertTrue(all(v["missing_creative_types"] == [] for v in variants))
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/creatives")
        self.assertNotIn("已自動補打一次仍未產出", page.text)


if __name__ == "__main__":
    unittest.main()
