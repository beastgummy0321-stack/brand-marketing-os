# -*- coding: utf-8 -*-
"""app/tests/test_ads_compliance_scan_on_generate.py — 票 S1-01：生成當下即掃描。

`compliance.scan_cycle()` 只掃「已採用」主題底下的元件；這裡驗證的是新的
`compliance.scan_components()`——矩陣頁生成一個主題、側板讀主題內容、工作檯快速生成，
三個進入點都要在使用者看到內容的當下就看到法務命中標記，不必等採用之後才知道。

只標示、不動決策（票面決策 2）：`apply_default_holds()` 不在這裡被呼叫，`adoption_decision`
表不該因為這個模組任何一段程式碼而多出資料列。品牌名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_compliance_scan_on_generate_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import compliance  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import theme_engine  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


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

_AXES_VALUES = {"angle": "benefit", "tone": "warm", "format": "single_image",
                "selling_point": "quality"}

_PLAN_OPTIONS = {
    "options": [
        {
            "is_recommended": True,
            "summary": "測試打法", "audience": _AUDIENCE,
            "angles": [{"title": "切角一", "message": "訊息一", "why": "", "product_id": None}],
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
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")


# --- 1. 純函式：compliance.scan_components() -------------------------------------------

class ScanComponentsTest(unittest.TestCase):
    """不落地測試——不開檔期、不建主題，直接對 dict 清單呼叫，比照票面「how we know it's
    done」1 逐項驗收。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光茶行（掃描票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def test_builtin_statutory_term_is_flagged_as_law(self):
        components = [{"component_type": "body", "content": "喝了能治療失眠"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertEqual(list(hits.keys()), [0])
        self.assertEqual(len(hits[0]), 1)
        hit = hits[0][0]
        self.assertEqual(hit["category"], "law")
        self.assertEqual(hit["severity"], "warn")
        self.assertEqual(hit["term"], "治療")
        self.assertIn("治療", hit["message"])
        self.assertIn("主要文案", hit["message"])

    def test_brand_rule_quoted_term_is_flagged_as_brand(self):
        bi_repo.create_rule(main.conn, self.bid, rule_type="wording",
                            content="文案禁止出現「限時搶購」字樣。",
                            severity="hard", actor=ACTOR)
        components = [{"component_type": "title", "content": "限時搶購最後倒數"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertEqual(len(hits[0]), 1)
        hit = hits[0][0]
        self.assertEqual(hit["category"], "brand")
        self.assertEqual(hit["severity"], "warn")
        self.assertEqual(hit["term"], "限時搶購")

    def test_clean_component_key_is_absent(self):
        components = [{"component_type": "body", "content": "每天早晨的一杯好茶"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertEqual(hits, {})

    def test_image_prompt_statutory_term_is_deliberately_skipped(self):
        """image_prompt 是給生圖工具看的指令，不是顧客會看到的文案，刻意不掃（見
        compliance.py scan_components() 檔頭的 ponytail 說明）。"""
        components = [{"component_type": "image_prompt", "content": "特寫療效奇蹟畫面"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertEqual(hits, {})

    def test_component_with_id_uses_id_as_key_not_index(self):
        components = [{"id": "cthc_test1", "component_type": "body", "content": "喝了能治療失眠"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertEqual(list(hits.keys()), ["cthc_test1"])

    def test_scan_does_not_write_any_adoption_decision(self):
        """票面決策 2：只標示、不動決策——scan_components() 是純讀取，即使命中了法規詞庫
        也不該多寫任何一筆 adoption_decision（那是 apply_default_holds() 的事，不在這支
        函式範圍內，本票也刻意不呼叫它）。"""
        before = main.conn.execute(
            "SELECT COUNT(*) AS n FROM adoption_decision").fetchone()["n"]
        components = [{"component_type": "body", "content": "喝了能治療失眠"}]
        hits = compliance.scan_components(main.conn, self.bid, components)
        self.assertTrue(hits)  # 前提：這次真的有命中，不是空跑
        after = main.conn.execute(
            "SELECT COUNT(*) AS n FROM adoption_decision").fetchone()["n"]
        self.assertEqual(before, after)


class UnbackedClaimComponentTest(unittest.TestCase):
    """票面「how we know it's done」1 第三點：查無佐證的規格宣稱要標，登記了佐證就要清空。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(main.conn, name="虛構手工蜜餞坊（掃描票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="測試蜜餞禮盒",
                                              actor=ACTOR)
        self.pid = self.product["id"]

    def test_unbacked_shelf_life_is_flagged_then_clears_once_backed(self):
        components = [{"component_type": "body", "content": "本產品保存期限3年，安心食用"}]

        hits = compliance.scan_components(main.conn, self.bid, components, product_id=self.pid)
        self.assertEqual(len(hits[0]), 1)
        hit = hits[0][0]
        self.assertEqual(hit["category"], "unbacked_claim")
        self.assertIn("3年", hit["term"])

        bi_repo.create_product_fact(
            main.conn, self.bid, self.pid, actor=ACTOR, fact_type="shelf_life",
            label="保存期限", value="3年", status="confirmed", confirmed_by=ACTOR)

        hits_after = compliance.scan_components(
            main.conn, self.bid, components, product_id=self.pid)
        self.assertEqual(hits_after, {})


# --- 2. 端點：GET .../themes/{t} ---------------------------------------------------------

_BUG_SETTINGS_DECIMAL = pytest.mark.xfail(
    strict=True,
    reason="BUG app/core/settings.py:143 — brand_llm_spent() 回傳 Decimal，"
           "budget_exceeded_message() 拿去跟 float 相加，一律 TypeError",
)


@_BUG_SETTINGS_DECIMAL
class ThemeDetailEndpointScanTest(unittest.TestCase):
    """票面「how we know it's done」2：planted 統計詞的主題，GET 側板端點要回非空
    compliance_hits ＋非空 scan_note。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構草本茶集（掃描票端點）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

        self._orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")
        self.cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchone()["id"]

    def tearDown(self):
        ads_plan.PROVIDER = self._orig_plan

    def test_theme_detail_returns_hits_and_scan_note(self):
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=self.cell_id, format_key="single_image",
            name="掃描端點測試主題", folder_code="C801", actor=ACTOR,
            components=[{"component_type": "title", "content": "喝了能治療失眠",
                        "fingerprint_json": _AXES_VALUES}],
        )
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/{theme['id']}")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scan_note"], compliance.SCAN_LIMITS_NOTE)
        components = body["theme"]["components"]
        self.assertEqual(len(components), 1)
        self.assertTrue(components[0]["compliance_hits"])
        self.assertEqual(components[0]["compliance_hits"][0]["category"], "law")

    def test_clean_theme_detail_still_carries_empty_compliance_hits_and_scan_note(self):
        """契約：compliance_hits 空清單而非缺席欄位，scan_note 即使乾淨也永遠附上（誠實
        揭露：沒被標記不等於法務過關）。"""
        theme = theme_repo.create_theme(
            main.conn, self.bid, campaign_cycle_id=self.cycle_id,
            experiment_cell_id=self.cell_id, format_key="single_image",
            name="乾淨主題", folder_code="C802", actor=ACTOR,
            components=[{"component_type": "title", "content": "每天早晨的一杯好茶",
                        "fingerprint_json": _AXES_VALUES}],
        )
        resp = self.client.get(
            f"/api/ads/brands/{self.bid}/ads/{self.cycle_id}/themes/{theme['id']}")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scan_note"], compliance.SCAN_LIMITS_NOTE)
        self.assertEqual(body["theme"]["components"][0]["compliance_hits"], [])


# --- 3. 端點：POST .../quick-generate -----------------------------------------------------

class QuickGenerateEndpointScanTest(unittest.TestCase):
    """票面「how we know it's done」3：快速生成回應的每則元件都要帶 compliance_hits 鍵。"""

    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, "intake_budget_limit", "1000")
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光茶行（掃描票快速生成）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self._orig_provider = theme_engine.PROVIDER

    def tearDown(self):
        theme_engine.PROVIDER = self._orig_provider
        coresettings.set_setting(main.conn, "intake_budget_limit", "30")

    def _text_item(self, content: str) -> dict:
        return {"content": content, "fingerprint": _AXES_VALUES}

    def test_quick_generate_components_all_carry_compliance_hits_key(self):
        reply = json.dumps({
            "name": "虛構主題：晨光第一杯",
            "image_prompt": [f"暖金色茶席場景，特寫第 {i} 張，療效奇蹟" for i in range(10)],
            "body": [self._text_item("喝了能治療失眠" if i == 0 else f"文案{i}")
                    for i in range(5)],
            "title": [self._text_item(f"標題{i}") for i in range(5)],
            "description": [self._text_item(f"說明{i}") for i in range(5)],
        }, ensure_ascii=False)
        theme_engine.PROVIDER = FakeProvider(response=_fake(reply))

        resp = self.client.post(
            f"/api/creative/brands/{self.bid}/quick-generate",
            json={"scope": "post", "topic": "第一杯 39 元", "product_id": None})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scan_note"], compliance.SCAN_LIMITS_NOTE)

        result = body["result"]
        self.assertTrue(all("compliance_hits" in c for c in result["components"]))

        hit_components = [c for c in result["components"] if c["compliance_hits"]]
        self.assertEqual(len(hit_components), 1)
        self.assertEqual(hit_components[0]["component_type"], "body")
        self.assertEqual(hit_components[0]["compliance_hits"][0]["category"], "law")

        # image_prompt 帶了法規詞（"療效"）但刻意不掃，鍵仍在、值是空清單。
        image_prompts = [c for c in result["components"] if c["component_type"] == "image_prompt"]
        self.assertEqual(len(image_prompts), 10)
        self.assertTrue(all(c["compliance_hits"] == [] for c in image_prompts))


if __name__ == "__main__":
    unittest.main()
