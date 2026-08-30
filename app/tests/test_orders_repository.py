"""app/tests/test_orders_repository.py — 訂單票（issue #33）：落庫、5 項統計卡、逐 SKU 毛利。

fixture 一律虛構品牌（「虛構晨光茶行」），嚴禁真實客戶資料（規範第八節）。
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.orders import repository as orders_repo

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
        self.brand = bi_repo.create_brand(web.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]


class SaveOrdersTest(_BaseOrdersTest):
    def test_new_order_and_customer_are_created(self):
        rows = [_order("ORD1", "2026-06-01", 1000, billing_email="A@Example.com",
                       items=[{"sku": "SKU-A", "item_price": 500, "quantity": 2}])]
        result = orders_repo.save_orders(web.conn, self.bid, rows, source="easystore_xlsx",
                                         actor=ACTOR)
        self.assertEqual(result.orders_imported, 1)
        self.assertEqual(result.orders_updated, 0)
        self.assertEqual(result.items_imported, 1)

        order = web.conn.execute(
            "SELECT * FROM order_record WHERE brand_id = %s AND order_number = 'ORD1'",
            (self.bid,)).fetchone()
        self.assertIsNotNone(order["customer_id"])
        customer = web.conn.execute("SELECT * FROM customer WHERE id = %s",
                                     (order["customer_id"],)).fetchone()
        self.assertEqual(customer["identity_type"], "email")

    def test_reimporting_same_order_number_updates_in_place_not_duplicates(self):
        rows = [_order("ORD2", "2026-06-01", 500, billing_email="b@example.com")]
        orders_repo.save_orders(web.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        # 歷史回填月份重疊：同一張訂單狀態更新（例如退款）後重丟
        rows2 = [_order("ORD2", "2026-06-01", 500, refunded_amount=500, order_status="refunded",
                        billing_email="b@example.com")]
        result2 = orders_repo.save_orders(web.conn, self.bid, rows2, source="easystore_xlsx",
                                          actor=ACTOR)
        self.assertEqual(result2.orders_imported, 0)
        self.assertEqual(result2.orders_updated, 1)
        count = web.conn.execute(
            "SELECT COUNT(*) c FROM order_record WHERE brand_id = %s AND order_number = 'ORD2'",
            (self.bid,)).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_phone_and_email_variants_resolve_to_same_customer(self):
        orders_repo.save_orders(
            web.conn, self.bid,
            [_order("ORD3", "2026-06-01", 100, billing_phone="0912345678")],
            source="easystore_xlsx", actor=ACTOR)
        orders_repo.save_orders(
            web.conn, self.bid,
            [_order("ORD4", "2026-06-02", 100, billing_phone="+886912345678")],
            source="easystore_xlsx", actor=ACTOR)
        customers = web.conn.execute(
            "SELECT COUNT(*) c FROM customer WHERE brand_id = %s", (self.bid,)).fetchone()["c"]
        self.assertEqual(customers, 1, "0912 與 +886 應該是同一人，不該開出兩個顧客")

    def test_missing_billing_info_leaves_order_unlinked_not_a_fake_customer(self):
        orders_repo.save_orders(
            web.conn, self.bid, [_order("ORD5", "2026-06-01", 100)],
            source="easystore_xlsx", actor=ACTOR)
        order = web.conn.execute(
            "SELECT customer_id FROM order_record WHERE brand_id = %s AND order_number = 'ORD5'",
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
        orders_repo.save_orders(web.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)
        orders_repo.set_sku_cost(web.conn, self.bid, "SKU-A", 60, actor=ACTOR)
        self.summary = orders_repo.stats(web.conn, self.bid, since="2026-06-01",
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
        summary = orders_repo.stats(web.conn, self.bid, today="2026-06-30")
        self.assertFalse(summary["has_history"])
        self.assertIsNone(summary["net_revenue"])
        self.assertIsNone(summary["average_order_value"])
        self.assertIsNone(summary["repurchase_rate"])
        self.assertEqual(summary["sku_margins"], [])


class PolicyChangeLogTest(_BaseOrdersTest):
    """票 #39：折扣／退款口徑變更記變更日（決策 0025 第 4 點）。"""

    def test_record_and_list(self):
        orders_repo.record_policy_change(
            web.conn, self.bid, policy_type="discount", changed_at="2026-05-01",
            description="滿千折百改為滿千折八十", actor=ACTOR)
        changes = orders_repo.list_policy_changes(web.conn, self.bid)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["policy_type"], "discount")

    def test_unknown_policy_type_is_rejected(self):
        with self.assertRaises(ValueError):
            orders_repo.record_policy_change(
                web.conn, self.bid, policy_type="shipping", changed_at="2026-05-01",
                description="改運費規則", actor=ACTOR)

    def test_until_filters_out_future_changes(self):
        orders_repo.record_policy_change(
            web.conn, self.bid, policy_type="refund", changed_at="2026-07-01",
            description="退款期限從 7 天改 14 天", actor=ACTOR)
        self.assertEqual(len(orders_repo.list_policy_changes(web.conn, self.bid,
                                                              until="2026-06-30")), 0)
        self.assertEqual(len(orders_repo.list_policy_changes(web.conn, self.bid,
                                                              until="2026-07-31")), 1)


if __name__ == "__main__":
    unittest.main()
