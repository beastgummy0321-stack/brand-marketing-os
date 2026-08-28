"""app/tests/test_ads_pacing.py — 票 08-pacing-alert：檔期預算步調警示。

純函數 classify() 情境測試（規格 0001「受測模組」指定 pacing 判定要純函數情境測試）：
燒太快、花不完、正常步調、檔期剛開始樣本不足四種案例，各含邊界值。
check_cycle() 是資料庫進出口，另外測：送進打斷佇列＋去重防轟炸＋狀態翻轉會再送一次＋
已結案／紙上模擬檔期不判定。
"""

import unittest

from app.ads import pacing
from app.ads import performance as ads_performance
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.core.db import new_id, now_iso

ACTOR = "測試員"



class ClassifyTest(unittest.TestCase):
    """純函數，不碰資料庫。門檻固定用 0.15（15 個百分點）方便手算。"""

    def test_normal_pacing_within_threshold(self):
        # 期長 100 天，過了 50 天（time_progress=0.5），花了 52%（budget_progress=0.52）
        # 偏差 0.02 < 0.15，正常步調。
        result = pacing.classify(budget=10000, spend=5200, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-02-19",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "normal")

    def test_overspend_burning_too_fast(self):
        # 期長 100 天，過了 50 天（time_progress=0.5），已經花了 80%（budget_progress=0.8）
        # 偏差 0.3 > 0.15，燒太快，預算會提前燒完。
        result = pacing.classify(budget=10000, spend=8000, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-02-19",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "overspend")
        self.assertAlmostEqual(result["deviation"], 0.3, places=2)

    def test_underspend_wont_use_up_budget(self):
        # 期長 100 天，過了 50 天（time_progress=0.5），只花了 20%（budget_progress=0.2）
        # 偏差 -0.3 < -0.15，花不完。
        result = pacing.classify(budget=10000, spend=2000, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-02-19",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "underspend")

    def test_insufficient_sample_when_cycle_just_started(self):
        """檔期開跑不到 3 天（MIN_SAMPLE_DAYS），就算花費比例看起來離譜也不判定，
        避免第一天用掉 50% 每日預算就被誤判成「燒太快」。"""
        result = pacing.classify(budget=10000, spend=5000, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-01-02",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "insufficient_sample")

    def test_boundary_exact_threshold_is_normal_not_overspend(self):
        """剛好等於門檻算正常，超過門檻才算異常——差一點不算，跟 sample_size_tier
        的邊界慣例（>= 才算）對齊但方向相反：這裡偏差要「超過」門檻才觸發。"""
        result = pacing.classify(budget=10000, spend=6500, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-02-19",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "normal")

    def test_no_budget_is_insufficient_sample_not_a_crash(self):
        """檔期還沒填預算（None 或 0）算不出進度比例，不判定、不噴錯（鐵則 16）。"""
        result = pacing.classify(budget=None, spend=100, start_date="2026-01-01",
                                 end_date="2026-04-10", today="2026-02-19",
                                 threshold_pct=0.15)
        self.assertEqual(result["status"], "insufficient_sample")
        result2 = pacing.classify(budget=0, spend=100, start_date="2026-01-01",
                                  end_date="2026-04-10", today="2026-02-19",
                                  threshold_pct=0.15)
        self.assertEqual(result2["status"], "insufficient_sample")


class CheckCycleTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構步調茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def _make_cycle(self, *, budget=10000, start_date="2026-01-01", end_date="2026-04-10",
                    status="LIVE", phase="normal") -> str:
        cycle_id = new_id("ccy")
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective, budget,"
            " currency, start_date, end_date, channels_json, status, archived, plan_version,"
            " phase, created_at, updated_at) VALUES (%s, %s, %s, '[]', 'sales', %s, 'TWD', %s, %s,"
            " '[\"meta\"]', %s, false, 0, %s, %s, %s)",
            (cycle_id, db.DEV_ORG_ID, self.bid, budget, start_date, end_date, status, phase, ts, ts),
        )
        self.conn.commit()
        return cycle_id

    def _spend(self, cycle_id: str, amount: float, *, today: str) -> None:
        ads_performance.import_manual(
            self.conn, self.bid, cycle_id,
            {"spend": amount, "date_start": today, "date_stop": today},
            actor=ACTOR, today=today)

    def test_overspend_enqueues_rule_warning_interrupt(self):
        cycle_id = self._make_cycle()
        self._spend(cycle_id, 8000, today="2026-02-19")

        interrupt_id = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19")

        self.assertIsNotNone(interrupt_id)
        rows = core_interrupts.list_open(self.conn, brand_id=self.bid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "pacing_overspend")
        # 燒太快是「錢有風險」不是「錢已損失」（code review 2026-08-06 定調）：
        # money_loss 會把品牌燈號直接判紅，真的賠錢由判讀狀態機負責喊。
        self.assertEqual(rows[0]["severity"], "rule_warning")
        self.assertEqual(rows[0]["campaign_cycle_id"], cycle_id)
        self.assertEqual(rows[0]["action_url"], f"/app/brands/{self.bid}/campaigns/{cycle_id}")
        self.assertLessEqual(len(rows[0]["message"]), 30)

    def test_underspend_enqueues_rule_warning_interrupt(self):
        cycle_id = self._make_cycle()
        self._spend(cycle_id, 2000, today="2026-02-19")

        interrupt_id = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19")

        self.assertIsNotNone(interrupt_id)
        rows = core_interrupts.list_open(self.conn, brand_id=self.bid)
        self.assertEqual(rows[0]["category"], "pacing_underspend")
        self.assertEqual(rows[0]["severity"], "rule_warning")

    def test_normal_pacing_does_not_enqueue(self):
        cycle_id = self._make_cycle()
        self._spend(cycle_id, 5200, today="2026-02-19")

        interrupt_id = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19")

        self.assertIsNone(interrupt_id)
        self.assertEqual(core_interrupts.list_open(self.conn, brand_id=self.bid), [])

    def test_same_cycle_same_status_does_not_spam(self):
        """同一檔期同一狀況不重複轟炸：第二次呼叫（數字沒變化，狀態一樣）不再新增一筆。"""
        cycle_id = self._make_cycle()
        self._spend(cycle_id, 8000, today="2026-02-19")

        first = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19")
        second = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-20")

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(core_interrupts.list_open(self.conn, brand_id=self.bid)), 1)

    def test_status_flip_sends_a_new_alert(self):
        """從燒太快轉成花不完（例如手動降預算配速），狀態翻轉要能再送一次，不被舊去重鍵擋住。"""
        cycle_id = self._make_cycle()
        self._spend(cycle_id, 8000, today="2026-02-19")
        pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19")

        # 之後沒再花錢、時間繼續走到期末前，累積花費比例被時間進度拉過去，偏差翻到花不完那一側。
        second = pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-04-08")

        self.assertIsNotNone(second)
        rows = core_interrupts.list_open(self.conn, brand_id=self.bid)
        self.assertEqual(len(rows), 2)
        categories = {r["category"] for r in rows}
        self.assertEqual(categories, {"pacing_overspend", "pacing_underspend"})

    def test_closed_cycle_is_not_evaluated(self):
        cycle_id = self._make_cycle(status="CLOSED")
        self._spend(cycle_id, 8000, today="2026-02-19")
        self.assertIsNone(pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19"))

    def test_simulation_phase_is_not_evaluated(self):
        """紙上模擬（決策 0022 第 14 點）不是真錢，不判定步調。"""
        cycle_id = self._make_cycle(phase="simulation")
        self._spend(cycle_id, 8000, today="2026-02-19")
        self.assertIsNone(pacing.check_cycle(self.conn, self.bid, cycle_id, today="2026-02-19"))

    def test_unknown_cycle_returns_none(self):
        self.assertIsNone(pacing.check_cycle(self.conn, self.bid, "ccy_nope", today="2026-02-19"))


if __name__ == "__main__":
    unittest.main()
