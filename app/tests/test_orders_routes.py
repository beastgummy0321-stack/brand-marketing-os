# -*- coding: utf-8 -*-
"""app/tests/test_orders_routes.py — 訂單票（issue #33）：頁面路由與拖檔口上傳端到端。"""

import atexit
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_orders_routes_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402

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


def _easystore_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_EASYSTORE_HEADERS)
    ws.append(["ORD1", "2026-06-01", 1000, 0, "paid", "fulfilled", "completed", None,
              "buyer@example.com", None, "SKU-A", 500, 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class OrdersRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                         follow_redirects=False)
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_orders_home_page_renders_with_no_history(self):
        resp = self.client.get(f"/brands/{self.bid}/orders")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("累積中", resp.text)

    def test_upload_easystore_xlsx_lands_orders_in_db(self):
        resp = self.client.post(
            f"/brands/{self.bid}/orders/import",
            files={"drop_file": ("Export_Orders.xlsx", _easystore_xlsx_bytes(),
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("kind=ok", resp.headers["location"])
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM order_record WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)

        # 匯完之後首頁看得到剛剛的訂單，統計卡不再顯示「累積中」的空狀態
        page = self.client.get(f"/brands/{self.bid}/orders")
        self.assertIn("ORD1", page.text)

    def test_upload_unrecognisable_file_gives_honest_warning_not_a_500(self):
        resp = self.client.post(
            f"/brands/{self.bid}/orders/import",
            files={"drop_file": ("mystery.csv", b"foo,bar\n1,2\n", "text/csv")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("kind=warn", resp.headers["location"])

    def test_sku_cost_form_rejects_non_numeric_input(self):
        resp = self.client.post(
            f"/brands/{self.bid}/orders/sku-cost",
            data={"sku": "SKU-A", "unit_cost": "abc"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("kind=warn", resp.headers["location"])


if __name__ == "__main__":
    unittest.main()
