"""app/tests/test_orders_channel.py — 通路對照卡（GitHub issue #40，決策 0025 第二節 B；
票 12／ADR 0035 通路是資料）：蝦皮檔解析＋落地到共用 channel_revenue、手動登記、
revenue NULL＝「不知道」不能在彙總途中變成假的 0（鐵則 16）。

外殼切片（2026-08-28）＋票 12（2026-08-29）：燈號規則、灰燈債務、蝦皮期別碼、判讀整合、
藥局補貨間隔訊號（RestockIntervalTest）隨 `app/ads/` 一起刪掉——呼叫端不存在了。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch
from app.orders import repository as orders_repo

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
    """票 12：save_shopee_rows 現在寫 channel_revenue（channel='marketplace'）。"""

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
            "SELECT COUNT(*) c FROM channel_revenue WHERE brand_id = %s AND channel = 'marketplace'",
            (self.bid,),
        ).fetchone()["c"]
        self.assertEqual(count, 1)
        summary = orders_repo.channel_revenue_summary(
            web.conn, self.bid, since="2026-06-01", until="2026-06-30")
        self.assertEqual(summary["revenue"], 800.0)
        self.assertTrue(summary["marketplace_uncalibrated"])
        # 票 T7：這條路徑已經靠 external_id 去重，新的 source_row_hash 欄位不歸它管——
        # 留 NULL，否則兩筆金額剛好一樣的不同蝦皮訂單會被新的 partial unique index 誤判成重複。
        row_hash = web.conn.execute(
            "SELECT source_row_hash FROM channel_revenue"
            " WHERE brand_id = %s AND channel = 'marketplace'", (self.bid,)).fetchone()
        self.assertIsNone(row_hash["source_row_hash"])

    def test_no_rows_in_range_returns_none_not_zero(self):
        summary = orders_repo.channel_revenue_summary(
            web.conn, self.bid, since="2026-01-01", until="2026-01-31")
        self.assertIsNone(summary["revenue"])
        self.assertFalse(summary["has_rows"])


class DispatchShopeeTest(_BaseChannelTest):
    def test_shopee_csv_routes_to_shopee_importer(self):
        content = _shopee_csv([("SN010", "2026-06-03", "999", None)]).encode("utf-8")
        result = orders_dispatch.import_dropped_file(
            web.conn, self.bid, filename="shopee_orders.csv", content=content, actor=ACTOR)
        self.assertEqual(result.kind, "shopee_report")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.shopee_result.imported, 1)


def _website_ledger(bid):
    row = web.conn.execute(
        "SELECT SUM(revenue) s, COUNT(*) c FROM channel_revenue"
        " WHERE brand_id = %s AND channel = 'website'", (bid,)).fetchone()
    return float(row["s"]), row["c"]


class WebsiteChannelRevenueMatchesStatsTest(_BaseChannelTest):
    """定案 5（ADR 0035）：保護的是錢——channel='website' 加總要跟 stats()['net_revenue']
    對得上（退款、棄單都要算對），重複匯入不能讓帳翻倍。"""

    def test_website_ledger_sum_equals_stats_net_revenue_and_survives_reimport(self):
        rows = [
            {"order_number": "WEB-1", "order_date": "2026-06-01", "total_amount": 1000,
             "refunded_amount": 0, "order_status": "paid", "items": []},
            {"order_number": "WEB-2", "order_date": "2026-06-05", "total_amount": 800,
             "refunded_amount": 200, "order_status": "paid", "items": []},
            {"order_number": "WEB-3", "order_date": "2026-06-10", "total_amount": 500,
             "refunded_amount": 0, "order_status": "cancelled", "items": []},
        ]
        orders_repo.save_orders(web.conn, self.bid, rows, source="test", actor=ACTOR)
        stats = orders_repo.stats(web.conn, self.bid, since="2026-06-01", until="2026-06-30",
                                  today="2026-06-30")
        ledger_sum, _ = _website_ledger(self.bid)
        self.assertEqual(stats["net_revenue"], 1600)
        self.assertEqual(ledger_sum, stats["net_revenue"])

        orders_repo.save_orders(web.conn, self.bid, rows, source="test", actor=ACTOR)  # 重丟同一批
        ledger_sum_after, count = _website_ledger(self.bid)
        self.assertEqual(count, 3, "重複匯入把帳翻倍了")
        self.assertEqual(ledger_sum_after, 1600)

        # 重新匯入把日期洗掉：stats() 按 order_date 篩選，這筆從此不算進實收，帳本也要
        # 跟著清掉，否則帳本會比訂單頁多一筆而且永遠對不回來。
        rows[0]["order_date"] = None
        orders_repo.save_orders(web.conn, self.bid, rows, source="test", actor=ACTOR)
        stats_after = orders_repo.stats(web.conn, self.bid, since="2026-06-01",
                                        until="2026-06-30", today="2026-06-30")
        ledger_sum_final, count_final = _website_ledger(self.bid)
        self.assertEqual(count_final, 2)
        self.assertEqual(ledger_sum_final, stats_after["net_revenue"])


class ManualChannelEntryDataCorrectnessTest(_BaseChannelTest):
    """定案 1／鐵則 16：revenue NULL＝不知道，不能在彙總途中變成假的 0。"""

    def test_offline_entry_without_revenue_survives_as_unknown_not_zero(self):
        orders_channel.record_channel_entry(
            web.conn, self.bid, channel="physical_store", entry_date="2026-06-01",
            revenue=None, quantity=12, note="到貨", actor=ACTOR)
        summary = orders_repo.channel_revenue_summary(
            web.conn, self.bid, since="2026-06-01", until="2026-06-30")
        self.assertTrue(summary["has_rows"])
        self.assertIsNone(summary["revenue"])
        # 不認得的通路、以及「官網不能手動登錄」，都在 test_orders_api.py 的
        # channel-entry 契約測試裡驗（同一個行為不在兩層各測一次）。


class ManualChannelEntryDedupeTest(_BaseChannelTest):
    """票 T7：手動登記本來沒有 external_id，partial unique index 去不了重——按兩次同一張
    表單＝營收翻倍。保護的是錢（done-check 1）與資料正確性（done-check 2，鐵則 8 手動
    路徑不能因為去重機制被誤傷）。"""

    def test_identical_resubmit_updates_not_duplicates(self):
        for _ in range(2):
            orders_channel.record_channel_entry(
                web.conn, self.bid, channel="physical_store", entry_date="2026-06-01",
                revenue=5000, quantity=3, note="到貨", actor=ACTOR)
        row = web.conn.execute(
            "SELECT COUNT(*) n, SUM(revenue) s FROM channel_revenue"
            " WHERE brand_id = %s AND channel = 'physical_store'", (self.bid,)).fetchone()
        self.assertEqual(row["n"], 1, "按兩次同一張手動登記表單把營收翻倍了")
        self.assertEqual(float(row["s"]), 5000.0, "重複送出後營收金額變了，不是單純更新")

    def test_a_genuinely_different_second_entry_still_lands(self):
        orders_channel.record_channel_entry(
            web.conn, self.bid, channel="physical_store", entry_date="2026-06-01",
            revenue=5000, quantity=3, note="到貨", actor=ACTOR)
        orders_channel.record_channel_entry(
            web.conn, self.bid, channel="physical_store", entry_date="2026-06-01",
            revenue=5000, quantity=3, note="到貨（補開一趟車，不是同一筆）", actor=ACTOR)
        count = web.conn.execute(
            "SELECT COUNT(*) c FROM channel_revenue"
            " WHERE brand_id = %s AND channel = 'physical_store'", (self.bid,)).fetchone()["c"]
        self.assertEqual(count, 2, "只有備註不同的第二筆手動登記被誤判成重複，沒有落地")


if __name__ == "__main__":
    unittest.main()
