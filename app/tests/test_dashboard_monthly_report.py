# -*- coding: utf-8 -*-
"""票 07：Act3 月報數字唯讀聚合與 API。"""

import atexit
import os
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_dashboard_monthly_report_")
os.environ["BRAND_OS_TODAY"] = "2026-08-05"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id  # noqa: E402
from app.dashboard import repository as dashboard_repo  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
TODAY = "2026-08-05"


def _seed_spend(conn, brand_id: str, *, date_str: str, spend: float) -> str:
    ads_performance.import_manual(
        conn, brand_id, None,
        {"date_start": date_str, "spend": spend, "impressions": 1000, "clicks": 10,
         "conversions": 1, "revenue": None},
        actor=ACTOR, today=TODAY,
    )
    row = conn.execute(
        "SELECT id FROM performance_snapshot WHERE brand_id = ? AND date_range_start = ?"
        " ORDER BY created_at DESC LIMIT 1", (brand_id, date_str),
    ).fetchone()
    return row["id"]


def _seed_roas(conn, brand_id: str, *, snapshot_id: str, value: float, computed_at: str) -> None:
    conn.execute(
        "INSERT INTO derived_metric (id, brand_id, performance_snapshot_id,"
        " campaign_cycle_id, metric, value, calc_basis, computed_at, created_at)"
        " VALUES (?, ?, ?, NULL, 'roas', ?, '測試塞入', ?, ?)",
        (new_id("dmt"), brand_id, snapshot_id, value, computed_at, computed_at),
    )
    conn.commit()


class DashboardMonthlyReportTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構月報茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)

    def test_month_boundaries_keep_current_month_data_only(self):
        orders_repo.save_orders(
            main.conn, self.brand["id"],
            [{"order_number": "ORD-AUG", "order_date": "2026-08-02",
              "total_amount": 700, "refunded_amount": 0}],
            source="test", actor=ACTOR)
        orders_repo.save_orders(
            main.conn, self.brand["id"],
            [{"order_number": "ORD-JUL", "order_date": "2026-07-02",
              "total_amount": 500, "refunded_amount": 0}],
            source="test", actor=ACTOR)
        aug_snapshot = _seed_spend(main.conn, self.brand["id"],
                                    date_str="2026-08-03", spend=300)
        jul_snapshot = _seed_spend(main.conn, self.brand["id"],
                                    date_str="2026-07-03", spend=200)
        _seed_roas(main.conn, self.brand["id"], snapshot_id=jul_snapshot,
                   value=2.0, computed_at="2026-07-03T10:00:00")
        _seed_roas(main.conn, self.brand["id"], snapshot_id=aug_snapshot,
                   value=4.0, computed_at="2026-08-03T10:00:00")

        report = dashboard_repo.monthly_report(main.conn, self.brand["id"], "2026-08")

        self.assertEqual(report["spend"], 300)
        self.assertEqual(report["orders"], 1)
        self.assertEqual(report["revenue"], 700)
        self.assertEqual(report["roas"], 4.0)
        self.assertEqual(report["cac"], 300.0)
        self.assertEqual(report["trend"]["months"][-1], "2026-08")

    def test_no_data_month_returns_none_metrics_and_trend(self):
        report = dashboard_repo.monthly_report(main.conn, self.brand["id"], "2026-08")

        for key in ("spend", "orders", "revenue", "roas", "cac"):
            self.assertIsNone(report[key], key)
        self.assertEqual(len(report["trend"]["months"]), 6)
        self.assertEqual(len(report["trend"]["cac"]), 6)

    def test_cac_is_none_when_orders_are_zero(self):
        _seed_spend(main.conn, self.brand["id"], date_str="2026-08-03", spend=300)

        report = dashboard_repo.monthly_report(main.conn, self.brand["id"], "2026-08")

        self.assertEqual(report["orders"], 0)
        self.assertIsNone(report["cac"])

    def test_endpoint_envelope_and_invalid_month_message(self):
        response = self.client.get(
            f"/api/dashboard/brands/{self.brand['id']}/monthly-report?month=2026-08"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())
        self.assertIn("generated_at", response.json())

        invalid = self.client.get(
            f"/api/dashboard/brands/{self.brand['id']}/monthly-report?month=2026-13"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("YYYY-MM", invalid.text)


if __name__ == "__main__":
    unittest.main()
