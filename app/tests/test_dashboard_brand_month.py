"""app/tests/test_dashboard_brand_month.py — 票 06：品牌頁本月花費／營收／毛利／ROAS 併桌。

五件事，只寫這五件（docs/workflow-diet.md 第 4 條）：
1. 金額正確：花費（app.meta）＋營收（app.orders 訂單實收）＋毛利（逐 SKU 成本，部分
   SKU 沒登記成本時只算已知的那部分）＋ROAS（營收 ÷ 花費）四個數字對得上手算的真實值。
2. 租戶隔離：另一個組織讀不到這個品牌的月報，404。
3. API 契約：{data, generated_at} 信封＋データ欄位齊全。
4. 資料正確性：沒有訂單＝空態（None，不是假 0）；SKU 成本一個都沒登記＝毛利 None；
   沒有花費資料＝ROAS None（不是 0，鐵則 16「沒得算」跟「等於 0」是兩件事）。
5. 票 12（ADR 0035）：revenue 是全通路加總（官網＋平台商店＋離線一個數字），
   marketplace_uncalibrated 只在視窗內出現過 marketplace 列時才是 true。

畫面行為不寫單元測試（見 frontend/e2e/smoke.spec.ts）。
"""

import os
import unittest
from datetime import date
from uuid import uuid4

os.environ["BRAND_OS_TODAY"] = "2026-08-05"  # 凍結時鐘，比照 test_dashboard_overview.py

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.identity import repository as identity_repo  # noqa: E402
from app.meta import repository as meta_repo  # noqa: E402
from app.orders import channel as orders_channel  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

from .identity_test_helpers import mint_hs256  # noqa: E402

ACTOR = "測試員"
TODAY = "2026-08-05"


def _make_org(suffix: str) -> tuple:
    """比照 test_meta_daily_spend.py `_make_org`：獨立組織＋能登入的 JWT。"""
    org_id = f"org_month_test_{suffix}_{uuid4().hex[:10]}"
    main.conn.execute(
        "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
        " ON CONFLICT (id) DO NOTHING",
        (org_id, org_id),
    )
    user_id = uuid4()
    email = f"month-test-{suffix}-{user_id.hex[:8]}@example.com"
    identity_repo.create_user(main.conn, user_id, email)
    identity_repo.create_membership(main.conn, org_id, user_id, "owner")
    main.conn.commit()
    return org_id, mint_hs256(sub=str(user_id), email=email)


def _headers(token: str, org_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}


class BrandMonthMoneyTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.org_id = coredb.DEV_ORG_ID

    def _brand(self, name: str) -> str:
        return bi_repo.create_brand(
            main.conn, name=f"{name}{uuid4().hex[:8]}", client_name=None, actor=ACTOR,
            org_id=self.org_id,
        )["id"]

    def _bind_account_with_spend(self, brand_id: str, spend: float) -> None:
        meta_repo.upsert_accounts(main.conn, self.org_id, [
            {"account_id": f"acct-{uuid4().hex[:8]}", "name": "測試帳號", "currency": "TWD"},
        ])
        main.conn.commit()
        account = meta_repo.list_accounts(main.conn, self.org_id)[-1]
        meta_repo.bind(main.conn, self.org_id, brand_id, account["id"])
        meta_repo.upsert_campaign_spend(
            main.conn, self.org_id, account["id"], date(2026, 8, 2),
            [{"campaign_id": "c1", "campaign_name": "c1", "spend": spend,
              "impressions": 100, "clicks": 10, "roas": None}],
        )
        main.conn.commit()

    def test_money_math_and_envelope_shape(self):
        """1200 元營收（一筆訂單）、逐 SKU 毛利只算已登記成本的那個 SKU、
        花費 2000 元、ROAS＝營收÷花費，四個數字都要對得上。"""
        brand_id = self._brand("併桌品牌")
        orders_repo.save_orders(
            main.conn, brand_id,
            [{"order_number": "ORD-1", "order_date": "2026-08-02", "total_amount": 1000,
              "refunded_amount": 0,
              "items": [{"sku": "SKU-A", "item_price": 100, "quantity": 5},
                        {"sku": "SKU-B", "item_price": 50, "quantity": 4}]}],
            source="test", actor=ACTOR)
        orders_repo.set_sku_cost(main.conn, brand_id, "SKU-A", 30, actor=ACTOR, today=TODAY)
        # SKU-B 故意不登記成本。
        self._bind_account_with_spend(brand_id, 2000)

        resp = self.client.get(f"/api/dashboard/brands/{brand_id}/month")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        data = body["data"]

        self.assertAlmostEqual(data["spend"], 2000.0, places=2)
        self.assertAlmostEqual(data["revenue"], 1000.0, places=2)
        # 只有 SKU-A 有登記成本：(100*5 - 30*5) = 350；SKU-B 的 200 元營收不算進毛利。
        self.assertAlmostEqual(data["margin"], 350.0, places=2)
        self.assertEqual(data["margin_unknown_sku_count"], 1)
        self.assertAlmostEqual(data["roas"], 0.5, places=2)
        self.assertTrue(data["has_orders"])

    def test_no_orders_is_empty_state_not_zero(self):
        """完全沒有訂單：營收／毛利／ROAS 都是 None（累積中），不是假的 0。"""
        brand_id = self._brand("沒訂單品牌")
        resp = self.client.get(f"/api/dashboard/brands/{brand_id}/month")
        data = resp.json()["data"]
        self.assertFalse(data["has_orders"])
        self.assertIsNone(data["revenue"])
        self.assertIsNone(data["margin"])
        self.assertEqual(data["margin_unknown_sku_count"], 0)
        self.assertIsNone(data["roas"])

    def test_margin_none_when_no_sku_cost_registered_at_all(self):
        """有訂單、有 SKU，但一個成本都沒登記：毛利誠實回 None，不是假裝算出 0。"""
        brand_id = self._brand("沒登記成本品牌")
        orders_repo.save_orders(
            main.conn, brand_id,
            [{"order_number": "ORD-2", "order_date": "2026-08-03", "total_amount": 500,
              "refunded_amount": 0,
              "items": [{"sku": "SKU-C", "item_price": 50, "quantity": 10}]}],
            source="test", actor=ACTOR)
        resp = self.client.get(f"/api/dashboard/brands/{brand_id}/month")
        data = resp.json()["data"]
        self.assertTrue(data["has_orders"])
        self.assertAlmostEqual(data["revenue"], 500.0, places=2)
        self.assertIsNone(data["margin"])
        self.assertEqual(data["margin_unknown_sku_count"], 1)

    def test_roas_none_when_no_spend(self):
        """有營收、沒有綁定 Meta 帳號（花費＝0）：ROAS「沒得算」回 None，不是 0。"""
        brand_id = self._brand("沒花費品牌")
        orders_repo.save_orders(
            main.conn, brand_id,
            [{"order_number": "ORD-3", "order_date": "2026-08-02", "total_amount": 800,
              "refunded_amount": 0, "items": []}],
            source="test", actor=ACTOR)
        resp = self.client.get(f"/api/dashboard/brands/{brand_id}/month")
        data = resp.json()["data"]
        self.assertAlmostEqual(data["spend"], 0.0, places=2)
        self.assertAlmostEqual(data["revenue"], 800.0, places=2)
        self.assertIsNone(data["roas"])

    def test_other_org_cannot_read_this_brand_month(self):
        brand_id = self._brand("租戶隔離品牌")
        org_b, token_b = _make_org("isolation")
        resp = self.client.get(
            f"/api/dashboard/brands/{brand_id}/month", headers=_headers(token_b, org_b),
        )
        self.assertEqual(resp.status_code, 404)


class CrossChannelRevenueTest(unittest.TestCase):
    """票 12（ADR 0035）：revenue 是全通路加總，marketplace_uncalibrated 只在視窗內
    出現過 marketplace 列時才是 true。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.org_id = coredb.DEV_ORG_ID

    def _brand(self, name: str) -> str:
        return bi_repo.create_brand(
            main.conn, name=f"{name}{uuid4().hex[:8]}", client_name=None, actor=ACTOR,
            org_id=self.org_id,
        )["id"]

    def test_revenue_sums_every_channel_and_flags_marketplace_uncalibrated(self):
        brand_id = self._brand("全通路品牌")
        orders_repo.save_orders(
            main.conn, brand_id,
            [{"order_number": "ORD-CH1", "order_date": "2026-08-02", "total_amount": 1000,
              "refunded_amount": 0, "items": []}],
            source="test", actor=ACTOR)
        orders_channel.record_channel_entry(
            main.conn, brand_id, channel="physical_store", entry_date="2026-08-03",
            revenue=300, quantity=None, note=None, actor=ACTOR)

        data = self.client.get(f"/api/dashboard/brands/{brand_id}/month").json()["data"]
        self.assertAlmostEqual(data["revenue"], 1300.0, places=2)  # 官網 1000 + 實體店 300
        self.assertFalse(data["marketplace_uncalibrated"], "視窗內還沒有平台商店的列")

        orders_channel.record_channel_entry(
            main.conn, brand_id, channel="marketplace", entry_date="2026-08-04",
            revenue=500, quantity=None, note=None, actor=ACTOR)
        data = self.client.get(f"/api/dashboard/brands/{brand_id}/month").json()["data"]
        self.assertAlmostEqual(data["revenue"], 1800.0, places=2)  # 再加平台商店 500
        self.assertTrue(data["marketplace_uncalibrated"])


if __name__ == "__main__":
    unittest.main()
