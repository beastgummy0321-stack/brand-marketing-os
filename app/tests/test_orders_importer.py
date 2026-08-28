"""app/tests/test_orders_importer.py — 訂單票（issue #33）：EasyStore xlsx 解析＋分派層。

表頭沿用 DoR 附的 EasyStore 欄位實況：Order Number/Date/Total Amount/Refunded Amount/
Financial Status/Fulfillment Status/Order Status/Voucher Code/Billing Email/
Billing Phone/Item SKU/Item Price/Quantity（一單多商品列，訂單層欄位只在首列）。
"""

import io
import unittest

import openpyxl

from app.orders import importer

EASYSTORE_HEADERS = [
    "Order Number", "Date", "Total Amount", "Refunded Amount", "Financial Status",
    "Fulfillment Status", "Order Status", "Voucher Code", "Billing Email",
    "Billing Phone", "Item SKU", "Item Price", "Quantity",
]


def _build_xlsx(rows: list) -> bytes:
    """rows：每列是 EASYSTORE_HEADERS 對應順序的 list（表頭列不用附，這裡自動加）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EASYSTORE_HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 一張兩品項訂單（虛構品牌「晨光茶行」樣本資料）
_TWO_ITEM_ORDER = [
    ["ORD1001", "2026-06-01", 1200, 0, "paid", "fulfilled", "completed", "ADCODE1",
     "buyer@example.com", "0912345678", "SKU-A", 500, 2],
    [None, None, None, None, None, None, None, None, None, None, "SKU-B", 200, 1],
]


class ParseEasyStoreXlsxTest(unittest.TestCase):
    def test_groups_multi_item_rows_under_one_order(self):
        rows, result = importer.parse_easystore_xlsx(_build_xlsx(_TWO_ITEM_ORDER))
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 1)
        order = rows[0]
        self.assertEqual(order["order_number"], "ORD1001")
        self.assertEqual(order["total_amount"], 1200)
        self.assertEqual(order["billing_email"], "buyer@example.com")
        self.assertEqual(len(order["items"]), 2)
        self.assertEqual(order["items"][0]["sku"], "SKU-A")
        self.assertEqual(order["items"][0]["quantity"], 2)
        self.assertEqual(order["items"][1]["sku"], "SKU-B")

    def test_groups_multi_item_rows_when_order_number_filled_on_every_row(self):
        """真實 EasyStore 匯出檔的實況（不是 fixture 假設）：Order Number 每一列都有填，
        不是只有首列——分組靠「連續同號」，不是靠留白。"""
        rows_data = [
            ["ORD2001", "2026-06-03", 900, 0, "paid", "fulfilled", "completed", None,
             "buyer2@example.com", "0911111111", "SKU-X", 400, 1],
            ["ORD2001", "2026-06-03", 900, 0, "paid", "fulfilled", "completed", None,
             "buyer2@example.com", "0911111111", "SKU-Y", 500, 1],
            ["ORD2002", "2026-06-04", 250, 0, "paid", "unfulfilled", "processing", None,
             "buyer3@example.com", "0922222222", "SKU-Z", 250, 1],
        ]
        rows, result = importer.parse_easystore_xlsx(_build_xlsx(rows_data))
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["order_number"], "ORD2001")
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(first["items"][0]["sku"], "SKU-X")
        self.assertEqual(first["items"][1]["sku"], "SKU-Y")
        self.assertEqual(rows[1]["order_number"], "ORD2002")
        self.assertEqual(len(rows[1]["items"]), 1)

    def test_multiple_orders_do_not_bleed_into_each_other(self):
        rows_data = _TWO_ITEM_ORDER + [
            ["ORD1002", "2026-06-02", 300, 0, "paid", "unfulfilled", "processing", None,
             None, "0987654321", "SKU-C", 300, 1],
        ]
        rows, result = importer.parse_easystore_xlsx(_build_xlsx(rows_data))
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["order_number"], "ORD1002")
        self.assertIsNone(rows[1]["billing_email"])
        self.assertEqual(rows[1]["billing_phone"], "0987654321")

    def test_missing_order_number_column_errors_out(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Random Column", "Another"])
        ws.append(["a", "b"])
        buf = io.BytesIO()
        wb.save(buf)
        rows, result = importer.parse_easystore_xlsx(buf.getvalue())
        self.assertEqual(rows, [])
        self.assertTrue(result.errors)

    def test_empty_file_errors_out(self):
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        rows, result = importer.parse_easystore_xlsx(buf.getvalue())
        self.assertEqual(rows, [])
        self.assertTrue(result.errors)


class SniffFileKindTest(unittest.TestCase):
    def test_easystore_headers_detected(self):
        self.assertTrue(importer.looks_like_easystore_orders(EASYSTORE_HEADERS))
        self.assertEqual(importer.sniff_file_kind("Export_Orders.xlsx", EASYSTORE_HEADERS),
                         "easystore_orders")

    def test_meta_headers_are_no_longer_a_known_kind(self):
        """外殼切片（2026-08-28）：Meta 成效 CSV 那條匯入路徑隨 `app/ads/` 一起刪掉，
        拖進來只會誠實回 unknown，不假裝認得。"""
        meta_headers = ["Reporting starts", "Reporting ends", "Campaign name", "Amount spent (TWD)"]
        self.assertEqual(importer.sniff_file_kind("meta_export.csv", meta_headers), "unknown")

    def test_unrecognised_headers_are_unknown(self):
        self.assertEqual(importer.sniff_file_kind("mystery.csv", ["foo", "bar"]), "unknown")

    def test_reuses_two_phase_match_columns_algorithm(self):
        """分派層只加別名表，兩階段比對演算法是同一份（app.shared.csv_columns.match_columns）：
        「成果」類前綴截胡的既有防線（issue #23 bug 1）套用同一組規則也該對訂單欄位生效。"""
        mapping, unmatched = importer.match_order_columns(EASYSTORE_HEADERS)
        self.assertEqual(mapping["order_number"], "Order Number")
        self.assertEqual(mapping["item_sku"], "Item SKU")
        self.assertEqual(unmatched, [])


if __name__ == "__main__":
    unittest.main()
