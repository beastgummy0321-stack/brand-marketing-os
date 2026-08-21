# -*- coding: utf-8 -*-
"""待認領廣告 JSON API：回應形狀、認領／忽略與品牌隔離。"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
from app.ads import handoff as ads_handoff
from app.brand_intelligence import repository as bi_repo
from app.core.db import new_id, now_iso

ACTOR = "測試員"


class ClaimsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.commit()
        self.brand_id = bi_repo.create_brand(main.conn, name=f"認領測試{uuid.uuid4().hex[:8]}", client_name=None, actor=ACTOR)["id"]
        self.account_id = ads_handoff._ensure_ad_account(main.conn, f"act_claims_{uuid.uuid4().hex[:8]}", now_iso())
        self.suggested_id = self._insert_campaign("夏季全站9折_轉換", "suggested", self.brand_id)
        self.unclaimed_id = self._insert_campaign("秋季新品", "unclaimed", None)
        self.other_brand_id = bi_repo.create_brand(main.conn, name=f"隔壁品牌{uuid.uuid4().hex[:8]}", client_name=None, actor=ACTOR)["id"]
        self.other_suggested_id = self._insert_campaign("隔壁品牌的活動", "suggested", self.other_brand_id)
        main.conn.commit()

    def _insert_campaign(self, name: str, status: str, suggested_brand_id: str | None) -> str:
        campaign_id = new_id("dsc")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO discovered_campaign (id, ad_account_id, platform, meta_campaign_id, campaign_name,"
            " first_seen_at, last_seen_at, suggested_brand_id, claim_status, created_at, updated_at)"
            " VALUES (?, ?, 'meta', ?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, self.account_id, f"meta_{campaign_id}", name, ts, ts, suggested_brand_id, status, ts, ts),
        )
        return campaign_id

    def _items(self) -> list[dict]:
        response = self.client.get(f"/api/campaigns/brands/{self.brand_id}/claims")
        self.assertEqual(response.status_code, 200)
        self.assertIn("generated_at", response.json())
        return response.json()["data"]["items"]

    def test_get_returns_suggested_and_unclaimed_with_correct_flags(self):
        items = self._items()
        self.assertEqual({item["id"] for item in items}, {self.suggested_id, self.unclaimed_id})
        self.assertNotIn(self.other_suggested_id, {item["id"] for item in items})
        flags = {item["id"]: item["is_suggested"] for item in items}
        self.assertTrue(flags[self.suggested_id])
        self.assertFalse(flags[self.unclaimed_id])

    def test_claim_removes_item_and_keeps_legacy_page_available(self):
        response = self.client.post(f"/api/campaigns/brands/{self.brand_id}/claims/{self.suggested_id}/claim")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "「夏季全站9折_轉換」記成這個品牌的了，它的成效數字會算進來。"})
        self.assertNotIn(self.suggested_id, {item["id"] for item in self._items()})

    def test_ignore_removes_item(self):
        response = self.client.post(f"/api/campaigns/brands/{self.brand_id}/claims/{self.unclaimed_id}/ignore")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "好，這個活動不算這個品牌的。"})
        self.assertNotIn(self.unclaimed_id, {item["id"] for item in self._items()})

    def test_missing_brand_is_404(self):
        response = self.client.get("/api/campaigns/brands/missing/claims")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "找不到品牌"})

    def test_value_error_is_detail_400(self):
        response = self.client.post(f"/api/campaigns/brands/{self.brand_id}/claims/no-such-campaign/claim")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "找不到這個廣告活動"})
