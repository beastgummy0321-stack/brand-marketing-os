"""app/tests/test_orders_channel.py — 通路對照卡（GitHub issue #40，決策 0025 第二節 B）。

驗收重點：
1. 蝦皮檔解析＋藥局批次表單；全部選填。
2. 藥局補貨間隔訊號：資料不足時誠實說不知道，間隔縮短才標記。

外殼切片（2026-08-28）：燈號規則、灰燈債務、蝦皮期別碼、判讀整合四組測試隨
`app/ads/` 一起刪掉——它們的主體（檔期、判讀）不存在了，見 `app/orders/channel.py` 檔頭。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch

ACTOR = "測試員"



_SHOPEE_CSV_HEADER = "Order SN,Order creation date,Order amount,Voucher code\n"


def _shopee_csv(rows):
    body = "".join(f"{sn},{d},{amt},{code or ''}\n" for sn, d, amt, code in rows)
    return _SHOPEE_CSV_HEADER + body


class _BaseChannelTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構晨露茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(web.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]


class ParseShopeeCsvTest(_BaseChannelTest):
    def test_parses_rows_and_matches_columns_by_meaning(self):
        text = _shopee_csv([("SN001", "2026-06-02", "500", "SHOPXX"),
                            ("SN002", "2026-06-05", "300", None)])
        rows, result = orders_channel.parse_shopee_csv(text)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["order_sn"], "SN001")
        self.assertEqual(rows[0]["revenue"], 500.0)
        self.assertEqual(rows[0]["voucher_code"], "SHOPXX")

    def test_missing_order_sn_column_reports_honestly(self):
        rows, result = orders_channel.parse_shopee_csv("foo,bar\n1,2\n")
        self.assertEqual(rows, [])
        self.assertTrue(result.errors)

    def test_empty_file_reports_honestly(self):
        rows, result = orders_channel.parse_shopee_csv("")
        self.assertEqual(rows, [])
        self.assertTrue(result.errors)


class SniffTest(_BaseChannelTest):
    def test_shopee_headers_are_recognised(self):
        self.assertTrue(orders_channel.looks_like_shopee_report(
            ["Order SN", "Order creation date", "Order amount"]))

    def test_easystore_headers_are_not_mistaken_for_shopee(self):
        self.assertFalse(orders_channel.looks_like_shopee_report(
            ["Order Number", "Date", "Total Amount"]))

    def test_meta_ads_headers_are_not_mistaken_for_shopee(self):
        self.assertFalse(orders_channel.looks_like_shopee_report(
            ["Reporting starts", "Amount spent (TWD)", "Impressions"]))


class SaveShopeeRowsTest(_BaseChannelTest):
    def test_reimporting_same_order_sn_overwrites_not_duplicates(self):
        rows1, _ = orders_channel.parse_shopee_csv(
            _shopee_csv([("SN001", "2026-06-02", "500", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows1, source="shopee_csv",
                                        actor=ACTOR)
        rows2, _ = orders_channel.parse_shopee_csv(
            _shopee_csv([("SN001", "2026-06-02", "800", None)]))
        result = orders_channel.save_shopee_rows(web.conn, self.bid, rows2, source="shopee_csv",
                                                  actor=ACTOR)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.imported, 0)
        count = web.conn.execute(
            "SELECT COUNT(*) c FROM shopee_report_row WHERE brand_id = %s", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)
        revenue = orders_channel.shopee_revenue(web.conn, self.bid, "2026-06-01", "2026-06-30")
        self.assertEqual(revenue, 800.0)

    def test_no_rows_in_range_returns_none_not_zero(self):
        self.assertIsNone(
            orders_channel.shopee_revenue(web.conn, self.bid, "2026-01-01", "2026-01-31"))


class DispatchShopeeTest(_BaseChannelTest):
    def test_shopee_csv_routes_to_shopee_importer(self):
        content = _shopee_csv([("SN010", "2026-06-03", "999", None)]).encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            web.conn, self.bid, filename="shopee_orders.csv", content=content, actor=ACTOR)
        self.assertEqual(result.kind, "shopee_report")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.shopee_result.imported, 1)


class RestockIntervalTest(_BaseChannelTest):
    def _batch(self, batch_date):
        orders_channel.record_pharmacy_batch(web.conn, self.bid, batch_date=batch_date,
                                             actor=ACTOR)

    def test_fewer_than_three_batches_is_insufficient_data(self):
        self._batch("2026-05-01")
        self._batch("2026-06-01")
        result = orders_channel.restock_interval_signal(web.conn, self.bid, "2026-06-15")
        self.assertIsNone(result["shortened"])

    def test_shortened_interval_is_detected(self):
        """間隔從 30 天縮到 10 天（縮短 67%），達門檻應判為外溢訊號。"""
        self._batch("2026-04-01")
        self._batch("2026-05-01")  # 間隔 30 天
        self._batch("2026-05-11")  # 間隔 10 天
        result = orders_channel.restock_interval_signal(web.conn, self.bid, "2026-06-01")
        self.assertTrue(result["shortened"])
        self.assertEqual(result["latest_interval_days"], 10)
        self.assertEqual(result["baseline_interval_days"], 30.0)

    def test_stable_interval_is_not_flagged(self):
        self._batch("2026-04-01")
        self._batch("2026-05-01")
        self._batch("2026-06-01")  # 間隔穩定在 30 天上下
        result = orders_channel.restock_interval_signal(web.conn, self.bid, "2026-06-15")
        self.assertFalse(result["shortened"])


if __name__ == "__main__":
    unittest.main()
