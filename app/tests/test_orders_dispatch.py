"""app/tests/test_orders_dispatch.py — 訂單票（issue #33）：萬用拖檔口分派層。

驗收條件：拖檔口自動辨識檔案類型並路由到對應解析器（重用既有兩階段欄名比對，只加分派層）。

外殼切片（2026-08-28）：Meta 廣告成效 CSV 那條路徑（自動對期別、跨期拆分、補件重判）
隨 `app/ads/` 一起刪掉，相關案例一併移除；見 `app/orders/dispatch.py` 檔頭。
"""

import io
import unittest

import openpyxl

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.orders import dispatch as orders_dispatch

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
        self.brand = bi_repo.create_brand(web.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_easystore_xlsx_routes_to_order_importer(self):
        result = orders_dispatch.import_dropped_file(
            web.conn, self.bid, filename="Export_Orders.xlsx",
            content=_easystore_xlsx_bytes(), actor=ACTOR)
        self.assertEqual(result.kind, "easystore_orders")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.order_result.orders_imported, 1)

    def test_unrecognisable_file_reports_unknown_kind_honestly(self):
        content = b"foo,bar\n1,2\n"
        result = orders_dispatch.import_dropped_file(
            web.conn, self.bid, filename="mystery.csv", content=content, actor=ACTOR)
        self.assertEqual(result.kind, "unknown")
        self.assertTrue(result.errors)

if __name__ == "__main__":
    unittest.main()
