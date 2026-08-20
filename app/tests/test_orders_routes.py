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

import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402



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
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

if __name__ == "__main__":
    unittest.main()
