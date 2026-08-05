# -*- coding: utf-8 -*-
"""app/tests/test_dashboard_cockpit.py — 票 03-cockpit-kpi-chart：單品牌駕駛艙 API。

隔離測試資料庫（BRAND_OS_DB 指向 tmp 檔），TestClient 模式（比照
app/tests/test_dashboard_overview.py）。測試品牌一律虛構。

KPI 口徑（規格 0001）：本月營收＝訂單實收；花費＝成效快照 spend 加總；
ROAS 取自 derived_metric；環比＝與上月同期比較。
"""

import atexit
import os
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_dashboard_cockpit_")
os.environ["BRAND_OS_DB"] = str(os.path.join(_tmpdir, "test.db"))
os.environ["BRAND_OS_BACKUP_DIR"] = str(os.path.join(_tmpdir, "backups"))
os.environ["BRAND_OS_UPLOADS"] = str(os.path.join(_tmpdir, "uploads"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

main.reopen_connection()


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
    """品牌層（無檔期）成效快照一列，走公開的 import_manual（比照真實匯入路徑，
    不直接寫表）。回傳寫入的 performance_snapshot id，供 derived_metric 外鍵用。"""
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
    """derived_metric 沒有跨層公開寫入函式給「品牌層＋任意月份」這種測試情境用
    （`save_derived_metrics` 只認真的檔期並整批先刪後寫）；測試檔豁免跨層 SQL 掃描
    （見 test_architecture_boundaries.py 的 app/tests/ 排除清單），直接塞一列。"""
    conn.execute(
        "INSERT INTO derived_metric (id, brand_id, performance_snapshot_id,"
        " campaign_cycle_id, metric, value, calc_basis, computed_at, created_at)"
        " VALUES (?, ?, ?, NULL, 'roas', ?, '測試塞入', ?, ?)",
        (new_id("dmt"), brand_id, snapshot_id, value, computed_at, computed_at),
    )
    conn.commit()


class DashboardCockpitApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_empty = bi_repo.create_brand(
            main.conn, name=f"虛構空白茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.brand_full = bi_repo.create_brand(
            main.conn, name=f"虛構滿載雜貨店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)

        # 訂單：本月 2 筆共 1200、上月 1 筆共 1000 → 營收環比 +20%、訂單數環比 +100%
        orders_repo.save_orders(
            main.conn, self.brand_full["id"],
            [{"order_number": "ORD-THIS-1", "order_date": "2026-08-01",
              "total_amount": 700, "refunded_amount": 0},
             {"order_number": "ORD-THIS-2", "order_date": "2026-08-02",
              "total_amount": 500, "refunded_amount": 0}],
            source="test", actor=ACTOR)
        orders_repo.save_orders(
            main.conn, self.brand_full["id"],
            [{"order_number": "ORD-LAST", "order_date": "2026-07-01",
              "total_amount": 1000, "refunded_amount": 0}],
            source="test", actor=ACTOR)

        # 花費：本月 300、上月 200 → 環比 +50%
        _seed_spend(main.conn, self.brand_full["id"], date_str="2026-08-03", spend=300)
        _seed_spend(main.conn, self.brand_full["id"], date_str="2026-07-03", spend=200)

        # ROAS：本月 4.0（derived_metric 直接落地值，不是拿 revenue/spend 現算）、
        # 上月 2.0 → 環比 +100%
        snap_this = _seed_spend(main.conn, self.brand_full["id"], date_str="2026-08-04", spend=1)
        _seed_roas(main.conn, self.brand_full["id"], snapshot_id=snap_this, value=4.0,
                  computed_at="2026-08-04T10:00:00")
        snap_last = _seed_spend(main.conn, self.brand_full["id"], date_str="2026-07-04", spend=1)
        _seed_roas(main.conn, self.brand_full["id"], snapshot_id=snap_last, value=2.0,
                  computed_at="2026-07-04T10:00:00")

        # 邊界：只有 6 個月視窗中最舊的月份（2026-03）有一筆花費，其餘月份都沒資料
        _seed_spend(main.conn, self.brand_full["id"], date_str="2026-03-15", spend=50)

    def _get(self, brand_id):
        return self.client.get(f"/api/dashboard/brands/{brand_id}/cockpit")

    # -- envelope / 404 -----------------------------------------------------

    def test_envelope_has_data_and_generated_at(self):
        resp = self._get(self.brand_empty["id"])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        self.assertEqual(body["data"]["brand_id"], self.brand_empty["id"])

    def test_unknown_brand_is_404(self):
        resp = self._get("brand_does_not_exist")
        self.assertEqual(resp.status_code, 404)

    # -- 無資料邊界 -----------------------------------------------------------

    def test_brand_with_no_data_returns_none_not_zero(self):
        """「沒得算」跟「等於 0」是兩件事：完全沒有訂單／成效資料的品牌，營收／花費／
        ROAS 要回 None，不是悄悄算成 0（鐵則 16）。訂單數例外——「這段期間 0 筆訂單」
        是算得出來的事實，回 0 不回 None。"""
        kpis = self._get(self.brand_empty["id"]).json()["data"]["kpis"]
        self.assertIsNone(kpis["revenue"]["value"])
        self.assertIsNone(kpis["spend"]["value"])
        self.assertIsNone(kpis["roas"]["value"])
        self.assertEqual(kpis["orders"]["value"], 0)
        for kpi in kpis.values():
            self.assertIsNone(kpi["mom_pct"])

    def test_brand_with_no_data_chart_has_six_empty_months(self):
        chart = self._get(self.brand_empty["id"]).json()["data"]["chart"]
        self.assertEqual(len(chart["months"]), 6)
        self.assertEqual(chart["months"][-1], "2026-08")
        self.assertTrue(all(v is None for v in chart["revenue"]))
        self.assertTrue(all(v is None for v in chart["spend"]))

    # -- KPI 口徑：已知資料算對 -------------------------------------------------

    def test_revenue_this_month_and_mom_pct(self):
        kpis = self._get(self.brand_full["id"]).json()["data"]["kpis"]
        self.assertEqual(kpis["revenue"]["value"], 1200)
        self.assertEqual(kpis["revenue"]["mom_pct"], 20.0)

    def test_orders_this_month_and_mom_pct(self):
        kpis = self._get(self.brand_full["id"]).json()["data"]["kpis"]
        self.assertEqual(kpis["orders"]["value"], 2)
        self.assertEqual(kpis["orders"]["mom_pct"], 100.0)

    def test_spend_this_month_is_sum_of_performance_snapshot_spend(self):
        kpis = self._get(self.brand_full["id"]).json()["data"]["kpis"]
        # 本月三筆花費快照：300 + 1（ROAS 那筆）= 301；上月 200 + 1 = 201
        self.assertEqual(kpis["spend"]["value"], 301)
        self.assertEqual(kpis["spend"]["mom_pct"], round((301 - 201) / 201 * 100, 1))

    def test_roas_value_comes_from_derived_metric_not_recomputed(self):
        """規格明講「ROAS 取自 derived_metric」——落地值是 4.0，若程式改成拿
        revenue/spend 現算，這裡（revenue 完全沒收集、spend=301）會算出 None 或錯誤值，
        測試就會抓到。"""
        kpis = self._get(self.brand_full["id"]).json()["data"]["kpis"]
        self.assertEqual(kpis["roas"]["value"], 4.0)
        self.assertEqual(kpis["roas"]["mom_pct"], 100.0)

    def test_chart_months_are_last_six_calendar_months_ascending(self):
        chart = self._get(self.brand_full["id"]).json()["data"]["chart"]
        self.assertEqual(chart["months"],
                         ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"])

    def test_chart_partial_month_data_leaves_gaps_as_none(self):
        """邊界：只有一個月（3 月）有花費資料，其餘月份沒有——趨勢線該月有值、
        其他月份是 None，不是補成 0（鐵則 16）。"""
        chart = self._get(self.brand_full["id"]).json()["data"]["chart"]
        self.assertEqual(chart["spend"][0], 50)  # 2026-03
        self.assertIsNone(chart["spend"][1])  # 2026-04：完全沒資料
        self.assertIsNone(chart["spend"][2])  # 2026-05：完全沒資料

    def test_kpi_trend_length_matches_chart_months(self):
        data = self._get(self.brand_full["id"]).json()["data"]
        for kpi in data["kpis"].values():
            self.assertEqual(len(kpi["trend"]), len(data["chart"]["months"]))

    # -- 只讀 -----------------------------------------------------------------

    def test_cockpit_endpoint_does_not_write_any_row(self):
        tables = ["brand", "order_record", "performance_snapshot", "derived_metric"]

        def _snapshot():
            return {t: [dict(r) for r in main.conn.execute(f"SELECT * FROM {t} ORDER BY id")]
                    for t in tables}

        before = _snapshot()
        self._get(self.brand_full["id"])
        self._get(self.brand_full["id"])
        after = _snapshot()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
