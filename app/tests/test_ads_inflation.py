# -*- coding: utf-8 -*-
"""app/tests/test_ads_inflation.py — 灌水係數＋revenue 反推標記＋對帳頁（GitHub issue #36）。

驗收重點：
1. revenue 來源標記：CSV 反推列標 roas_derived、原始欄位標 reported，既有列回填 unknown。
2. 對帳：Meta 自報 vs 訂單淨歸因並列；沒有訂單資料／沒有配碼時誠實顯示無法對帳。
3. 係數表：帶版本與生效區間；樣本門檻不足前用保守預設；每次校準記上一版的事後誤差。
4. 自適應降頻：連續幾期誤差穩定才降為每季，規則判定、「距今 X 天」正確。
5. 刪期比照 learning_ledger 脫鉤，不隨期刪除。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_inflation_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import app.main as main  # noqa: E402
from app.ads import codes as ads_codes  # noqa: E402
from app.ads import ga4_api  # noqa: E402
from app.ads import ga4_sync  # noqa: E402
from app.ads import inflation as ads_inflation  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import now_iso  # noqa: E402
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


def _order(order_number, order_date, total_amount, voucher_code=None):
    return {
        "order_number": order_number, "order_date": order_date, "total_amount": total_amount,
        "refunded_amount": 0, "financial_status": "paid", "fulfillment_status": "fulfilled",
        "order_status": "paid", "voucher_code": voucher_code,
        "billing_email": f"{order_number}@example.test", "billing_phone": None, "items": [],
    }


class _BaseInflationTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構浪潮飲品{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _cycle(self, start_date, duration_days=7):
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date=start_date, duration_days=duration_days)
        return cycle

    def _with_codes_and_data(self, cycle, *, meta_revenue, order_revenue, spend=1000):
        """一期完整的對帳素材：配碼＋一筆對到廣告碼的訂單＋一筆手動輸入的 Meta 成效。"""
        codes = ads_codes.generate_codes(main.conn, self.bid, cycle["id"], discount_type="percent",
                                         discount_value=10, actor=ACTOR)
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        orders_repo.save_orders(
            main.conn, self.bid,
            [_order(f"O_{cycle['id']}", cycle["start_date"], order_revenue, voucher_code=ad_code)],
            source="easystore_xlsx", actor=ACTOR)
        ads_performance.import_manual(
            main.conn, self.bid, cycle["id"],
            {"spend": spend, "revenue": meta_revenue}, actor=ACTOR, today=cycle["start_date"])
        return cycle


class RevenueSourceTaggingTest(_BaseInflationTest):
    def test_direct_revenue_column_is_tagged_reported(self):
        cycle = self._cycle("2026-06-01")
        csv_text = "行銷活動名稱,花費金額,購買轉換價值\n虛構檔期,1000,5000\n"
        ads_performance.import_csv(main.conn, self.bid, cycle["id"], csv_text, actor=ACTOR)
        row = ads_performance.list_snapshots(main.conn, self.bid, cycle["id"])[0]
        self.assertEqual(row["revenue_source"], "reported")

    def test_roas_derived_revenue_is_tagged_roas_derived(self):
        cycle = self._cycle("2026-06-01")
        csv_text = "行銷活動名稱,花費金額,成果 ROAS\n虛構檔期,1000,1.5\n"
        ads_performance.import_csv(main.conn, self.bid, cycle["id"], csv_text, actor=ACTOR)
        row = ads_performance.list_snapshots(main.conn, self.bid, cycle["id"])[0]
        self.assertEqual(row["revenue_source"], "roas_derived")
        self.assertAlmostEqual(row["revenue"], 1500.0)

    def test_missing_revenue_has_no_source(self):
        cycle = self._cycle("2026-06-01")
        csv_text = "行銷活動名稱,花費金額\n虛構檔期,1000\n"
        ads_performance.import_csv(main.conn, self.bid, cycle["id"], csv_text, actor=ACTOR)
        row = ads_performance.list_snapshots(main.conn, self.bid, cycle["id"])[0]
        self.assertIsNone(row["revenue_source"])

    def test_revenue_by_source_breaks_down_the_totals(self):
        cycle = self._cycle("2026-06-01")
        ads_performance.import_csv(
            main.conn, self.bid, cycle["id"],
            "行銷活動名稱,花費金額,購買轉換價值\n甲,1000,5000\n", actor=ACTOR)
        ads_performance.import_csv(
            main.conn, self.bid, cycle["id"],
            "行銷活動名稱,花費金額,成果 ROAS\n乙,1000,1.5\n", actor=ACTOR)
        breakdown = ads_performance.revenue_by_source(main.conn, self.bid, cycle["id"])
        self.assertEqual(breakdown["reported"], 5000)
        self.assertEqual(breakdown["roas_derived"], 1500)
        self.assertEqual(breakdown["total"], 6500)

    def test_migration_backfill_marks_existing_rows_unknown(self):
        """既有列（revenue 已入庫、revenue_source 為 NULL）回填規則：標 unknown（見 migration
        0010 註解——當初沒存 raw_json，事後無法分辨原始欄位還是反推值，誠實標不知道）。"""
        cycle = self._cycle("2026-06-01")
        # 模擬「migration 套用前」的舊資料：直接繞過 import_rows 插入沒有 revenue_source 的列。
        from app.core.db import new_id
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, platform,"
            " date_range_start, date_range_end, as_of_date, snapshot_taken_at, currency,"
            " spend, revenue, revenue_source, reconciled, source, quarantined, created_at)"
            " VALUES (?, ?, ?, 'meta', '2026-06-01', '2026-06-01', '2026-06-01', ?, 'TWD',"
            " 1000, 3000, NULL, 1, 'csv', 0, ?)",
            (new_id("psn"), self.bid, cycle["id"], ts, ts),
        )
        main.conn.execute(
            "UPDATE performance_snapshot SET revenue_source = 'unknown'"
            " WHERE revenue IS NOT NULL AND revenue_source IS NULL"
        )
        main.conn.commit()
        row = ads_performance.list_snapshots(main.conn, self.bid, cycle["id"])[0]
        self.assertEqual(row["revenue_source"], "unknown")


class ReconcileCycleTest(_BaseInflationTest):
    def test_no_orders_at_all_is_honestly_unreconcilable(self):
        cycle = self._cycle("2026-06-01")
        ads_codes.generate_codes(main.conn, self.bid, cycle["id"], discount_type="percent",
                                 discount_value=10, actor=ACTOR)
        ads_performance.import_manual(main.conn, self.bid, cycle["id"],
                                      {"spend": 1000, "revenue": 3000}, actor=ACTOR)
        result = ads_inflation.reconcile_cycle(main.conn, self.bid, cycle["id"])
        self.assertFalse(result["available"])
        self.assertIn("沒有訂單資料", result["reason"])

    def test_no_ad_code_is_honestly_unreconcilable(self):
        cycle = self._cycle("2026-06-01")
        orders_repo.save_orders(main.conn, self.bid,
                                [_order("O1", "2026-06-01", 1000)],
                                source="easystore_xlsx", actor=ACTOR)
        result = ads_inflation.reconcile_cycle(main.conn, self.bid, cycle["id"])
        self.assertFalse(result["available"])
        self.assertIn("沒有配廣告碼", result["reason"])

    def test_reconciles_meta_vs_net_attributed_order_revenue(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01"), meta_revenue=1000, order_revenue=1200)
        result = ads_inflation.reconcile_cycle(main.conn, self.bid, cycle["id"])
        self.assertTrue(result["available"])
        self.assertEqual(result["meta_revenue"], 1000)
        self.assertEqual(result["order_revenue"], 1200)
        self.assertAlmostEqual(result["coefficient_now"], 1.2)


class CalibrationTest(_BaseInflationTest):
    def test_first_calibration_is_not_reliable_below_sample_threshold(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01"), meta_revenue=1000, order_revenue=1000)
        result = ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["sample_size"], 1)
        self.assertFalse(result["reliable"])

        effective = ads_inflation.effective_coefficient(main.conn, self.bid)
        self.assertFalse(effective["reliable"])
        self.assertEqual(effective["coefficient"], ads_inflation.DEFAULT_COEFFICIENT)
        self.assertIn("不可靠", effective["note"])

    def test_reaching_threshold_makes_it_reliable_and_logs_ex_post_error(self):
        for i in range(ads_inflation.SAMPLE_THRESHOLD):
            cycle = self._with_codes_and_data(
                self._cycle(f"2026-0{6 + i}-01"), meta_revenue=1000, order_revenue=1000)
            ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR)

        effective = ads_inflation.effective_coefficient(main.conn, self.bid)
        self.assertTrue(effective["reliable"])
        self.assertEqual(effective["sample_size"], ads_inflation.SAMPLE_THRESHOLD)
        self.assertEqual(effective["coefficient"], 1.0)

        # 累積校準次數 - 1 筆事後誤差紀錄（第一次校準沒有「上一版」可比對）
        errors = main.conn.execute(
            "SELECT error_pct FROM ad_revenue_coefficient_error_log WHERE brand_id = ?",
            (self.bid,)).fetchall()
        self.assertEqual(len(errors), ads_inflation.SAMPLE_THRESHOLD - 1)
        for row in errors:
            self.assertAlmostEqual(row["error_pct"], 0.0)

    def test_previous_version_gets_valid_to_closed(self):
        cycle1 = self._with_codes_and_data(
            self._cycle("2026-06-01"), meta_revenue=1000, order_revenue=1000)
        ads_inflation.calibrate(main.conn, self.bid, cycle1["id"], actor=ACTOR)
        v1 = ads_inflation.latest_coefficient(main.conn, self.bid)
        self.assertIsNone(v1["valid_to"])

        cycle2 = self._with_codes_and_data(
            self._cycle("2026-07-01"), meta_revenue=1000, order_revenue=1300)
        ads_inflation.calibrate(main.conn, self.bid, cycle2["id"], actor=ACTOR)
        v1_after = main.conn.execute(
            "SELECT * FROM ad_revenue_coefficient WHERE id = ?", (v1["id"],)).fetchone()
        self.assertIsNotNone(v1_after["valid_to"])
        v2 = ads_inflation.latest_coefficient(main.conn, self.bid)
        self.assertEqual(v2["version"], 2)
        self.assertAlmostEqual(v2["coefficient"], 1.3)

    def test_calibrate_without_meta_revenue_refuses(self):
        cycle = self._cycle("2026-06-01")
        ads_codes.generate_codes(main.conn, self.bid, cycle["id"], discount_type="percent",
                                 discount_value=10, actor=ACTOR)
        orders_repo.save_orders(main.conn, self.bid,
                                [_order("O1", "2026-06-01", 1000,
                                       voucher_code=ads_codes.list_codes(
                                           main.conn, self.bid, cycle["id"])[0]["code"])],
                                source="easystore_xlsx", actor=ACTOR)
        with self.assertRaises(ValueError):
            ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR)


class CadenceTest(_BaseInflationTest):
    def test_no_calibration_yet_defaults_to_per_cycle_and_due(self):
        state = ads_inflation.cadence_state(main.conn, self.bid, today="2026-06-01")
        self.assertEqual(state["cadence"], "per_cycle")
        self.assertTrue(state["due"])
        self.assertIsNone(state["days_since_last"])
        self.assertEqual(state["confidence_label"], "尚未校準")

    def test_stable_errors_downgrade_to_quarterly(self):
        """連續 STABILITY_WINDOW 次事後誤差都在容忍範圍內才降頻——規則判定，非 LLM。"""
        months = ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]
        for start in months:
            cycle = self._with_codes_and_data(
                self._cycle(start), meta_revenue=1000, order_revenue=1000)
            ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR, today=start)

        state = ads_inflation.cadence_state(main.conn, self.bid, today="2026-09-05")
        self.assertEqual(state["cadence"], "quarterly")
        self.assertEqual(state["days_since_last"], 4)
        self.assertFalse(state["due"])  # 才過 4 天，離每季門檻還早

        far_future = ads_inflation.cadence_state(main.conn, self.bid, today="2027-01-01")
        self.assertTrue(far_future["due"])

    def test_unstable_errors_stay_per_cycle(self):
        cycle1 = self._with_codes_and_data(
            self._cycle("2026-06-01"), meta_revenue=1000, order_revenue=1000)
        ads_inflation.calibrate(main.conn, self.bid, cycle1["id"], actor=ACTOR, today="2026-06-01")
        cycle2 = self._with_codes_and_data(
            self._cycle("2026-07-01"), meta_revenue=1000, order_revenue=5000)  # 誤差極大
        ads_inflation.calibrate(main.conn, self.bid, cycle2["id"], actor=ACTOR, today="2026-07-01")

        state = ads_inflation.cadence_state(main.conn, self.bid, today="2026-07-05")
        self.assertEqual(state["cadence"], "per_cycle")
        self.assertTrue(state["due"])

    def test_downgrade_to_quarterly_enqueues_a_future_reminder(self):
        months = ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]
        for start in months:
            cycle = self._with_codes_and_data(
                self._cycle(start), meta_revenue=1000, order_revenue=1000)
            ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR, today=start)

        row = main.conn.execute(
            "SELECT * FROM interrupt WHERE brand_id = ? AND category = 'revenue_reconcile_due'",
            (self.bid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["severity"], "informational")


class DataGradeTest(_BaseInflationTest):
    """成色標籤（GitHub issue #41，決策 0025 懶人優先第 6 點）：資料完整度決定成色，
    永遠給結論、永不擋路。"""

    def test_uncalibrated_brand_defaults_to_meta_only(self):
        grade = ads_inflation.data_grade(main.conn, self.bid)
        self.assertEqual(grade["kind"], "meta_only")
        self.assertEqual(grade["label"], "Meta 視角判讀")

    def test_reaching_sample_threshold_upgrades_to_calibrated(self):
        for i in range(ads_inflation.SAMPLE_THRESHOLD):
            cycle = self._with_codes_and_data(
                self._cycle(f"2026-0{6 + i}-01"), meta_revenue=1000, order_revenue=1000)
            ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR)

        grade = ads_inflation.data_grade(main.conn, self.bid)
        self.assertEqual(grade["kind"], "calibrated")
        # 修憲落地 G5（決策 0035 第四節第 11 點）：這裡曾經斷言 "已校準判讀"，但灌水係數
        # 從未真的乘進 judge() 用的 revenue（只有對帳頁引用），標籤描述了一個沒發生的
        # 校準。改名為「已對過帳（數字未調整）」誠實反映實際算術，不再假裝有校準。
        self.assertEqual(grade["label"], "已對過帳（數字未調整）")
        self.assertNotEqual(grade["label"], "已校準判讀")


class GA4LeakEstimateTest(_BaseInflationTest):
    """GA4 漏率反偵測（GitHub issue #41，決策 0025 小補丁組第 5 點）：用「有廣告碼但
    GA4 對不到」的訂單比例估 GA4 自身流失，避免全算成 Meta 灌水。"""

    PROPERTY_ID = "123456789"
    FAKE_KEY_JSON = '{"client_email": "svc@example.iam.gserviceaccount.com"}'

    def _configure_ga4(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, self.PROPERTY_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, self.FAKE_KEY_JSON)

    def _sync_ga4(self, conversions, since, until):
        self._configure_ga4()
        client = ga4_api.FakeGA4Client(
            rows=[ga4_api.SourceMediumRow(source="google", medium="cpc", sessions=100,
                                          conversions=conversions, revenue=5000.0)],
            purchase_seen=True)
        ga4_sync.sync_brand(main.conn, self.bid, ACTOR, client=client, since=since, until=until,
                            today=until)

    def test_no_ad_code_orders_says_so_honestly(self):
        cycle = self._cycle("2026-06-01", duration_days=7)
        result = ads_inflation.ga4_leak_estimate(main.conn, self.bid, cycle)
        self.assertFalse(result["available"])
        self.assertIn("沒有訂單用到廣告碼", result["reason"])

    def test_no_ga4_sync_says_so_honestly(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01", duration_days=7), meta_revenue=1000, order_revenue=1000)
        result = ads_inflation.ga4_leak_estimate(main.conn, self.bid, cycle)
        self.assertFalse(result["available"])
        self.assertIn("還沒同步過 GA4", result["reason"])

    def test_ga4_range_not_covering_cycle_says_so_honestly(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01", duration_days=7), meta_revenue=1000, order_revenue=1000)
        self._sync_ga4(conversions=1.0, since="2026-07-01", until="2026-07-31")
        result = ads_inflation.ga4_leak_estimate(main.conn, self.bid, cycle)
        self.assertFalse(result["available"])
        self.assertIn("沒有完整涵蓋", result["reason"])

    def test_leak_ratio_computed_when_ga4_undercounts_known_orders(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01", duration_days=7), meta_revenue=1000, order_revenue=1000)
        self._sync_ga4(conversions=0.0, since="2026-06-01", until="2026-06-07")
        result = ads_inflation.ga4_leak_estimate(main.conn, self.bid, cycle)
        self.assertTrue(result["available"])
        self.assertEqual(result["order_count"], 1)
        self.assertEqual(result["ga4_conversions"], 0.0)
        self.assertEqual(result["leak_ratio"], 1.0)
        self.assertIn("GA4 自己沒追蹤到", result["note"])
        self.assertIn("不是 Meta 灌水", result["note"])

    def test_leak_ratio_is_zero_when_ga4_matches_or_exceeds_orders(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01", duration_days=7), meta_revenue=1000, order_revenue=1000)
        self._sync_ga4(conversions=5.0, since="2026-06-01", until="2026-06-07")
        result = ads_inflation.ga4_leak_estimate(main.conn, self.bid, cycle)
        self.assertTrue(result["available"])
        self.assertEqual(result["leak_ratio"], 0.0)


class CascadeTest(_BaseInflationTest):
    def test_deleting_cycle_only_detaches_coefficient_history(self):
        cycle = self._with_codes_and_data(
            self._cycle("2026-06-01"), meta_revenue=1000, order_revenue=1000)
        result = ads_inflation.calibrate(main.conn, self.bid, cycle["id"], actor=ACTOR)

        ads_repo.set_cycle_archived(main.conn, self.bid, cycle["id"], archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, cycle["id"], actor=ACTOR)

        row = main.conn.execute(
            "SELECT * FROM ad_revenue_coefficient WHERE id = ?", (result["id"],)).fetchone()
        self.assertIsNotNone(row, "灌水係數比照 learning_ledger 脫鉤，不隨檔期刪除")
        self.assertIsNone(row["source_cycle_id"])


if __name__ == "__main__":
    unittest.main()
