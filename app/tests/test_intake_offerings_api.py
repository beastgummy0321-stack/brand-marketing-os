"""app/tests/test_intake_offerings_api.py — 精靈第 3 步「賣什麼與數字」JSON API（F05-I07）。

因果鏈：`create_product`／`save_product_economics` 是唯一寫入者（ARCHITECTURE.md §8 第 1 條），
這裡只驗證這支路由把「母產品＋賣法」的畫面形狀正確轉成那兩張表的列，不重新測 facade 本身
（facade 自己的規則已經在 `test_brand_intelligence*.py` 測過）。
"""

import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-offerings-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402

_SEQ = [0]


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)

    def _brand_name(self) -> str:
        _SEQ[0] += 1
        return f"虛構建檔offerings測試品牌{_SEQ[0]}"

    def _create_full(self) -> str:
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "description": "一句測試用的品牌描述文字。",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        return body["brand_id"]

    def _post(self, brand_id: str, offerings: list):
        return self.client.post(
            f"/api/intake/brands/{brand_id}/offerings", json={"offerings": offerings},
        )


class OfferingsPostTest(_Base):
    def test_parent_with_two_variants(self):
        bid = self._create_full()
        resp = self._post(bid, [{
            "parent": {"name": "薑黃錠"},
            "variants": [
                {"label": "單瓶", "selling_price": 600,
                 "unit_variable_cost": 200, "shipping_cost": 80},
                {"label": "3 入組", "selling_price": 1600,
                 "unit_variable_cost": 550, "shipping_cost": 80},
            ],
        }])
        self.assertEqual(resp.status_code, 204)

        products = bi_repo.list_products(web.conn, bid)
        self.assertEqual(len(products), 3)
        parent = next(p for p in products if p["parent_id"] is None)
        variants = [p for p in products if p["parent_id"] == parent["id"]]
        self.assertEqual(len(variants), 2)
        for variant in variants:
            econ = bi_repo.get_product_economics(web.conn, bid, variant["id"])
            self.assertIsNotNone(econ)
            self.assertEqual(econ["currency"], "TWD")

    def test_assumptions_round_trip(self):
        bid = self._create_full()
        resp = self._post(bid, [{
            "parent": {"name": "薑黃錠"},
            "variants": [{
                "label": "單瓶", "selling_price": 600,
                "unit_variable_cost": 330, "shipping_cost": 80,
                "assumptions": ["cost"],
            }],
        }])
        self.assertEqual(resp.status_code, 204)
        get_resp = self.client.get(f"/api/intake/brands/{bid}/offerings")
        self.assertEqual(get_resp.status_code, 200)
        offerings = get_resp.json()["data"]["offerings"]
        variant = next(o for o in offerings if o["parent_id"] is not None)
        self.assertEqual(variant["assumptions"], ["cost"])

    def test_service_close_rate_round_trip(self):
        bid = self._create_full()
        resp = self._post(bid, [{
            "parent": {"name": "顧問諮詢"},
            "variants": [{
                "label": "單次諮詢", "selling_price": 5000, "unit_variable_cost": 0,
                "shipping_cost": 0, "close_rate": 0.2,
            }],
        }])
        self.assertEqual(resp.status_code, 204)
        get_resp = self.client.get(f"/api/intake/brands/{bid}/offerings")
        offerings = get_resp.json()["data"]["offerings"]
        variant = next(o for o in offerings if o["parent_id"] is not None)
        self.assertEqual(variant["close_rate"], 0.2)

    def test_missing_shipping_cost_returns_400_with_variant_name(self):
        bid = self._create_full()
        resp = self._post(bid, [{
            "parent": {"name": "薑黃錠"},
            "variants": [{"label": "3 入組", "selling_price": 1600, "unit_variable_cost": 550}],
        }])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("薑黃錠 · 3 入組", resp.json()["error"])
        self.assertIn("運費", resp.json()["error"])

    def test_empty_offerings_returns_400(self):
        bid = self._create_full()
        resp = self._post(bid, [])
        self.assertEqual(resp.status_code, 400)


class OfferingsGetTest(_Base):
    def test_get_includes_product_without_economics_and_benchmarks(self):
        bid = self._create_full()
        bi_repo.create_product(web.conn, bid, name="初掃建立但沒填數字的商品", actor="test")

        resp = self.client.get(f"/api/intake/brands/{bid}/offerings")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        offering = next(o for o in body["offerings"] if o["name"] == "初掃建立但沒填數字的商品")
        self.assertIsNone(offering["selling_price"])

        for key in ("gross_margin", "shipping_cost", "close_rate"):
            self.assertIn(key, body["benchmarks"])
            self.assertTrue(body["benchmarks"][key]["source_text"])


if __name__ == "__main__":
    unittest.main()
