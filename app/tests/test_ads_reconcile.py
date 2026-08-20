# -*- coding: utf-8 -*-
"""app/tests/test_ads_reconcile.py — 廣告分支票 11：對帳護欄接上真實資料。

判斷邏輯的邊界測試在 test_ads_budget_guardrails.py；這裡測的是「接得對不對」：
資料組得對、Finding 存得進去、可信度算得出來、不擋路。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_recon_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reconcile as recon  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class _BaseReconcileTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]

    def _spend(self, amount):
        perf.import_manual(main.conn, self.bid, self.cycle_id, {"spend": amount}, actor=ACTOR)

    def _url(self):
        return f"/brands/{self.bid}/ads/{self.cycle_id}/performance/reconcile"


class ReconcileWiringTest(_BaseReconcileTest):
    def test_matching_spend_produces_no_findings(self):
        self._spend(10000)
        result = recon.run(main.conn, self.bid, self.cycle_id)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["label"], "可信")

    def test_overspend_is_caught_and_stored(self):
        self._spend(14000)
        result = recon.run(main.conn, self.bid, self.cycle_id)
        self.assertEqual(len(result["findings"]), 1)
        self.assertLess(result["confidence"], 1.0)
        rows = ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "reconciliation")
        self.assertEqual(len(rows), 1)
        self.assertIn("多了", rows[0]["message"])

    def test_quarantined_rows_do_not_participate(self):
        """隔離區的壞資料不能拿去對帳，否則會對出假警報。"""
        self._spend(10000)
        perf.import_csv(main.conn, self.bid, self.cycle_id,
                        "行銷活動名稱,花費金額\n測試,-99999\n", actor=ACTOR)
        result = recon.run(main.conn, self.bid, self.cycle_id)
        self.assertEqual(result["findings"], [])

    def test_no_performance_data_means_nothing_to_reconcile(self):
        result = recon.run(main.conn, self.bid, self.cycle_id)
        self.assertEqual(result["findings"], [])

    def test_rerun_replaces_instead_of_accumulating(self):
        self._spend(14000)
        recon.run(main.conn, self.bid, self.cycle_id)
        recon.run(main.conn, self.bid, self.cycle_id)
        rows = ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "reconciliation")
        self.assertEqual(len(rows), 1)

    def test_self_answers_add_findings_with_the_same_shape(self):
        self._spend(10000)
        result = recon.run(main.conn, self.bid, self.cycle_id,
                           self_answers={"budget_same": False})
        self.assertEqual(len(result["findings"]), 1)
        rows = ads_repo.list_findings(main.conn, self.bid, self.cycle_id, "external_change")
        self.assertEqual(rows[0]["source"], "self_answer")

    def test_confidence_labels_step_down(self):
        self.assertEqual(recon.describe_confidence(1.0)[0], "可信")
        self.assertEqual(recon.describe_confidence(0.7)[0], "可信度打折")
        self.assertEqual(recon.describe_confidence(0.2)[0], "僅供參考")


class ReconcilePageTest(_BaseReconcileTest):
    def test_page_shows_confidence_and_does_not_block(self):
        self._spend(14000)
        resp = self.client.post(self._url(), data={}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("本期判讀可信度", page.text)
        self.assertIn("可信度打折", page.text)

    def test_answering_nothing_is_allowed(self):
        """自答是補充資訊，不是新的必經關卡——三題都不答也能按。"""
        self._spend(10000)
        resp = self.client.post(self._url(), data={}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("kind=warn", resp.headers["location"])

    def test_answers_flow_through_the_page(self):
        self._spend(10000)
        self.client.post(self._url(), data={"budget_same": "no"}, follow_redirects=False)
        page = self.client.get(f"/brands/{self.bid}/ads/{self.cycle_id}/performance")
        self.assertIn("跟交接包不一樣", page.text)


if __name__ == "__main__":
    unittest.main()
