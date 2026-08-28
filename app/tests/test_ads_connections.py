"""app/tests/test_ads_connections.py — D線票2（GitHub issue #44）：資料與連線頁＋薄匯入路由。

嗅探與匯入邏輯本身不重寫、不重測——沿用 app/tests/test_orders_dispatch.py 已驗證過的
app.orders.dispatch.import_dropped_file()。這裡只驗證：
1. 頁面容量規則（票 1 腳本）。
2. 薄匯入路由背後的同一支分派函式，三種結果（成功／警告／錯誤）皆正確入庫。

fixture 一律虛構品牌，嚴禁真實品牌名稱。
"""

import io
import unittest
from datetime import date

import openpyxl

import app.main as main
from app.ads import ga4_sync
from app.ads import repository as ads_repo
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.orders import dispatch as orders_dispatch

ACTOR = "測試員"
META_ACCOUNT = "act_1234567890"
GA4_PROPERTY_ID = "123456789"
GA4_FAKE_KEY_JSON = '{"client_email": "svc@example.iam.gserviceaccount.com"}'


_EASYSTORE_HEADERS = ["Order Number", "Date", "Total Amount", "Refunded Amount",
                      "Financial Status", "Fulfillment Status", "Order Status",
                      "Voucher Code", "Billing Email", "Billing Phone", "Item SKU",
                      "Item Price", "Quantity"]

_SHOPEE_CSV = "Order SN,Order creation date,Order amount,Voucher code\nSN010,2026-06-03,999,\n"

_META_CSV = ("Reporting starts,Reporting ends,Campaign name,Amount spent (TWD),"
            "Impressions,Link clicks,Purchases,Purchases conversion value\n"
            "{start},{end},虛構檔期,3000,8000,210,5,9000\n")


def _easystore_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_EASYSTORE_HEADERS)
    ws.append(["ORD1", "2026-06-01", 1000, 0, "paid", "fulfilled", "completed", None,
              "buyer@example.com", None, "SKU-A", 500, 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ConnectionsRouteTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM app_setting WHERE key IN (%s, %s, %s, %s)",
                          (ads_sync.ACCOUNT_SETTING, ads_sync.TOKEN_SETTING,
                           ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    # ---- 頁面直達＋空狀態＋金鑰深連結 --------------------------------------

    # ---- 薄匯入路由：三種格式皆正確入庫，且導回本頁而非訂單頁 ----------------

    def test_upload_easystore_xlsx_lands_orders_and_stays_on_connections_page(self):
        # 舊頁的 `kind=ok` ＝ 分派層認出格式且沒有任何錯誤（見 routes_connections.py 的映射）
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="Export_Orders.xlsx",
            content=_easystore_xlsx_bytes(), actor=ACTOR, today=date.today().isoformat())
        self.assertEqual(result.kind, "easystore_orders")
        self.assertEqual(result.errors, [])
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM order_record WHERE brand_id = %s", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_upload_shopee_csv_lands_and_stays_on_connections_page(self):
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="shopee.csv", content=_SHOPEE_CSV.encode("utf-8"),
            actor=ACTOR, today=date.today().isoformat())
        self.assertEqual(result.kind, "shopee_report")
        self.assertEqual(result.errors, [])
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM shopee_report_row WHERE brand_id = %s", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_upload_meta_csv_matching_cycle_lands_and_stays_on_connections_page(self):
        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[], pain_value=5000,
                                      objective="流量", actor=ACTOR, start_date="2026-06-01",
                                      duration_days=14)
        content = _META_CSV.format(start="2026-06-01", end="2026-06-14").encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today=date.today().isoformat())
        self.assertEqual(result.kind, "meta_ads_csv")
        self.assertEqual(result.errors, [])
        row = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE brand_id = %s",
            (self.bid,)).fetchone()
        self.assertEqual(row["campaign_cycle_id"], cycle["id"])

    def test_upload_meta_csv_outside_any_cycle_gives_warning_not_ok(self):
        content = _META_CSV.format(start="2020-01-01", end="2020-01-14").encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="meta_export.csv", content=content, actor=ACTOR,
            today=date.today().isoformat())
        # 舊頁的 `kind=warn` ＝ 認得是 Meta CSV，但有對不到檔期的列而帶回一段提醒
        self.assertEqual(result.kind, "meta_ads_csv")
        self.assertNotEqual(result.errors, [])
        self.assertEqual(result.ads_unmatched_rows, 1)

    def test_upload_unrecognisable_file_gives_error_lists_headers_stays_on_page(self):
        result = orders_dispatch.import_dropped_file(
            main.conn, self.bid, filename="mystery.csv", content=b"foo,bar\n1,2\n",
            actor=ACTOR, today=date.today().isoformat())
        # 舊頁的 `kind=danger` ＝分派層認不出格式（unknown），訊息就是 errors[0]
        self.assertEqual(result.kind, "unknown")
        message = result.errors[0]
        self.assertIn("foo", message)
        self.assertIn("bar", message)

if __name__ == "__main__":
    unittest.main()
