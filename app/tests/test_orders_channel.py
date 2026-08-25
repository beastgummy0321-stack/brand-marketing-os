# -*- coding: utf-8 -*-
"""app/tests/test_orders_channel.py — 通路對照卡（GitHub issue #40，決策 0025 第二節 B）。

驗收重點：
1. 蝦皮檔解析＋藥局批次表單＋蝦皮碼欄位；全部選填。
2. 燈號規則正確：外溢（藍）／互噬（橘）／缺資料（灰），fixture 驗算。
3. 灰燈債務（連兩期缺通路資料）降級判讀可信度，不進打斷佇列。
4. 檔期刪除連帶清掉 cycle_shopee_code（CYCLE_CASCADE_TABLES）。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import unittest

import pytest

import app.shared.web as web
from app.ads import reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.llm.providers import FakeProvider, ProviderResponse, Usage
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch

ACTOR = "測試員"

# BUG app/orders/channel.py:183 — shopee_revenue() 回傳 round(row["total"] or 0, 2)；
# row["total"] 是 Postgres numeric SUM() 讀回的 Decimal，round(Decimal, 2) 還是
# Decimal（不像 round(float, 2) 會強制轉型），跟函式簽章宣告的 Optional[float] 不符。
_BUG_SHOPEE_REVENUE_DECIMAL = pytest.mark.xfail(
    strict=True,
    reason="BUG app/orders/channel.py:183 — shopee_revenue() 簽章寫 Optional[float]，"
           "實際 round(Decimal, 2) 回傳 Decimal，下游跟 float 做算術/比較會不一致",
)

# BUG app/ads/performance.py:364 — import_rows() 的 INSERT INTO performance_snapshot
# 對某個 date 型別欄位傳了空字串 ""，SQLite 的 TEXT 親和性容忍空字串當日期，Postgres
# 的 date 欄位直接拒絕（psycopg.errors.InvalidDatetimeFormat）。
_BUG_PERFORMANCE_EMPTY_STRING_DATE = pytest.mark.xfail(
    strict=True,
    reason="BUG app/ads/performance.py:364 — import_rows() INSERT 對 date 欄位傳空字串，"
           "psycopg.errors.InvalidDatetimeFormat: invalid input syntax for type date: ''",
)

_SHOPEE_CSV_HEADER = "Order SN,Order creation date,Order amount,Voucher code\n"


def _shopee_csv(rows):
    body = "".join(f"{sn},{d},{amt},{code or ''}\n" for sn, d, amt, code in rows)
    return _SHOPEE_CSV_HEADER + body


class _BaseChannelTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構晨露茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(web.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
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


class SignalRuleTest(_BaseChannelTest):
    """燈號規則 fixture 驗算：外溢藍／互噬橘／缺資料灰。"""

    def setUp(self):
        super().setUp()
        self.cycle = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)

    def test_no_data_at_all_is_gray(self):
        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertEqual(result["light"], "gray")

    def test_redemption_count_triggers_spillover(self):
        orders_channel.set_shopee_code(web.conn, self.bid, self.cycle["id"], code="SHOPJUN",
                                       redemption_count=12, actor=ACTOR)
        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertEqual(result["light"], "spillover")
        self.assertEqual(result["badge_kind"], "accent")
        self.assertIn("12", result["message"])

    @_BUG_SHOPEE_REVENUE_DECIMAL
    def test_shopee_revenue_growth_triggers_spillover(self):
        # 前一段等長期間（14 天）：2026-05-18 ~ 2026-05-31，營收 1000
        rows, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B1", "2026-05-20", "1000", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows, source="shopee_csv", actor=ACTOR)
        # 本期：2026-06-01 ~ 06-14，營收 1300（成長 30%）
        rows2, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B2", "2026-06-05", "1300", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows2, source="shopee_csv", actor=ACTOR)

        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertEqual(result["light"], "spillover")
        self.assertEqual(result["shopee_growth"]["ratio"], 0.3)

    def test_shopee_revenue_decline_triggers_cannibalization(self):
        rows, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B1", "2026-05-20", "1000", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows, source="shopee_csv", actor=ACTOR)
        rows2, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B2", "2026-06-05", "700", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows2, source="shopee_csv", actor=ACTOR)

        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertEqual(result["light"], "cannibalization")
        self.assertEqual(result["badge_kind"], "warn")

    def test_shortened_restock_interval_triggers_spillover(self):
        orders_channel.record_pharmacy_batch(web.conn, self.bid, batch_date="2026-03-01",
                                             actor=ACTOR)
        orders_channel.record_pharmacy_batch(web.conn, self.bid, batch_date="2026-04-01",
                                             actor=ACTOR)
        orders_channel.record_pharmacy_batch(web.conn, self.bid, batch_date="2026-04-11",
                                             actor=ACTOR)
        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertEqual(result["light"], "spillover")

    def test_data_present_but_no_signal_stays_unlit(self):
        rows, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B1", "2026-05-20", "1000", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows, source="shopee_csv", actor=ACTOR)
        rows2, _ = orders_channel.parse_shopee_csv(_shopee_csv([("B2", "2026-06-05", "1020", None)]))
        orders_channel.save_shopee_rows(web.conn, self.bid, rows2, source="shopee_csv", actor=ACTOR)

        result = orders_channel.signal(web.conn, self.bid, self.cycle)
        self.assertIsNone(result["light"])


class GrayLightDebtTest(_BaseChannelTest):
    def test_single_gray_cycle_is_not_debt_yet(self):
        cycle = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        self.assertFalse(
            orders_channel.gray_light_debt(web.conn, self.bid, cycle, ads_repo.list_cycles))

    def test_two_consecutive_gray_cycles_are_debt(self):
        first = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-05-01", duration_days=14)
        second = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        self.assertTrue(
            orders_channel.gray_light_debt(web.conn, self.bid, second, ads_repo.list_cycles))
        # 灰燈債務不進打斷佇列（決策 0025 補遺第 8 點：跟老手暗門的跳過記債是兩套債務）
        self.assertEqual(core_interrupts.list_open(web.conn, brand_id=self.bid), [])

    def test_filled_previous_cycle_breaks_the_debt(self):
        first = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-05-01", duration_days=14)
        orders_channel.set_shopee_code(web.conn, self.bid, first["id"], code="SHOPMAY",
                                       redemption_count=3, actor=ACTOR)
        second = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        self.assertFalse(
            orders_channel.gray_light_debt(web.conn, self.bid, second, ads_repo.list_cycles))


class CascadeDeleteTest(_BaseChannelTest):
    def test_deleting_cycle_removes_its_shopee_code(self):
        cycle = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        orders_channel.set_shopee_code(web.conn, self.bid, cycle["id"], code="SHOPJUN",
                                       redemption_count=1, actor=ACTOR)
        ads_repo.set_cycle_archived(web.conn, self.bid, cycle["id"], archived=True, actor=ACTOR)
        ads_repo.delete_cycle(web.conn, self.bid, cycle["id"], actor=ACTOR)
        self.assertIsNone(orders_channel.get_shopee_code(web.conn, self.bid, cycle["id"]))


class ReadingIntegrationTest(_BaseChannelTest):
    """通路對照卡掛進判讀（app/ads/reading.run），純顯示、不影響判定結果本身。"""

    def setUp(self):
        super().setUp()
        self.cycle = ads_repo.create_cycle(
            web.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text='{"text": "測試判讀說明"}', structured=None,
            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn"))

    def tearDown(self):
        reading.PROVIDER = self._orig

    @_BUG_PERFORMANCE_EMPTY_STRING_DATE
    def test_run_attaches_channel_comparison_to_cycle_verdict(self):
        from app.ads import performance as ads_performance
        ads_performance.import_manual(
            web.conn, self.bid, self.cycle["id"],
            {"spend": 10000, "impressions": 20000, "clicks": 400, "conversions": 10,
             "revenue": 40000}, actor=ACTOR)
        ok, err = reading.run(web.conn, self.bid, self.cycle["id"], ACTOR)
        self.assertTrue(ok, err)
        result = reading.load(web.conn, self.bid, self.cycle["id"])["cycle"]["result"]
        self.assertIn("channel_comparison", result)
        self.assertEqual(result["channel_comparison"]["light"], "gray")
        self.assertFalse(result["channel_comparison"]["gray_light_debt"])


if __name__ == "__main__":
    unittest.main()
