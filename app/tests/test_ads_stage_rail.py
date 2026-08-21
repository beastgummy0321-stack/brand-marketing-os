# -*- coding: utf-8 -*-
"""app/tests/test_ads_stage_rail.py — D線票4（GitHub issue #46）：五格進度軌接上檔期五個階段頁。

驗收重點：
1. 五個階段頁（檔期／素材／交接包／投放前檢查／成效）頂端都渲染同一條 #43 的
   progress_rail，傳 collapsed=True，狀態對齊 app/ads/stages.derive_stage() 算出來的
   目前階段——這裡分別在「剛開檔期」（第 1 格）與「已經投放」（第 5 格）兩個時間點各檢查
   一次五個頁面，確認不是寫死。
2. 收合模式下，已完成且有連結的格收合成序號但仍可點回顧（progress_rail 本身的既定行為，見
   app/tests/test_components_macros.py 的 test_done_cell_with_url_is_collapsed_but_still_clickable），
   還沒開始（future）的格不可點——對齊「未開始的階段格不可點」。
3. 麵包屑四層止於檔期日期——素材／交接包／投放前檢查／成效四頁原本多帶一個階段名 tail，
   本票拿掉，階段名改放頁面 H1。

品牌與素材內容一律虛構，全程 FakeProvider，不發任何真實網路請求。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_stage_rail_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import creative as ads_creative  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
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
_PLAN_OPTIONS = {"options": [
    {"is_recommended": True, "summary": "測試打法", "audience": _AUDIENCE,
     "angles": [{"title": "早上第一杯", "message": "訊息", "why": "", "product_id": None}],
     "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
    {"is_recommended": False, "summary": "備用方案", "audience": _AUDIENCE,
     "angles": [{"title": "備用切角", "message": "備用訊息", "why": "", "product_id": None}],
     "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []}},
]}

# 五個階段頁：(路徑後綴, 頁面應出現的階段名)。檔期頁的 H1 是檔期日期本身，不套階段名
# （本票的麵包屑修正也只列素材／交接包／投放前檢查／成效四頁，檔期頁不在此列）。
STAGE_PAGES = [
    ("", None),
    ("/creatives", "素材"),
    ("/handoff", "交接包"),
    ("/checklist", "投放前檢查"),
    ("/performance", "成效"),
]


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=400, output_tokens=200),
                            stop_reason="end_turn")


def _rail(html: str) -> str:
    start = html.index('aria-label="檔期進度"')
    tag_start = html.rindex("<nav", 0, start)
    end = html.index("</nav>", start)
    return html[tag_start:end]


def _breadcrumb_tier_count(html: str) -> int:
    """麵包屑層數＝分隔符號數 + 1（app/templates/_components/breadcrumb.html 的既有結構）。"""
    start = html.index('<nav class="breadcrumb"')
    end = html.index("</nav>", start)
    segment = html[start:end]
    return segment.count('<span class="sep">/</span>') + 1


class _BaseStageRailTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

    def _get(self, suffix: str):
        return self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}{suffix}")

    def _advance_to_live(self):
        """走完整個流程：確認計畫 → 產出並採用素材 → 產出交接包 → 具名回報投放，
        讓檔期狀態變成 LIVE（第 5 格：成效）。這只是把檔期推到第 5 格的前置動作，不是
        本檔的斷言對象：企劃／素材生成直接呼叫業務函式（舊頁進度頁與 /api 背景工作跑的
        就是這兩支），採用素材沒有對應的 /api 端點，同樣直接呼叫業務函式，其餘走 /api。"""
        orig_plan = ads_plan.PROVIDER
        ads_plan.PROVIDER = FakeProvider(
            response=_fake(json.dumps(_PLAN_OPTIONS, ensure_ascii=False)))
        try:
            ok, err = ads_plan.generate_options(main.conn, self.bid, self.cycle_id, ACTOR)
        finally:
            ads_plan.PROVIDER = orig_plan
        self.assertTrue(ok, err)
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/select", json={})
        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/plan/approve")

        cell_id = main.conn.execute(
            "SELECT id FROM experiment_cell WHERE campaign_cycle_id = ?",
            (self.cycle_id,)).fetchone()["id"]
        reply = json.dumps({"variants": [
            {"cell_id": cell_id, "variant_type": "hook", "content": "每天第一杯，別再將就",
             "rationale": "", "creative_angle_number": 16, "on_camera": False,
             "cut_type": "pain_visualized", "quote_source": None,
             "fingerprint": {"angle": "pain", "tone": "blunt", "format": "text_focus",
                            "selling_point": "quality"}},
        ]}, ensure_ascii=False)
        orig_creative = ads_creative.PROVIDER
        ads_creative.PROVIDER = FakeProvider(response=_fake(reply))
        try:
            ok, err = ads_creative.generate(main.conn, self.bid, self.cycle_id, ACTOR)
        finally:
            ads_creative.PROVIDER = orig_creative
        self.assertTrue(ok, err)
        self.assertTrue(
            ads_creative.approve_selection(main.conn, self.bid, self.cycle_id, ACTOR))

        self.client.post(f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/build")
        package = ads_handoff.list_packages(main.conn, self.bid, self.cycle_id)[0]
        self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/handoff/{package['id']}/activate",
            json={"meta_campaign_id": "23851234567890123"})


class FreshCycleStage1Test(_BaseStageRailTest):
    """剛開的檔期：第 1 格（計畫）當前，第 2 格（素材）是下一格，其餘收合。"""

    def test_all_five_pages_render_rail_current_stage1(self):
        for suffix, stage_name in STAGE_PAGES:
            with self.subTest(page=suffix or "/(cycle)"):
                resp = self._get(suffix)
                self.assertEqual(resp.status_code, 200)
                html = resp.text
                rail = _rail(html)
                self.assertIn('<span class="rail-current" aria-current="step">計畫</span>', rail)
                self.assertIn('<span class="rail-next">素材</span>', rail)
                for n in (3, 4, 5):
                    self.assertIn(f'<span class="rail-collapsed">{n}</span>', rail)
                self.assertNotIn("<a ", rail)  # 收合模式沒有任何格可以點

    def test_breadcrumb_is_four_tiers_on_every_page(self):
        for suffix, _ in STAGE_PAGES:
            with self.subTest(page=suffix or "/(cycle)"):
                html = self._get(suffix).text
                self.assertEqual(_breadcrumb_tier_count(html), 4)

    def test_stage_name_is_in_h1_for_the_four_sub_pages(self):
        for suffix, stage_name in STAGE_PAGES:
            if stage_name is None:
                continue
            with self.subTest(page=suffix):
                html = self._get(suffix).text
                h1 = html[html.index("<h1>"):html.index("</h1>")]
                self.assertIn(stage_name, h1)


class LiveCycleStage5Test(_BaseStageRailTest):
    """走完流程回報投放後：第 5 格（成效）當前，沒有下一格，其餘收合。"""

    def setUp(self):
        super().setUp()
        self._advance_to_live()

    def test_all_five_pages_render_rail_current_stage5(self):
        # 前四格（計畫／素材／交接包／投放前檢查）都已完成：收合成序號，但可點回顧
        # 對應的階段頁（GitHub issue #46 缺陷 1 修正）。
        done_urls = [
            (1, f"/brands/{self.bid}/ads/{self.cycle_id}"),
            (2, f"/brands/{self.bid}/ads/{self.cycle_id}/creatives"),
            (3, f"/brands/{self.bid}/ads/{self.cycle_id}/handoff"),
            (4, f"/brands/{self.bid}/ads/{self.cycle_id}/checklist"),
        ]
        for suffix, _ in STAGE_PAGES:
            with self.subTest(page=suffix or "/(cycle)"):
                resp = self._get(suffix)
                self.assertEqual(resp.status_code, 200)
                rail = _rail(resp.text)
                self.assertIn('<span class="rail-current" aria-current="step">成效</span>', rail)
                self.assertNotIn("rail-next", rail)  # 最後一格沒有下一格可亮
                for n, url in done_urls:
                    self.assertIn(
                        f'<a class="rail-collapsed rail-done" href="{url}">{n}</a>', rail)

    def test_breadcrumb_still_four_tiers_after_activation(self):
        for suffix, _ in STAGE_PAGES:
            with self.subTest(page=suffix or "/(cycle)"):
                html = self._get(suffix).text
                self.assertEqual(_breadcrumb_tier_count(html), 4)

    def test_urls_are_unchanged(self):
        """本票不准改任何一個階段頁的網址——這裡直接打五個既有路徑，全部要 200。"""
        for suffix, _ in STAGE_PAGES:
            with self.subTest(page=suffix or "/(cycle)"):
                self.assertEqual(self._get(suffix).status_code, 200)


if __name__ == "__main__":
    unittest.main()
