# -*- coding: utf-8 -*-
"""app/tests/test_ads_home_console.py — 修憲落地 V3：廣告首頁遷 B｜工作台式
（DESIGN.md §21，決策 0033／0038）。

驗收重點：說明句改成資料（console-ui skill 硬規則1）——進行中檔期顯示「第 N 步／共 5 步」；
已判讀的最近結案檔期顯示 ROAS＋賺賠狀態膠囊；沒判讀過的已結案檔期整塊不出現
（principles.md 鐵則16：拿不到就不要放，不放假資料或 0 佔位）。
純版面的驗收（側欄結構／主要按鈕數／動作列連結／側欄徽章）隨舊頁一併刪除。

品牌與產品名一律虛構，絕不使用真實客戶品牌。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_home_console_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as ads_perf  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import stages  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402


ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


def _fake(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=200, output_tokens=100),
                            stop_reason="end_turn")


class _BaseTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構晨露茶行{self.id()[-6:]}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _open_cycle(self, **overrides):
        data = {"budget": 10000, "objective": "sales"}
        data.update(overrides)
        data.pop("slider_index", None)
        if "custom_amount" in data:
            data["budget"] = float(data.pop("custom_amount"))
        resp = self.client.post(f"/api/campaigns/{self.bid}", json=data)
        self.assertEqual(resp.status_code, 200)
        return resp.json()["cycle_id"]

    def _campaign_items(self):
        """檔期清單 JSON API：hub 兩塊摘要（進行中第幾步／最近結案的判讀）的同一份資料
        ——`routes_campaigns_list_api._list_item()` 直接重用 hub 用的 `_hub_stage_info()`
        與 `_closed_cycle_reading()`，不是另算一份。"""
        resp = self.client.get(f"/api/campaigns/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        return {item["id"]: item for item in resp.json()["data"]}



class StageWordingTest(_BaseTest):
    def test_shows_step_index_out_of_five(self):
        cycle_id = self._open_cycle()
        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["stage_index"], 1)         # 第 1 步
        self.assertEqual(len(stages.STAGE_LABELS), 5)    # ／共 5 步（hub 的 stage_total）


class EndedUnsettledCycleDisplayTest(_BaseTest):
    """B0-05（`.scratch/rehearsal-b0-fix/issues/R5-cockpit-and-state-machine.md`）：真機重現
    end_date 已經過了 35 天的 LIVE 檔期，清單仍顯示「投放中・第 5 步／共 5 步・剩 0 天」
    ——收帳排程只在系統開著時才會被排到（`app/main.py _auto_sync_if_due()`），單機單人
    的使用型態不保證準時觸發。本票不做排程器（BOARD R5-S，另案批准），只在讀取時把
    「已經結束但還沒收帳」的狀態老實講出來。"""

    def _cycle(self, *, start_date: str, duration_days: int, status: str) -> str:
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=10000, objective="sales",
            actor=ACTOR, start_date=start_date, duration_days=duration_days)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle["id"], status=status, actor=ACTOR)
        return cycle["id"]

    def test_overdue_live_cycle_shows_ended_unsettled_not_live_zero_days_left(self):
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=20)).isoformat()
        cycle_id = self._cycle(start_date=start, duration_days=7, status="LIVE")

        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["status_label"], "已結束・待收帳")
        self.assertNotEqual(item["status_label"], "投放中")
        self.assertIsNone(item["days_left"])

    def test_overdue_evaluating_cycle_also_shows_ended_unsettled(self):
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=20)).isoformat()
        cycle_id = self._cycle(start_date=start, duration_days=7, status="EVALUATING")

        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["status_label"], "已結束・待收帳")

    def test_live_cycle_still_within_end_date_is_unaffected(self):
        """對照組：還沒過 end_date 的 LIVE 檔期維持原樣，不能被這次修復誤傷。"""
        from datetime import date
        cycle_id = self._cycle(start_date=date.today().isoformat(), duration_days=14, status="LIVE")

        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["status_label"], "投放中")
        self.assertIsNotNone(item["days_left"])


# BUG app/ads/performance.py:364 — import_rows() 的 INSERT 對 date 欄位傳 ""，
# Postgres 一律 psycopg.errors.InvalidDatetimeFormat（同一個 BUG，orders 群組已標過）。
_BUG_EMPTY_STRING_DATE = pytest.mark.xfail(
    strict=True,
    reason='BUG app/ads/performance.py:364 — import_rows() 的 INSERT 對 date 欄位傳 ""，'
           "Postgres 一律 psycopg.errors.InvalidDatetimeFormat",
)


class ClosedCycleSummaryTest(_BaseTest):
    """最近結案的檔期：ROAS／賺賠狀態膠囊直接讀已存的判讀快照，沒判讀過就誠實不顯示。"""

    def setUp(self):
        super().setUp()
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)

    def _judge(self, cycle_id):
        orig = ads_reading.PROVIDER
        ads_reading.PROVIDER = FakeProvider(response=_fake('{"text": "加碼"}'))
        try:
            ads_perf.import_manual(main.conn, self.bid, cycle_id,
                                   {"spend": 10000, "impressions": 20000, "clicks": 400,
                                    "conversions": 10, "revenue": 40000}, actor=ACTOR)
            ok, err = ads_reading.run(main.conn, self.bid, cycle_id, ACTOR)
            self.assertTrue(ok, err)
        finally:
            ads_reading.PROVIDER = orig

    @_BUG_EMPTY_STRING_DATE
    def test_judged_closed_cycle_shows_roas_and_verdict_badge(self):
        cycle_id = self._open_cycle(product_ids=[self.product], custom_amount="10000")
        self._judge(cycle_id)
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["bucket"], "closed")  # 就是「最近結案的檔期」那一塊的那期
        self.assertEqual(item["roas"], 4.0)  # revenue 40000 / spend 10000 → 畫面上的 4.00 倍
        self.assertIsNotNone(item["verdict_kind"])  # 賺賠狀態膠囊

    def test_unjudged_closed_cycle_shows_nothing_not_fake_data(self):
        """principles.md 鐵則16：拿不到就不要放，不放假資料或 0 佔位。"""
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id, status="CLOSED", actor=ACTOR)
        item = self._campaign_items()[cycle_id]
        self.assertEqual(item["bucket"], "closed")
        # 沒判讀過就整塊不出現＝這期一個判讀欄位都拿不到，不是 0 或空字串佔位
        self.assertIsNone(item["roas"])
        self.assertIsNone(item["verdict_kind"])
        self.assertIsNone(item["status_label_reading"])

