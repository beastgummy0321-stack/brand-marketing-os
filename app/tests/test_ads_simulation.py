# -*- coding: utf-8 -*-
"""app/tests/test_ads_simulation.py — 廣告分支票 14：紙上模擬第 0 期。

重點：模擬數字由程式產生（不讓 LLM 編）、同一期可重現、全程標示非真實、
不產生投放交接包、跑過一期後入口就消失。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_sim_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import simulation  # noqa: E402
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


class _BaseSimTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _open(self, mode="simulation", amount="10000"):
        resp = self.client.post(f"/brands/{self.bid}/ads/new",
                                data={"custom_amount": amount, "objective": "sales",
                                      "mode": mode},
                                follow_redirects=False)
        return resp.headers["location"].split("/ads/")[1].split("?")[0]


class SimulationEntryTest(_BaseSimTest):
    def test_first_time_defaults_to_simulation(self):
        page = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertIn("先跑一次模擬", page.text)
        index = page.text.index('value="simulation"')
        self.assertIn("checked", page.text[index:index + 60])

    def test_entry_disappears_after_the_first_cycle(self):
        """跑過一期就別擋熟手的路。"""
        self._open(mode="real")
        page = self.client.get(f"/brands/{self.bid}/ads/new")
        self.assertNotIn("先跑一次模擬", page.text)

    def test_user_can_skip_straight_to_a_real_cycle(self):
        """選「直接開真的」就不是模擬期。（第一期真檔期會被標成校準期，見票 15。）"""
        cycle_id = self._open(mode="real")
        self.assertNotEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"],
                            "simulation")

    def test_simulation_cycle_is_marked(self):
        cycle_id = self._open()
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"],
                         "simulation")
        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}")
        self.assertIn("這是一期模擬檔期", page.text)
        self.assertIn("不會實際投放", page.text)

    def test_cannot_sneak_a_simulation_after_the_first_cycle(self):
        """已經跑過真檔期的品牌不該再開出模擬期，即使表單被動手腳。"""
        self._open(mode="real")
        cycle_id = self._open(mode="simulation")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"], "normal")


class SimulatedNumbersTest(_BaseSimTest):
    def test_numbers_are_reproducible_for_the_same_cycle(self):
        """同一期重看永遠是同一組數字，不會每次重整就變一個結果。"""
        cycle_id = self._open()
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        basis, _ = simulation._basis(main.conn, self.bid)
        first = simulation.simulate_totals(cycle, basis, average_price=800)
        second = simulation.simulate_totals(cycle, basis, average_price=800)
        self.assertEqual(first, second)

    def test_different_cycles_get_different_numbers(self):
        a = ads_repo.get_cycle(main.conn, self.bid, self._open())
        b = ads_repo.get_cycle(main.conn, self.bid, self._open(mode="real", amount="10000"))
        basis, _ = simulation._basis(main.conn, self.bid)
        self.assertNotEqual(simulation.simulate_totals(a, basis, average_price=800),
                            simulation.simulate_totals(b, basis, average_price=800))

    def test_spend_matches_the_planned_budget(self):
        cycle_id = self._open(amount="20000")
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        summary = perf.totals(main.conn, self.bid, cycle_id)
        self.assertEqual(summary["spend"], 20000)

    def test_numbers_are_internally_consistent(self):
        """點擊不能多於曝光——模擬數字自己也要過得了合理性海關。"""
        cycle_id = self._open(amount="30000")
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, cycle_id)[0]
        self.assertLessEqual(row["clicks"], row["impressions"])
        self.assertLessEqual(row["conversions"], row["clicks"])
        self.assertEqual(row["quarantined"], 0)

    def test_source_is_marked_as_simulated(self):
        cycle_id = self._open()
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        self.assertEqual(perf.list_snapshots(main.conn, self.bid, cycle_id)[0]["source"],
                         "simulated")

    def test_regenerating_replaces_instead_of_stacking(self):
        cycle_id = self._open()
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, cycle_id)), 1)

    def test_real_cycle_cannot_be_simulated(self):
        cycle_id = self._open(mode="real")
        ok, msg = simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        self.assertFalse(ok)
        self.assertIn("不是模擬檔期", msg)

    def test_basis_says_where_the_numbers_came_from(self):
        _, note = simulation._basis(main.conn, self.bid)
        self.assertIn("產業通例值", note)


class SimulationPagesTest(_BaseSimTest):
    def setUp(self):
        super().setUp()
        self.cycle_id = self._open()
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text=json.dumps({"text": "模擬結果說明"}, ensure_ascii=False),
            structured=None, usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn"))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def test_performance_page_offers_simulation_not_csv(self):
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("產生模擬成效", page.text)
        self.assertNotIn("匯入 Meta 匯出的報表", page.text)

    def test_page_says_the_numbers_are_not_real(self):
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("不是真實投放結果", page.text)

    def test_simulated_cycle_can_be_read_like_a_real_one(self):
        """模擬期照樣走判讀——那正是要讓新手先看到的東西。"""
        self.client.post(f"/brands/{self.bid}/ads/{self.cycle_id}/performance/simulate",
                         follow_redirects=False)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertIsNotNone(loaded["cycle"])


if __name__ == "__main__":
    unittest.main()
