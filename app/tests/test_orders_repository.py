# -*- coding: utf-8 -*-
"""app/tests/test_orders_repository.py — 訂單票（issue #33）：落庫、5 項統計卡、逐 SKU 毛利。

fixture 一律虛構品牌（「虛構晨光茶行」），嚴禁真實客戶資料（規範第八節）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_orders_repo_")

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _order(order_number, order_date, total_amount, refunded_amount=0, order_status="paid",
          billing_email=None, billing_phone=None, items=None):
    return {
        "order_number": order_number, "order_date": order_date, "total_amount": total_amount,
        "refunded_amount": refunded_amount, "financial_status": "paid",
        "fulfillment_status": "fulfilled", "order_status": order_status,
        "voucher_code": None, "billing_email": billing_email, "billing_phone": billing_phone,
        "items": items or [],
    }


class _BaseOrdersTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]


class SaveOrdersTest(_BaseOrdersTest):
    def test_new_order_and_customer_are_created(self):
        rows = [_order("ORD1", "2026-06-01", 1000, billing_email="A@Example.com",
                       items=[{"sku": "SKU-A", "item_price": 500, "quantity": 2}])]
        result = orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx",
                                         actor=ACTOR)
        self.assertEqual(result.orders_imported, 1)
        self.assertEqual(result.orders_updated, 0)
        self.assertEqual(result.items_imported, 1)

        order = main.conn.execute(
            "SELECT * FROM order_record WHERE brand_id = ? AND order_number = 'ORD1'",
            (self.bid,)).fetchone()
        self.assertIsNotNone(order["customer_id"])
        customer = main.conn.execute("SELECT * FROM customer WHERE id = ?",
                                     (order["customer_id"],)).fetchone()
        self.assertEqual(customer["identity_type"], "email")

    def test_reimporting_same_order_number_updates_in_place_not_duplicates(self):
        rows = [_order("ORD2", "2026-06-01", 500, billing_email="b@example.com")]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        # 歷史回填月份重疊：同一張訂單狀態更新（例如退款）後重丟
        rows2 = [_order("ORD2", "2026-06-01", 500, refunded_amount=500, order_status="refunded",
                        billing_email="b@example.com")]
        result2 = orders_repo.save_orders(main.conn, self.bid, rows2, source="easystore_xlsx",
                                          actor=ACTOR)
        self.assertEqual(result2.orders_imported, 0)
        self.assertEqual(result2.orders_updated, 1)
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM order_record WHERE brand_id = ? AND order_number = 'ORD2'",
            (self.bid,)).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_phone_and_email_variants_resolve_to_same_customer(self):
        orders_repo.save_orders(
            main.conn, self.bid,
            [_order("ORD3", "2026-06-01", 100, billing_phone="0912345678")],
            source="easystore_xlsx", actor=ACTOR)
        orders_repo.save_orders(
            main.conn, self.bid,
            [_order("ORD4", "2026-06-02", 100, billing_phone="+886912345678")],
            source="easystore_xlsx", actor=ACTOR)
        customers = main.conn.execute(
            "SELECT COUNT(*) c FROM customer WHERE brand_id = ?", (self.bid,)).fetchone()["c"]
        self.assertEqual(customers, 1, "0912 與 +886 應該是同一人，不該開出兩個顧客")

    def test_missing_billing_info_leaves_order_unlinked_not_a_fake_customer(self):
        orders_repo.save_orders(
            main.conn, self.bid, [_order("ORD5", "2026-06-01", 100)],
            source="easystore_xlsx", actor=ACTOR)
        order = main.conn.execute(
            "SELECT customer_id FROM order_record WHERE brand_id = ? AND order_number = 'ORD5'",
            (self.bid,)).fetchone()
        self.assertIsNone(order["customer_id"])


class StatsFixtureTest(_BaseOrdersTest):
    """五項統計卡 fixture 驗算（issue #33 驗收條件）。"""

    def setUp(self):
        super().setUp()
        rows = [
            # 顧客 4：窗口前就有一筆訂單，之後窗口內回購 -> 「舊客」+ 回購者
            _order("O-PREV", "2026-05-15", 200, billing_email="d@example.com",
                  items=[{"sku": "SKU-A", "item_price": 100, "quantity": 2}]),
            # 顧客 1：窗口內兩筆 -> 「新客」+ 回購者
            _order("O1", "2026-06-05", 1000, billing_email="a@example.com",
                  items=[{"sku": "SKU-A", "item_price": 100, "quantity": 5}]),
            _order("O2", "2026-06-20", 500, billing_email="a@example.com",
                  items=[{"sku": "SKU-B", "item_price": 50, "quantity": 2}]),
            # 顧客 2：窗口內一筆、部分退款 -> 「新客」、非回購者
            _order("O3", "2026-06-10", 800, refunded_amount=100, billing_phone="0922222222",
                  items=[{"sku": "SKU-A", "item_price": 100, "quantity": 3}]),
            # 顧客 3：窗口內唯一一筆是棄單，實收與新舊客都不該把它算進去
            _order("O4", "2026-06-15", 400, order_status="cancelled", billing_email="c@example.com",
                  items=[{"sku": "SKU-C", "item_price": 400, "quantity": 1}]),
            # 顧客 4：窗口內回購
            _order("O5", "2026-06-25", 600, billing_email="d@example.com",
                  items=[{"sku": "SKU-B", "item_price": 50, "quantity": 4}]),
        ]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        orders_repo.set_sku_cost(main.conn, self.bid, "SKU-A", 60, actor=ACTOR)
        self.summary = orders_repo.stats(main.conn, self.bid, since="2026-06-01",
                                         until="2026-06-30", today="2026-06-30")

    def test_net_revenue_excludes_refund_and_cancelled_order(self):
        # (1000-0)+(500-0)+(800-100)+(600-0) = 2800；O4 全額不計（棄單）
        self.assertEqual(self.summary["net_revenue"], 2800)

    def test_order_count_excludes_cancelled(self):
        self.assertEqual(self.summary["order_count"], 4)

    def test_average_order_value(self):
        self.assertAlmostEqual(self.summary["average_order_value"], 700.0)

    def test_new_vs_existing_customers(self):
        # 顧客1、顧客2 窗口內首次出現 -> 新客；顧客4 窗口前就有訂單 -> 舊客；顧客3 只有棄單不算
        self.assertEqual(self.summary["new_customers"], 2)
        self.assertEqual(self.summary["existing_customers"], 1)

    def test_repurchase_rate(self):
        # 窗口內有效訂單顧客共 3 位（1、2、4），其中 1、4 全期累計 >=2 筆 -> 2/3
        self.assertEqual(self.summary["repurchase_sample_size"], 3)
        self.assertAlmostEqual(self.summary["repurchase_rate"], 2 / 3, places=4)

    def test_sku_margin_with_registered_cost(self):
        by_sku = {row["sku"]: row for row in self.summary["sku_margins"]}
        self.assertEqual(by_sku["SKU-A"]["revenue"], 800)   # 500(O1) + 300(O3)
        self.assertEqual(by_sku["SKU-A"]["quantity"], 8)
        self.assertEqual(by_sku["SKU-A"]["margin"], 320)     # 800 - 60*8

    def test_sku_margin_honestly_unknown_without_registered_cost(self):
        by_sku = {row["sku"]: row for row in self.summary["sku_margins"]}
        self.assertIsNone(by_sku["SKU-B"]["unit_cost"])
        self.assertIsNone(by_sku["SKU-B"]["margin"])
        self.assertEqual(by_sku["SKU-B"]["revenue"], 300)   # 100(O2) + 200(O5)

    def test_cancelled_order_sku_excluded_from_margin_table(self):
        skus = {row["sku"] for row in self.summary["sku_margins"]}
        self.assertNotIn("SKU-C", skus)


class NoHistoryTest(_BaseOrdersTest):
    def test_empty_brand_shows_no_history_not_an_error(self):
        summary = orders_repo.stats(main.conn, self.bid, today="2026-06-30")
        self.assertFalse(summary["has_history"])
        self.assertIsNone(summary["net_revenue"])
        self.assertIsNone(summary["average_order_value"])
        self.assertIsNone(summary["repurchase_rate"])
        self.assertEqual(summary["sku_margins"], [])


class RepurchaseMultiplierTest(_BaseOrdersTest):
    """票 #39：回購倍數＝滿 90 天觀察期顧客的「90 天內淨營收」÷「首單淨營收」。"""

    def test_no_customers_returns_none_not_zero(self):
        result = orders_repo.repurchase_multiplier(main.conn, self.bid, today="2026-06-30")
        self.assertIsNone(result["multiplier"])
        self.assertEqual(result["sample_size"], 0)
        self.assertTrue(result["insufficient_sample"])

    def _seed_customers(self, count, *, repeat=True):
        """count 位顧客，首單 2026-01-01（早於 today 90 天以上）；repeat=True 時第 46 天
        再下一筆等額訂單（回購倍數 2 倍）。"""
        rows = []
        for i in range(count):
            email = f"c{i}@example.com"
            rows.append(_order(f"F{i}", "2026-01-01", 1000, billing_email=email))
            if repeat:
                rows.append(_order(f"R{i}", "2026-02-15", 1000, billing_email=email))
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)

    def test_below_sample_threshold_does_not_enable_multiplier(self):
        """票 #39 驗收條件：樣本不足不顯示實質線（回 None，不是硬湊一個數字）。"""
        self._seed_customers(29)
        result = orders_repo.repurchase_multiplier(main.conn, self.bid, today="2026-06-30")
        self.assertIsNone(result["multiplier"])
        self.assertEqual(result["sample_size"], 29)
        self.assertTrue(result["insufficient_sample"])

    def test_meeting_sample_threshold_computes_multiplier(self):
        """30 位顧客，首單 1000、90 天內回購再 1000 -> 倍數 2.0（fixture 驗算）。"""
        self._seed_customers(30)
        result = orders_repo.repurchase_multiplier(main.conn, self.bid, today="2026-06-30")
        self.assertFalse(result["insufficient_sample"])
        self.assertEqual(result["sample_size"], 30)
        self.assertEqual(result["multiplier"], 2.0)

    def test_customer_whose_observation_window_has_not_elapsed_is_excluded(self):
        """首單日距離 today 還不滿 90 天的顧客，觀察期還沒跑完，不計入樣本。"""
        self._seed_customers(30)
        # 額外 5 位顧客首單在 today 前 10 天，觀察期還沒跑完
        recent = [_order(f"L{i}", "2026-06-20", 1000, billing_email=f"late{i}@example.com")
                  for i in range(5)]
        orders_repo.save_orders(main.conn, self.bid, recent, source="easystore_xlsx", actor=ACTOR)
        result = orders_repo.repurchase_multiplier(main.conn, self.bid, today="2026-06-30")
        self.assertEqual(result["sample_size"], 30)  # 還是 30，不是 35


class PolicyChangeLogTest(_BaseOrdersTest):
    """票 #39：折扣／退款口徑變更記變更日（決策 0025 第 4 點）。"""

    def test_record_and_list(self):
        orders_repo.record_policy_change(
            main.conn, self.bid, policy_type="discount", changed_at="2026-05-01",
            description="滿千折百改為滿千折八十", actor=ACTOR)
        changes = orders_repo.list_policy_changes(main.conn, self.bid)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["policy_type"], "discount")

    def test_unknown_policy_type_is_rejected(self):
        with self.assertRaises(ValueError):
            orders_repo.record_policy_change(
                main.conn, self.bid, policy_type="shipping", changed_at="2026-05-01",
                description="改運費規則", actor=ACTOR)

    def test_until_filters_out_future_changes(self):
        orders_repo.record_policy_change(
            main.conn, self.bid, policy_type="refund", changed_at="2026-07-01",
            description="退款期限從 7 天改 14 天", actor=ACTOR)
        self.assertEqual(len(orders_repo.list_policy_changes(main.conn, self.bid,
                                                              until="2026-06-30")), 0)
        self.assertEqual(len(orders_repo.list_policy_changes(main.conn, self.bid,
                                                              until="2026-07-31")), 1)


class UnsettledRatioTest(_BaseOrdersTest):
    """票 #38：期末暫定判讀標注「未結案訂單佔 X%」（決策 0025 判讀節奏第 5 點）。"""

    def _order_with_fulfillment(self, order_number, fulfillment_status, order_status="paid"):
        row = _order(order_number, "2026-06-05", 1000, order_status=order_status)
        row["fulfillment_status"] = fulfillment_status
        return row

    def test_no_orders_returns_none_not_zero(self):
        self.assertIsNone(orders_repo.unsettled_order_ratio(
            main.conn, self.bid, "2026-06-01", "2026-06-30"))

    def test_ratio_counts_non_fulfilled_as_unsettled(self):
        rows = [
            self._order_with_fulfillment("O1", "fulfilled"),
            self._order_with_fulfillment("O2", "unfulfilled"),
            self._order_with_fulfillment("O3", None),
            self._order_with_fulfillment("O4", "fulfilled"),
        ]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        ratio = orders_repo.unsettled_order_ratio(main.conn, self.bid, "2026-06-01", "2026-06-30")
        self.assertEqual(ratio, 0.5)  # O2、O3 未結案，共 2/4

    def test_voided_orders_are_excluded_from_the_denominator(self):
        rows = [
            self._order_with_fulfillment("O1", "fulfilled"),
            self._order_with_fulfillment("O2", "unfulfilled", order_status="cancelled"),
        ]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        ratio = orders_repo.unsettled_order_ratio(main.conn, self.bid, "2026-06-01", "2026-06-30")
        self.assertEqual(ratio, 0.0)  # 作廢訂單不計入分母，剩下的都已結案


if __name__ == "__main__":
    unittest.main()
