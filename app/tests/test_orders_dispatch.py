# -*- coding: utf-8 -*-
"""app/tests/test_orders_dispatch.py — 訂單票（issue #33）：萬用拖檔口分派層。

驗收條件：拖檔口自動辨識檔案類型並路由到對應解析器（重用既有兩階段欄名比對，只加分派層）。
"""

import atexit
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_orders_dispatch_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import openpyxl  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.orders import dispatch as orders_dispatch  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"

_EASYSTORE_HEADERS = ["Order Number", "Date", "Total Amount", "Refunded Amount",
                      "Financial Status", "Fulfillment Status", "Order Status",
                      "Voucher Code", "Billing Email", "Billing Phone", "Item SKU",
                      "Item Price", "Quantity"]


def _easystore_xlsx_bytes(order_number="ORD1", order_date="2026-06-01"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_EASYSTORE_HEADERS)
    ws.append([order_number, order_date, 1000, 0, "paid", "fulfilled", "completed", None,
              "buyer@example.com", None, "SKU-A", 500, 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_META_CSV = ("Reporting starts,Reporting ends,Campaign name,Amount spent (TWD),"
            "Impressions,Link clicks,Purchases,Purchases conversion value\n"
            "{start},{end},虛構檔期,3000,8000,210,5,9000\n")


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_easystore_xlsx_routes_to_order_importer(self):
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="Export_Orders.xlsx",
            content=_easystore_xlsx_bytes(), actor=ACTOR)
        self.assertEqual(result.kind, "easystore_orders")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.order_result.orders_imported, 1)

    def test_unrecognisable_file_reports_unknown_kind_honestly(self):
        content = "foo,bar\n1,2\n".encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="mystery.csv", content=content, actor=ACTOR)
        self.assertEqual(result.kind, "unknown")
        self.assertTrue(result.errors)

    def test_meta_csv_auto_matches_to_overlapping_cycle(self):
        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[], pain_value=5000,
                                      objective="流量", actor=ACTOR, start_date="2026-06-01",
                                      duration_days=14)
        content = _META_CSV.format(start="2026-06-01", end="2026-06-14").encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        self.assertEqual(result.kind, "meta_ads_csv")
        self.assertEqual(result.ads_imported, 1)
        self.assertEqual(result.ads_unmatched_rows, 0)
        row = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE brand_id = ?",
            (self.bid,)).fetchone()
        self.assertEqual(row["campaign_cycle_id"], cycle["id"])

    def test_meta_csv_row_outside_any_cycle_becomes_brand_level_history(self):
        """決策 0039 第 7 條：對不到檔期的舊廣告列不再整批丟棄，轉品牌層
        （campaign_cycle_id=NULL），並誠實回報「已入品牌層歷史」而非「沒有匯入」。"""
        content = _META_CSV.format(start="2020-01-01", end="2020-01-14").encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        self.assertEqual(result.kind, "meta_ads_csv")
        self.assertEqual(result.ads_imported, 1)
        self.assertEqual(result.ads_unmatched_rows, 1)
        self.assertTrue(result.errors)
        self.assertIn("已入品牌層歷史", result.errors[0])
        row = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE brand_id = ?",
            (self.bid,)).fetchone()
        self.assertIsNone(row["campaign_cycle_id"])

    def test_same_brand_level_meta_csv_dropped_twice_does_not_double_count(self):
        """票 F9（GitHub #68，F8 破壞者 Persona 發現）：同一份品牌層歷史 CSV 拖進拖檔口
        兩次，第二次不能再靜默疊加樣本數，且要誠實列出略過幾列。"""
        content = _META_CSV.format(start="2020-01-01", end="2020-01-14").encode("utf-8")
        orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        self.assertEqual(result.ads_imported, 0)
        self.assertIn("略過", result.errors[0])
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = ?"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchone()["c"]
        self.assertEqual(count, 1)


class LateDataRerunDispatchTest(unittest.TestCase):
    """票 #38：晚到檔案丟拖檔口自動觸發受影響期別的補件重判（決策 0025 懶人優先第 3 點）。"""

    def setUp(self):
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[], pain_value=5000,
                                           objective="流量", actor=ACTOR, start_date="2026-06-01",
                                           duration_days=14)
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text='{"text": "測試判讀說明"}', structured=None,
            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn"))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def test_late_meta_csv_on_an_already_evaluated_cycle_triggers_a_rerun(self):
        content = _META_CSV.format(start="2026-06-01", end="2026-06-14").encode("utf-8")
        orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta1.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        ok, err = reading.run(main.conn, self.bid, self.cycle["id"], ACTOR)
        self.assertTrue(ok, err)

        late_csv = ("Reporting starts,Reporting ends,Campaign name,Amount spent (TWD),"
                   "Impressions,Link clicks,Purchases,Purchases conversion value\n"
                   "2026-06-01,2026-06-14,虛構檔期,9000,500,5,0,0\n").encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta2.csv", content=late_csv, actor=ACTOR,
            today="2026-06-20")
        self.assertTrue(result.late_reruns)

        version_count = main.conn.execute(
            "SELECT COUNT(*) c FROM settlement_version WHERE campaign_cycle_id = ?",
            (self.cycle["id"],)).fetchone()["c"]
        self.assertEqual(version_count, 2)

    def test_easystore_orders_landing_inside_an_evaluated_cycle_triggers_a_rerun(self):
        content = _META_CSV.format(start="2026-06-01", end="2026-06-14").encode("utf-8")
        orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta1.csv", content=content, actor=ACTOR,
            today="2026-06-15")
        ok, err = reading.run(main.conn, self.bid, self.cycle["id"], ACTOR)
        self.assertTrue(ok, err)

        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="Export_Orders.xlsx",
            content=_easystore_xlsx_bytes(order_date="2026-06-05"), actor=ACTOR)
        self.assertEqual(result.kind, "easystore_orders")
        self.assertTrue(result.late_reruns)

        version_count = main.conn.execute(
            "SELECT COUNT(*) c FROM settlement_version WHERE campaign_cycle_id = ?",
            (self.cycle["id"],)).fetchone()["c"]
        self.assertEqual(version_count, 2)


if __name__ == "__main__":
    unittest.main()
