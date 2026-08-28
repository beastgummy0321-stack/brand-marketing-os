"""app/tests/test_ads_simulation.py — 廣告分支票 14：紙上模擬第 0 期。

重點：模擬數字由程式產生（不讓 LLM 編）、同一期可重現、全程標示非真實、
不產生投放交接包、跑過一期後入口就消失。
"""

import atexit
import json
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_sim_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import (
    reading,  # noqa: E402
    simulation,  # noqa: E402
)
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import DEV_ORG_ID, new_id, now_iso  # noqa: E402
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
                                          client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def _open(self, mode="simulation", amount="10000"):
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"budget": float(amount), "objective": "sales",
                                      "simulate": mode == "simulation"})
        return resp.json()["cycle_id"]


class SimulationEntryTest(_BaseSimTest):
    def test_user_can_skip_straight_to_a_real_cycle(self):
        """選「直接開真的」就不是模擬期。（第一期真檔期會被標成校準期，見票 15。）"""
        cycle_id = self._open(mode="real")
        self.assertNotEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"],
                            "simulation")

    def test_cannot_sneak_a_simulation_after_the_first_cycle(self):
        """已經跑過真檔期的品牌不該再開出模擬期，即使表單被動手腳。"""
        self._open(mode="real")
        cycle_id = self._open(mode="simulation")
        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle_id)["phase"], "normal")

    def test_entry_disappears_after_the_first_cycle(self):
        """跑過一期就別擋熟手的路。"""
        self._open(mode="real")
        ctx = self.client.get(f"/api/campaigns/{self.bid}/new-context").json()["data"]
        self.assertFalse(ctx["offer_simulation"])


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


class SimulatedProductAttributionTest(_BaseSimTest):
    """票 11 D3：模擬成效沒有廣告可對（沒有 publishing_package），`resolve_product_id`
    的 a／b 兩條路都用不上，一律留 NULL——「檔期只賣一個產品就算那個的」那條路
    （原設計選項 c）複審後拿掉了，即使檔期真的只賣一個產品也不再猜（鐵則 16）。"""

    def test_product_id_stays_null_even_when_cycle_sells_exactly_one_product(self):
        cycle_id = self._open(amount="10000")
        product = bi_repo.create_product(main.conn, self.bid, name="虛構商品", actor=ACTOR)
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle_product (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " allocated_budget, allocation_ratio, allocation_basis, economics_missing,"
            " created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'equal_split', false, %s, %s)",
            (new_id("ccp"), DEV_ORG_ID, cycle_id, self.bid, product["id"], 10000.0, 1.0, ts, ts),
        )
        main.conn.commit()
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, cycle_id)[0]
        self.assertIsNone(row["product_id"])

    def test_product_id_null_when_cycle_sells_no_product(self):
        cycle_id = self._open(amount="10000")
        simulation.generate(main.conn, self.bid, cycle_id, ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, cycle_id)[0]
        self.assertIsNone(row["product_id"])


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

    def test_simulated_cycle_can_be_read_like_a_real_one(self):
        """模擬期照樣走判讀——那正是要讓新手先看到的東西。"""
        self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/simulate")
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        loaded = reading.load(main.conn, self.bid, self.cycle_id)
        self.assertIsNotNone(loaded["cycle"])


if __name__ == "__main__":
    unittest.main()
