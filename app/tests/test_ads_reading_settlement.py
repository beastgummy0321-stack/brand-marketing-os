# -*- coding: utf-8 -*-
"""app/tests/test_ads_reading_settlement.py — 票 06：結算完成後必須撐過重判。

setUp／fixture 比照 app/tests/test_ads_reading.py 的 _ReadingIntegrationBase（同一個
建檔＋灌成效資料的樣板），不另開新的測試骨架。一個完成檢查對一支測試。
"""

import unittest

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.llm.providers import FakeProvider, ProviderResponse, Usage

ACTOR = "測試員"


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


# BUG app/ads/performance.py:364 — import_rows() 的 INSERT 對 date 欄位傳 ""，
# Postgres 一律 psycopg.errors.InvalidDatetimeFormat（同一個 BUG，orders/ads 群組已標過）。
_BUG_EMPTY_STRING_DATE = pytest.mark.xfail(
    strict=True,
    reason='BUG app/ads/performance.py:364 — import_rows() 的 INSERT 對 date 欄位傳 ""，'
           "Postgres 一律 psycopg.errors.InvalidDatetimeFormat",
)


class _SettlementBase(unittest.TestCase):
    """比照 test_ads_reading.py 的 _ReadingIntegrationBase：建品牌＋產品＋開一期檔期。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡（票06）",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構濾掛組",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake('{"text": "測試判讀說明"}'))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)


class WeeklyRejudgeRefusedTest(_SettlementBase):
    """完成檢查 1：已結算的檔期，一般重判（沒帶 trigger_reason）要被拒絕，結算原封不動。"""

    @_BUG_EMPTY_STRING_DATE
    def test_run_without_trigger_reason_refused_after_settlement(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        settlement_before = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]

        ok2, reason = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        self.assertFalse(ok2)
        self.assertIsInstance(reason, str)
        self.assertTrue(reason.strip())
        self.assertIn("結算", reason)  # 白話理由要講清楚結算還在，不是錯誤代碼

        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "CLOSED")
        self.assertNotEqual(cycle["status"], "EVALUATING")  # 覆盤閘門 status != CLOSED 仍會放行

        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertEqual(loaded["cycle"]["id"], settlement_before["id"])  # 結算判讀列還在
        self.assertFalse(loaded["cycle"]["result"]["is_tentative"])


class LateDataOnSettledCycleTest(_SettlementBase):
    """完成檢查 2：補件重判（trigger_reason='late_data'）仍能碰已結案的檔期，且留在 CLOSED。"""

    @_BUG_EMPTY_STRING_DATE
    def test_rerun_for_late_data_after_settlement_not_refused(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        # 晚到一筆巨額花費，確保補件重判算出來的快照跟結算版有差異（不然 diff 是空的，
        # rerun_for_late_data 會回 None，測不出「有沒有被拒絕」）。
        self._spend(spend=50000, impressions=0, clicks=0, conversions=0, revenue=0)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)

        self.assertIsNotNone(outcome)
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "CLOSED")


class NormalRejudgeUnaffectedTest(_SettlementBase):
    """完成檢查 3：檔期還在 LIVE/EVALUATING 時，一般重判照舊——不受這次改動影響。"""

    @_BUG_EMPTY_STRING_DATE
    def test_run_without_trigger_reason_on_live_cycle_succeeds(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)

        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        self.assertTrue(ok)
        self.assertIsNone(err)
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "EVALUATING")


class FinalizeAtomicCloseTest(_SettlementBase):
    """完成檢查 4：不會有「結算判讀列已存在、檔期卻還是 EVALUATING」這個中間狀態——
    run(trigger_reason='final_settlement') 自己一次就把狀態寫成 CLOSED，不必等 finalize()
    事後補寫。"""

    @_BUG_EMPTY_STRING_DATE
    def test_final_settlement_run_alone_leaves_cycle_closed(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)

        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR,
                              trigger_reason="final_settlement")

        self.assertTrue(ok, err)
        cycle = ads_repo.get_cycle(main.conn, self.bid, self.cycle_id)
        self.assertEqual(cycle["status"], "CLOSED")
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertFalse(loaded["cycle"]["result"]["is_tentative"])


class ScopedDeleteProtectsSettlementTest(_SettlementBase):
    """完成檢查 5：非結算重判不能刪到結算版本那幾列。"""

    @_BUG_EMPTY_STRING_DATE
    def test_non_settlement_run_keeps_settlement_reading(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        settlement_id = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["id"]

        # 建構「有結算列但檔期不是 CLOSED」的狀態：直接改 SQL 繞過 D2 的守門，
        # 專門測 D4 的範圍刪除本身夠不夠格擋住結算列，不依賴上層守門有沒有生效。
        main.conn.execute("UPDATE campaign_cycle SET status = 'EVALUATING' WHERE id = %s",
                          (self.cycle_id,))
        main.conn.commit()
        self._spend(spend=1000, impressions=100, clicks=10, conversions=1, revenue=2000)

        ok2, err2 = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        self.assertTrue(ok2, err2)
        rows = main.conn.execute(
            "SELECT id, product_id, rule_result_json FROM performance_reading"
            " WHERE campaign_cycle_id = %s", (self.cycle_id,)).fetchall()
        ids = [r["id"] for r in rows]
        self.assertIn(settlement_id, ids)  # 結算列還在，沒被非結算重判刪掉

        settlement_row = next(r for r in rows if r["id"] == settlement_id)
        self.assertFalse(settlement_row["rule_result_json"]["is_tentative"])  # psycopg 已自動解 jsonb

        new_tentative = [r for r in rows
                         if r["product_id"] is None and r["id"] != settlement_id]
        self.assertTrue(new_tentative)  # 這次重判自己的暫定版另外多出一列，不是就地改掉結算列


if __name__ == "__main__":
    unittest.main()


class RejudgeButtonMessageTest(_SettlementBase):
    """手檢那條：駕駛艙「現在就重新判讀」按鈕在只剩已結案檔期時，畫面要說出白話理由。

    current_cycle() 只挑 LIVE／EVALUATING，已結案的期根本進不了 run()，所以擋的話講不出口
    的話得由端點自己補（routes_weekly_proposals_api.py），句子跟 run() 的拒絕理由同一個出處。
    """

    @_BUG_EMPTY_STRING_DATE
    def test_rejudge_endpoint_explains_settlement_instead_of_generic_empty(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/weekly/rejudge")

        self.assertEqual(resp.status_code, 400)
        message = resp.json()["data"]["error"]
        self.assertIn("結算", message)
        self.assertNotEqual(message, "目前沒有可判讀的檔期")


class LateRevenueShareReversalWarningTest(_SettlementBase):
    """票 R4-late-data-downstream（B0-35）：翻盤時晚到營收占比過高（門檻見 ads_settlement.
    LATE_REVENUE_SHARE_WARNING_THRESHOLD），匯入訊息（explanation）跟收件匣通知都要多
    一句查核提醒，不能讓人以為這是查證過的翻案。"""

    @_BUG_EMPTY_STRING_DATE
    def test_reversal_with_high_late_revenue_share_adds_check_prompt(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=8000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.assertEqual(reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["status"],
                         "pause_candidate")  # roas 0.8 倍，打平線 1.67 倍

        # 晚到訂單只補營收，不補花費／轉換——單筆晚到營收占補件後總營收 60%（12000/20000）。
        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=12000)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)

        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["shift"], "reversal")
        self.assertEqual(outcome["after_status"], "maintain")  # roas 2.0 倍，落在維持區間
        self.assertIn("60%", outcome["explanation"])
        self.assertIn("查核", outcome["explanation"])

        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid,
                                                category="reading_reversal")
        self.assertEqual(len(open_items), 1)
        # 收件匣卡片受「一卡一句 ≤30 全形字」限制（DESIGN.md §20 規則 4），放不下百分比，
        # 只換一句同樣點名查核的短版；完整占比說明在上面的 explanation（匯入訊息）裡。
        self.assertLessEqual(len(open_items[0]["message"]), 30)
        self.assertIn("查核", open_items[0]["message"])

class AssetBreakdownDraggingDownFlagTest(_SettlementBase):
    """票 R4-late-data-downstream（B0-33 覆審駁回後修復）：逐支表「拖累檔期」旗標要跟這期
    損益兩平比，不是逐支之間互相比大小——原本前端只找 rows 裡的最小值就標紅，三支比例
    相近、並列最低的廣告翻盤轉盈後仍然全部繼續掛紅標（獨立審查用真實 C4 補件形狀重現）。
    改在 `reading_assets.asset_totals()` 算好、跟著 `asset_breakdown` 存進
    `rule_result_json`，前端只管畫布林值。"""

    def _package(self, ad_name: str) -> str:
        pkg_id, ts = db.new_id("pkg"), db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " campaign_name, adset_name, ad_name, destination_url, utm_json, status,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, "測試活動", "測試組合", ad_name,
             "https://example.test", ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (db.new_id("xam"), db.DEV_ORG_ID, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        return pkg_id

    def _flags(self):
        breakdown = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["result"]["asset_breakdown"]
        return {row["asset_name"]: row["dragging_down_cycle"] for row in breakdown}

    @_BUG_EMPTY_STRING_DATE
    def test_three_tied_ads_flip_from_dragging_down_to_clear_after_late_revenue(self):
        ad_names = ("廣告A", "廣告B", "廣告C")
        for name in ad_names:
            self._package(name)

        nl = chr(10)
        header = "行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值"
        # 三支比例相近，roas 全部 0.50 倍（打平線 1.67 倍）——並列最低，全部真的在虧錢。
        rows = [f"測試活動,{name},5000,100,2000,4,1000" for name in ad_names]
        csv_text = nl.join([header] + rows)
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.matched_assets, 3, result.errors)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        self.assertEqual(self._flags(), {name: True for name in ad_names})

        # 晚到訂單只補營收（同 B0-35 那批 late CSV 的形狀），三支一樣多——翻盤後 roas 全部
        # 2.25 倍，並列最低但已經不虧了，一支都不該再掛紅標。
        late_rows = [f"測試活動,{name},0,0,0,0,3500" for name in ad_names]
        late_csv = nl.join([header] + late_rows)
        result2 = perf.import_csv(main.conn, self.bid, self.cycle_id, late_csv, actor=ACTOR)
        self.assertEqual(result2.matched_assets, 3, result2.errors)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        self.assertIsNotNone(outcome)

        self.assertEqual(self._flags(), {name: False for name in ad_names})
