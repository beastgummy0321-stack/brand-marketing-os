# -*- coding: utf-8 -*-
"""訂單唯讀 API 的回應形狀、分頁與找不到品牌情境。"""

import atexit
import os
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_orders_api_")
os.environ["BRAND_OS_DB"] = os.path.join(_tmpdir, "app.db")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402


def _cleanup():
    main.conn.close()
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class OrdersApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="訂單 API 測試品牌", client_name=None, actor="測試員")
        self.brand_id = self.brand["id"]
        rows = []
        for index in range(13):
            rows.append({
                "order_number": f"ES-{index + 1:05}", "order_date": "2026-08-20",
                "total_amount": 1000 + index, "refunded_amount": 0, "financial_status": "paid",
                "fulfillment_status": "fulfilled", "order_status": "completed",
                "voucher_code": "SUMMER10" if index == 0 else None,
                "billing_email": f"buyer{index}@example.com", "billing_phone": None,
                "items": [{"sku": "GM-500", "item_price": 1000 + index, "quantity": 1}],
            })
        orders_repo.save_orders(main.conn, self.brand_id, rows, source="test", actor="測試員")
        orders_repo.set_sku_cost(main.conn, self.brand_id, "GM-500", 620, actor="測試員")

    def test_get_orders_returns_summary_and_second_page(self):
        response = self.client.get(f"/api/brands/{self.brand_id}/orders?page=2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["brand"], {"id": self.brand_id, "name": "訂單 API 測試品牌"})
        self.assertEqual(body["orders"]["page"], 2)
        self.assertEqual(body["orders"]["page_size"], 12)
        self.assertEqual(body["orders"]["total"], 13)
        self.assertEqual(len(body["orders"]["items"]), 1)
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
        self.assertEqual(response.json(), {"detail": "找不到品牌"})


if __name__ == "__main__":
    unittest.main()
