# -*- coding: utf-8 -*-
"""app/tests/test_ads_performance_split.py — D線票5（GitHub issue #47）：成效頁拆層＋資料操作子頁。

驗收重點（舊頁版面斷言隨 Jinja 舊頁一起刪除，這裡只剩不綁畫面的業務行為）：
1. 拆層前後：同一組 fixture 的判讀結論／成色標籤／可信度數值必須完全相同（本票不改判讀邏輯，
   只驗證版面搬動沒有連帶改到這些數字）。
2. 資料不足時仍給結論並標成色：分母為 0 的 KPI 回 None，不硬給 0。
3. 已記錄的蝦皮碼重判讀後會反映進通路對照結果。

品牌與產品名一律虛構，全程 FakeProvider，不發任何真實網路請求。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_perf_split_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import nextcycle  # noqa: E402
from app.ads import reconcile as ads_reconcile  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.orders import channel as orders_channel  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


class _JudgedCycleTest(unittest.TestCase):
    """一個已判讀、有下一期草案、非模擬的真實檔期——五塊在這個狀態下應該同時全部出現。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self._orig = reading.PROVIDER
        # 判讀說明刻意用極短字串：AI 自然語言長度不受本票的版面容量規則管（決策 0026
        # §20.1 規則 4 修訂後僅約束主動推播訊息），但容量腳本目前不分卡片種類、一律計數，
        # 這裡用短字串讓「判讀結論」卡的卡面文字可驗證地落在單卡上限內，不代表正式產品
        # 會限制 AI 說明的長度。
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "加碼"}'))
        perf.import_manual(main.conn, self.bid, self.cycle_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        # 現有匯入路徑（CSV／手動／模擬）都不分產品寫回 performance_snapshot.product_id
        # （這欄位早就存在 schema，只是還沒有任何呼叫端填它——見 test_ads_reading.py
        # 的 test_says_it_cannot_split_by_product_when_data_is_aggregate）。這裡直接補一筆
        # 更新，模擬「這筆成效資料查得出是哪個產品」的情境，才能驗到「③分開看每個產品」
        # 這塊——零 migration，只是測試資料層面補一個既有欄位的值。
        snapshot_id = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]["id"]
        main.conn.execute("UPDATE performance_snapshot SET product_id = ? WHERE id = ?",
                          (self.product, snapshot_id))
        main.conn.commit()
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        assert ok, err

    def tearDown(self):
        reading.PROVIDER = self._orig


class FixtureParityTest(_JudgedCycleTest):
    """本票只搬版面：同一組 fixture 的判讀結論、成色標籤、可信度數值要跟拆層前完全一致。"""

    def test_reading_verdict_and_grade_unchanged(self):
        cycle_reading = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]
        # scale_candidate 的人話標籤（reading.STATUS_LABELS）
        self.assertEqual(cycle_reading["status_label"], "可以考慮加碼")
        # 懶人模式資料成色（決策 0025 第 6 點）
        self.assertEqual(cycle_reading["result"]["data_grade"]["label"], "Meta 視角判讀")

    def test_confidence_defaults_to_trustworthy_without_reconcile_findings(self):
        loaded = ads_reconcile.load(main.conn, self.bid, self.cycle_id)
        self.assertEqual(loaded["rows"], [])
        self.assertEqual(loaded["label"], "可信")

    def test_next_cycle_draft_numbers_unchanged(self):
        budget = nextcycle.load(main.conn, self.bid, self.cycle_id)["content"]["budget"]
        self.assertEqual(budget["current_budget"], 10000)   # 這期預算
        self.assertEqual(budget["proposed_budget"], 12000)  # 建議下期預算（scale_candidate 上限 20%）


class InsufficientDataStillGradesTest(unittest.TestCase):
    """驗收條件：資料不足時仍給結論並標成色，不擋路、不顯示假數字。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露花藝",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        perf.import_manual(main.conn, self.bid, self.cycle_id, {"spend": 3000}, actor=ACTOR)

    def test_performance_page_says_insufficient_not_zero(self):
        # 分母是 0 就給 None，頁面才印得出「資料不足」而不是硬給一個 0（鐵則 16）。
        kpis = perf.totals(main.conn, self.bid, self.cycle_id)["kpis"]
        self.assertIsNone(kpis["ctr"])
        self.assertIsNone(kpis["cpc"])
        self.assertIsNone(kpis["roas"])


class ShopeeCodeReadonlyGlanceTest(_JudgedCycleTest):
    """已記錄的蝦皮碼要在成效頁的通路對照詳情內看得到唯讀摘要（不是表單）。"""

    def test_recorded_code_shows_up_readonly_on_performance_page(self):
        orders_channel.set_shopee_code(main.conn, self.bid, self.cycle_id, code="SHOP0801",
                                       redemption_count=3, actor=ACTOR)
        # 蝦皮碼是判讀當下讀的訊號，記錄後要重判讀一次才會反映進通路對照卡（既有行為，票 #40）。
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        assert ok, err
        channel = reading.load(main.conn, self.bid,
                               self.cycle_id)["cycle"]["result"]["channel_comparison"]
        self.assertEqual(channel["shopee_code"]["code"], "SHOP0801")


if __name__ == "__main__":
    unittest.main()
