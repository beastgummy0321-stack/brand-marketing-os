"""訂單唯讀 API 的回應形狀、分頁與找不到品牌情境。"""

import io
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.orders import repository as orders_repo

# Relative, not literal: the summary defaults to a trailing window, so a fixed date expires.
_RECENT_ORDER_DATE = (date.today() - timedelta(days=10)).isoformat()

_EASYSTORE_HEADERS = [
    "Order Number", "Date", "Total Amount", "Refunded Amount", "Financial Status",
    "Fulfillment Status", "Order Status", "Voucher Code", "Billing Email", "Billing Phone",
    "Item SKU", "Item Price", "Quantity",
]


def _easystore_xlsx_bytes():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(_EASYSTORE_HEADERS)
    sheet.append([
        "API-IMPORT-00001", "2026-08-20", 1000, 0, "paid", "fulfilled", "completed", None,
        "imported@example.com", None, "GM-500", 1000, 1,
    ])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class OrdersApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="訂單 API 測試品牌", client_name=None, actor="測試員", org_id=DEV_ORG_ID)
        self.brand_id = self.brand["id"]
        rows = []
        for index in range(13):
            rows.append({
                "order_number": f"ES-{index + 1:05}", "order_date": _RECENT_ORDER_DATE,
                "total_amount": 1000 + index, "refunded_amount": 0, "financial_status": "paid",
                "fulfillment_status": "fulfilled", "order_status": "completed",
                "voucher_code": "SUMMER10" if index == 0 else None,
                "billing_email": f"buyer{index}@example.com", "billing_phone": None,
                "items": [{"sku": "GM-500", "item_price": 1000 + index, "quantity": 1}],
            })
        orders_repo.save_orders(web.conn, self.brand_id, rows, source="test", actor="測試員")
        orders_repo.set_sku_cost(web.conn, self.brand_id, "GM-500", 620, actor="測試員")

    def test_get_orders_returns_summary_and_second_page(self):
        response = self.client.get(f"/api/brands/{self.brand_id}/orders?page=2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["brand"], {"id": self.brand_id, "name": "訂單 API 測試品牌"})
        self.assertEqual(body["orders"]["page"], 2)
        self.assertEqual(body["orders"]["page_size"], 12)
        self.assertEqual(body["orders"]["total"], 13)
        self.assertEqual(len(body["orders"]["items"]), 1)
        self.assertEqual(set(body["orders"]["items"][0]), {
            "id", "order_number", "order_date", "total_amount", "order_status",
            "voucher_code",
        })
        self.assertEqual(set(body["summary"]), {
            "since", "until", "has_history", "order_count", "net_revenue",
            "average_order_value", "new_customers", "existing_customers", "repurchase_rate",
            "repurchase_sample_size", "sku_margins",
        })
        self.assertEqual(body["summary"]["sku_margins"][0]["unit_cost"], 620.0)
        self.assertEqual(body["summary"]["sku_margins"][0]["margin"], 5018.0)

    def test_missing_brand_is_404(self):
        response = self.client.get("/api/brands/missing/orders")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(set(response.json()), {"detail"})

    def test_import_orders_returns_message_and_increases_total(self):
        before = self.client.get(f"/api/brands/{self.brand_id}/orders").json()["orders"]["total"]
        response = self.client.post(
            f"/api/brands/{self.brand_id}/orders/import",
            files={"drop_file": ("Export_Orders.xlsx", _easystore_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        after = self.client.get(f"/api/brands/{self.brand_id}/orders").json()["orders"]["total"]
        self.assertEqual(after, before + 1)

        empty = self.client.post(
            f"/api/brands/{self.brand_id}/orders/import",
            files={"drop_file": ("empty.csv", b"", "text/csv")},
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(set(empty.json()), {"detail"})

    def test_sku_cost_returns_exact_success_and_failure_messages(self):
        response = self.client.post(
            f"/api/brands/{self.brand_id}/orders/sku-cost",
            json={"sku": "GM-500", "unit_cost": "620"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        self.assertIn("620.00", response.json()["message"])

        numeric = self.client.post(
            f"/api/brands/{self.brand_id}/orders/sku-cost",
            json={"sku": "GM-500", "unit_cost": 620},
        )
        self.assertEqual(numeric.status_code, 200)
        self.assertEqual(numeric.json()["ok"], True)
        self.assertIn("620.00", numeric.json()["message"])

        invalid = self.client.post(
            f"/api/brands/{self.brand_id}/orders/sku-cost",
            json={"sku": "GM-500", "unit_cost": "六百二十"},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(set(invalid.json()), {"detail"})

    def test_policy_change_returns_exact_messages_and_gets_label(self):
        response = self.client.post(
            f"/api/brands/{self.brand_id}/orders/policy-change",
            json={"policy_type": "discount", "changed_at": "2026-08-01", "description": "改成全站 9 折"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        body = self.client.get(f"/api/brands/{self.brand_id}/orders").json()
        self.assertEqual(body["policy_changes"], [{
            "policy_type": "discount", "policy_type_label": orders_repo.POLICY_TYPE_LABELS["discount"],
            "changed_at": "2026-08-01", "description": "改成全站 9 折",
        }])

        invalid = self.client.post(
            f"/api/brands/{self.brand_id}/orders/policy-change",
            json={"policy_type": "unknown", "changed_at": "2026-08-01", "description": "改成全站 9 折"},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("unknown", invalid.json()["detail"])

    def test_channel_entry_revenue_zero_kept_negative_refused(self):
        """F47 Contract A: revenue 0 is stored as 0, JSON null = left empty, -5 is refused with
        the field sentence and nothing lands."""
        url = f"/api/brands/{self.brand_id}/orders/channel-entry"
        zero = self.client.post(url, json={"channel": "physical_store", "entry_date": "2026-08-19",
                                           "revenue": 0, "quantity": None, "note": ""})
        self.assertEqual(zero.status_code, 200, zero.text)
        unset = self.client.post(url, json={"channel": "physical_store", "entry_date": "2026-08-20",
                                            "revenue": None, "quantity": None, "note": ""})
        self.assertEqual(unset.status_code, 200, unset.text)
        negative = self.client.post(url, json={"channel": "physical_store", "entry_date": "2026-08-21",
                                               "revenue": -5, "quantity": None, "note": ""})
        self.assertEqual((negative.status_code, negative.json()), (400, {"detail": "營收不能是負數。"}))
        entries = self.client.get(f"/api/brands/{self.brand_id}/orders").json()["channel_entries"]
        by_date = {e["entry_date"]: e["revenue"] for e in entries}
        self.assertEqual(by_date, {"2026-08-19": 0, "2026-08-20": None})

    def test_channel_entry_returns_exact_messages_and_gets_list(self):
        """票 12：通用通路營收登記取代藥局專屬表單，POST 落地後 GET 從
        channel_entries 讀得回來（channel_label 來自 vocab，不是內部值）。"""
        response = self.client.post(
            f"/api/brands/{self.brand_id}/orders/channel-entry",
            json={"channel": "physical_store", "entry_date": "2026-08-18", "revenue": "",
                  "quantity": "24", "note": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)
        body = self.client.get(f"/api/brands/{self.brand_id}/orders").json()
        self.assertEqual(body["channel_entries"], [{
            "channel": "physical_store", "channel_label": "實體店",
            "entry_date": "2026-08-18", "revenue": None, "quantity": 24.0, "note": "",
        }])

        invalid = self.client.post(
            f"/api/brands/{self.brand_id}/orders/channel-entry",
            json={"channel": "pharmacy", "entry_date": "2026-08-18", "revenue": "",
                  "quantity": "", "note": ""},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(set(invalid.json()), {"detail"})

        # 錢：官網那一列帳由訂單匯入自動記，手動不准再記第二筆——記得成，帳本就會跟
        # 訂單頁的實收永遠對不起來（票 12 settled 段第 4、5 點）。
        website = self.client.post(
            f"/api/brands/{self.brand_id}/orders/channel-entry",
            json={"channel": "website", "entry_date": "2026-08-18", "revenue": "5000",
                  "quantity": "", "note": ""},
        )
        self.assertEqual(website.status_code, 400)
        body = self.client.get(f"/api/brands/{self.brand_id}/orders").json()
        self.assertEqual(len(body["channel_entries"]), 1, "被擋下的那筆不該落地")

    def test_shopee_import_reports_imported_and_updated_counts(self):
        result = SimpleNamespace(
            kind="shopee_report", errors=[],
            shopee_result=SimpleNamespace(imported=2, updated=1),
        )
        with patch("app.orders.routes_api.orders_dispatch.import_dropped_file", return_value=result):
            response = self.client.post(
                f"/api/brands/{self.brand_id}/orders/import",
                files={"drop_file": ("shopee.csv", b"order sn,order amount\n", "text/csv")},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ok"], True)
        self.assertIn("2", body["message"])
        self.assertIn("1", body["message"])

    def test_all_post_endpoints_return_json_when_brand_is_missing(self):
        missing_brand = "missing"
        responses = [
            self.client.post(
                f"/api/brands/{missing_brand}/orders/import",
                files={"drop_file": ("orders.csv", b"header\n", "text/csv")},
            ),
            self.client.post(
                f"/api/brands/{missing_brand}/orders/sku-cost",
                json={"sku": "GM-500", "unit_cost": "620"},
            ),
            self.client.post(
                f"/api/brands/{missing_brand}/orders/policy-change",
                json={"policy_type": "discount", "changed_at": "2026-08-01", "description": "test"},
            ),
            self.client.post(
                f"/api/brands/{missing_brand}/orders/channel-entry",
                json={"channel": "physical_store", "entry_date": "2026-08-18",
                      "revenue": "", "quantity": "24", "note": ""},
            ),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(set(response.json()), {"detail"})


if __name__ == "__main__":
    unittest.main()
