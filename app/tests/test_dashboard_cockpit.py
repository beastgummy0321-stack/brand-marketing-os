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
os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘：本檔所有日期斷言都以這天為「今天」

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import theme_repository as theme_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import settings as core_settings  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
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


class AlertsFuelPipelineTest(unittest.TestCase):
    """票 05-alerts-fuel-pipeline：異常警示區（直接讀打斷佇列）＋AI 油錢錶（本月已花／
    上限，聚合 llm_task）＋內容產線小計（待審／已發）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構警示茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)

    def _get(self):
        resp = self.client.get(f"/api/dashboard/brands/{self.brand['id']}/cockpit")
        return resp.json()["data"]

    # -- 警示區：直接讀打斷佇列，不另建通知機制 --------------------------------------

    def _insert_interrupt(self, *, severity: str, dedupe_key: str, message: str = "測試警報",
                          action_url=None) -> str:
        """比照 test_dashboard_overview.py：目前尚無類別登記 money_loss／irreversible，
        直接塞一列繞過 enqueue（測試檔豁免跨層寫入掃描）。"""
        interrupt_id = new_id("itr")
        main.conn.execute(
            "INSERT INTO interrupt (id, brand_id, dedupe_key, category, severity, message,"
            " action_url, status, created_at) VALUES (?, ?, ?, 'code_surge_alert', ?, ?, ?,"
            " 'open', ?)",
            (interrupt_id, self.brand["id"], dedupe_key, severity, message, action_url,
             f"{TODAY}T09:00:00"),
        )
        main.conn.commit()
        return interrupt_id

    def test_no_open_alerts_is_empty_list(self):
        """空狀態：前端顯示「一切正常」，API 就回空陣列，不是省略欄位。"""
        self.assertEqual(self._get()["alerts"], [])

    def test_alerts_sorted_by_severity(self):
        self._insert_interrupt(severity="informational", dedupe_key="d-info")
        self._insert_interrupt(severity="money_loss", dedupe_key="d-money")
        self._insert_interrupt(severity="rule_warning", dedupe_key="d-rule")
        self._insert_interrupt(severity="irreversible", dedupe_key="d-irrev")
        severities = [a["severity"] for a in self._get()["alerts"]]
        self.assertEqual(severities,
                         ["money_loss", "irreversible", "rule_warning", "informational"])

    def test_alert_carries_message_and_action_url_for_detail_link(self):
        self._insert_interrupt(severity="money_loss", dedupe_key="d-1",
                               message="測試金額損失", action_url="/some/where")
        alert = self._get()["alerts"][0]
        self.assertEqual(alert["message"], "測試金額損失")
        self.assertEqual(alert["action_url"], "/some/where")

    def test_resolving_interrupt_removes_it_from_cockpit_alerts(self):
        """一鍵「知道了」沿用既有 core_interrupts.resolve()（本測試不動 resolve() 本身
        或它既有的測試斷言，只驗證駕駛艙讀取面確實反映結果）。"""
        interrupt_id = self._insert_interrupt(severity="rule_warning", dedupe_key="d-resolve")
        self.assertEqual(len(self._get()["alerts"]), 1)
        core_interrupts.resolve(main.conn, interrupt_id, actor=ACTOR)
        self.assertEqual(self._get()["alerts"], [])

    # -- AI 油錢錶：本月已花／上限，聚合 llm_task 成本紀錄 ---------------------------

    def _spend(self, cost: float, started_at: str) -> None:
        main.conn.execute(
            "INSERT INTO llm_task (id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, cost, started_at, finished_at)"
            " VALUES (?, ?, 't', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'succeeded', 1, ?, ?, ?)",
            (new_id("llm"), self.brand["id"], cost, started_at, started_at),
        )
        main.conn.commit()

    def test_fuel_gauge_sums_this_months_llm_cost_only(self):
        self._spend(5.0, "2026-07-20T10:00:00")  # 上月，不該算進本月
        self._spend(2.5, "2026-08-01T10:00:00")
        self._spend(1.5, f"{TODAY}T09:00:00")
        gauge = self._get()["fuel_gauge"]
        self.assertAlmostEqual(gauge["spent_this_month"], 4.0)

    def test_fuel_gauge_limit_matches_settings(self):
        core_settings.set_setting(main.conn, core_settings.INTAKE_BUDGET_SETTING, "88")
        gauge = self._get()["fuel_gauge"]
        self.assertEqual(gauge["limit"], 88.0)

    def test_fuel_gauge_zero_spend_is_zero_not_none(self):
        gauge = self._get()["fuel_gauge"]
        self.assertEqual(gauge["spent_this_month"], 0.0)

    # -- 內容產線小計：待審／已發數 ---------------------------------------------------

    def _insert_variant(self, *, status: str) -> None:
        """一顆主題、底下一個元件（票 03-close-repoint-gaps：內容產線小計改讀主題表——
        creative_variant 沒有存活寫入路徑，插那張表讀取層看不到，恆是 0/0）。
        status='APPROVED' 對到主題已採用（published）、'DRAFT' 對到還沒採用（pending），
        比照 theme_repository.count_components_by_adoption() 的口徑。"""
        cycle_id = new_id("ccy")
        ts = f"{TODAY}T00:00:00"
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, budget,"
            " currency, start_date, end_date, channels_json, status, archived, plan_version,"
            " phase, created_at, updated_at) VALUES (?, ?, '[]', 'sales', 5000, 'TWD', ?, ?,"
            " '[\"meta\"]', 'PLANNING', 0, 0, 'normal', ?, ?)",
            (cycle_id, self.brand["id"], TODAY, TODAY, ts, ts),
        )
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)", (cell_id, cycle_id, self.brand["id"], ts))
        theme = theme_repo.create_theme(
            main.conn, self.brand["id"], campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name=f"產線測試{cell_id}", folder_code=cell_id[-4:],
            actor=ACTOR,
            components=[{"component_type": "title", "content": "測試"}],
        )
        if status == "APPROVED":
            theme_repo.adopt_theme(main.conn, self.brand["id"], theme["id"], actor=ACTOR)

    def test_content_pipeline_zero_when_no_variants(self):
        self.assertEqual(self._get()["content_pipeline"], {"pending": 0, "published": 0})

    def test_content_pipeline_counts_pending_and_published(self):
        self._insert_variant(status="DRAFT")
        self._insert_variant(status="DRAFT")
        self._insert_variant(status="APPROVED")
        self.assertEqual(self._get()["content_pipeline"], {"pending": 2, "published": 1})


class LastSyncAtTest(unittest.TestCase):
    """票 07-auto-sync：駕駛艙顯示最後同步時間；超過一天（含從沒同步過）標示
    「數據可能過期」。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構同步茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)

    def _get(self):
        resp = self.client.get(f"/api/dashboard/brands/{self.brand['id']}/cockpit")
        return resp.json()["data"]

    def _insert_snapshot(self, snapshot_taken_at: str) -> None:
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, platform, date_range_start,"
            " date_range_end, as_of_date, snapshot_taken_at, currency, impressions, clicks,"
            " spend, conversions, revenue, reconciled, source, quarantined, created_at)"
            " VALUES (?, ?, 'meta', ?, ?, ?, ?, 'TWD', 0, 0, 0, 0, 0, 1, 'test', 0, ?)",
            (new_id("psn"), self.brand["id"], TODAY, TODAY, TODAY,
             snapshot_taken_at, snapshot_taken_at),
        )
        main.conn.commit()

    def _insert_ga4_sync_status(self, synced_at: str) -> None:
        main.conn.execute(
            "INSERT INTO ga4_sync_status (brand_id, date_range_start, date_range_end, row_count,"
            " purchase_event_seen, synced_at, updated_at) VALUES (?, ?, ?, 0, 1, ?, ?)",
            (self.brand["id"], TODAY, TODAY, synced_at, synced_at),
        )
        main.conn.commit()

    def test_never_synced_is_null_and_stale(self):
        data = self._get()
        self.assertIsNone(data["last_sync_at"])
        self.assertTrue(data["data_stale"])

    def test_synced_today_is_not_stale(self):
        self._insert_snapshot(f"{TODAY}T09:00:00+00:00")
        data = self._get()
        self.assertEqual(data["last_sync_at"], f"{TODAY}T09:00:00+00:00")
        self.assertFalse(data["data_stale"])

    def test_synced_yesterday_is_stale(self):
        self._insert_snapshot("2026-08-04T09:00:00+00:00")
        data = self._get()
        self.assertEqual(data["last_sync_at"], "2026-08-04T09:00:00+00:00")
        self.assertTrue(data["data_stale"])

    def test_ga4_sync_time_counts_too(self):
        self._insert_ga4_sync_status(f"{TODAY}T08:00:00+00:00")
        data = self._get()
        self.assertEqual(data["last_sync_at"], f"{TODAY}T08:00:00+00:00")
        self.assertFalse(data["data_stale"])

    def test_takes_the_later_of_meta_and_ga4(self):
        self._insert_snapshot("2026-08-04T09:00:00+00:00")
        self._insert_ga4_sync_status(f"{TODAY}T08:00:00+00:00")
        data = self._get()
        self.assertEqual(data["last_sync_at"], f"{TODAY}T08:00:00+00:00")
        self.assertFalse(data["data_stale"])


if __name__ == "__main__":
    unittest.main()
