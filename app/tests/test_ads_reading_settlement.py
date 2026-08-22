# -*- coding: utf-8 -*-
"""app/tests/test_ads_reading_settlement.py — 票 06：結算完成後必須撐過重判。

setUp／fixture 比照 app/tests/test_ads_reading.py 的 _ReadingIntegrationBase（同一個
建檔＋灌成效資料的樣板），不另開新的測試骨架。一個完成檢查對一支測試。
"""

import atexit
import json
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_reading_settlement_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
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


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


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

    def test_non_settlement_run_keeps_settlement_reading(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        settlement_id = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["id"]

        # 建構「有結算列但檔期不是 CLOSED」的狀態：直接改 SQL 繞過 D2 的守門，
        # 專門測 D4 的範圍刪除本身夠不夠格擋住結算列，不依賴上層守門有沒有生效。
        main.conn.execute("UPDATE campaign_cycle SET status = 'EVALUATING' WHERE id = ?",
                          (self.cycle_id,))
        main.conn.commit()
        self._spend(spend=1000, impressions=100, clicks=10, conversions=1, revenue=2000)

        ok2, err2 = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)

        self.assertTrue(ok2, err2)
        rows = main.conn.execute(
            "SELECT id, product_id, rule_result_json FROM performance_reading"
            " WHERE campaign_cycle_id = ?", (self.cycle_id,)).fetchall()
        ids = [r["id"] for r in rows]
        self.assertIn(settlement_id, ids)  # 結算列還在，沒被非結算重判刪掉

        settlement_row = next(r for r in rows if r["id"] == settlement_id)
        self.assertFalse(json.loads(settlement_row["rule_result_json"])["is_tentative"])

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

    def test_rejudge_endpoint_explains_settlement_instead_of_generic_empty(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/weekly/rejudge")

        self.assertEqual(resp.status_code, 400)
        message = resp.json()["data"]["error"]
        self.assertIn("結算", message)
        self.assertNotEqual(message, "目前沒有可判讀的檔期")
