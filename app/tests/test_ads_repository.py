"""app/tests/test_ads_repository.py — F24-I01 falsifier: `list_campaigns` cards carry
`data.sync`, the same shape and rules as `triage.classify()`'s own `data.sync`
(`repository.campaign_sync_state`, shared with `triage.py::_data_view`) -- never a second,
divergent definition of "connected"/"synced" for the home's cards.
"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import channels, repository
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.main import app


class _Reader:
    """Stand-in source capability (same pattern as `test_ads_triage.py::_Reader`): reports one
    bound account, `act_1`."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": "Asia/Taipei"}]


class ListCampaignsSyncDataTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F24 list_campaigns 測試", actor="test",
            client_name=None,
        )["id"]
        self.reader = _Reader()
        patcher = patch.object(
            channels, "external_reader", side_effect=lambda platform: self.reader,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _campaign(self, *, account="act_1", native_id="c1"):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="卡片同步測試",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": account, "native_kind": "campaign",
             "native_id": native_id},
        )
        self.conn.commit()
        return campaign_id

    def _card(self, campaign_id):
        cards = repository.list_campaigns(self.conn, self.org, self.brand)
        return next(card for card in cards if card["id"] == campaign_id)

    def test_get_old_accepted_basis_adds_unknown_evidence_without_rewriting_snapshot(self):
        product = brands.create_product(self.conn, self.brand, name="Original product",
                                        actor="test")
        campaign = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": "Accepted old plan", "goal_text": "x", "objective": "購買",
            "start_date": "2026-10-01", "end_date": "2026-10-10", "status": "ready",
            "budget_planned": 3000, "budget_scenario": "custom",
            "context_json": {"product_ids": [product["id"]]},
        }, created_by="test")
        original = {"strategy": {"allocation": [], "why": [], "unknowns": [], "alternatives": []},
                    "basis": {"planner_context": {"product_id": product["id"]},
                              "learnings": [{"id": "old-id", "text": "Accepted original text",
                                             "level": "validated"}],
                              "ranked_learnings": {"campaigns": [{"sell_way_id": product["id"],
                                  "rows": [{"learning_id": "old-rank", "ad_name": "Original rank",
                                            "rank": 1, "spend": 500, "sales": 2}]}]}}}
        repository.save_strategy(self.conn, self.org, self.brand, campaign["id"],
                                 budget_basis_json=deepcopy(original))
        self.conn.commit()
        response = TestClient(app).get(f"/api/ads/brands/{self.brand}/campaigns/{campaign['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["campaign"]["status"], "ready")
        self.assertEqual(response.json()["campaign"]["budget_planned"], 3000)
        shown = response.json()["campaign"]["budget_basis_json"]["basis"]
        self.assertEqual(shown["learnings"][0]["text"], "Accepted original text")
        self.assertEqual(shown["learnings"][0]["evidence"]["allowed_uses"], [])
        self.assertEqual(shown["evidence_context"]["eligible_count"], 0)
        rank = shown["ranked_learnings"]["campaigns"][0]["rows"][0]
        self.assertEqual((rank["rank"], rank["spend"], rank["sales"]), (1, 500, 2))
        self.assertEqual(rank["evidence"]["allowed_uses"], [])
        self.assertEqual(repository.get_campaign(self.conn, self.org, self.brand, campaign["id"])[
            "budget_basis_json"], original)

    def test_never_synced_card_carries_never_state(self):
        campaign_id = self._campaign()
        card = self._card(campaign_id)
        self.assertEqual(
            card["data"], {
                "sync": {"state": "never", "error": None, "last_success_at": None},
                "capacity": {"daily_budget": None, "currency": None, "target": None,
                             "can_support": None, "active_ads": 0},
            },
        )

    def test_ok_card_carries_ok_state(self):
        campaign_id = self._campaign()
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        card = self._card(campaign_id)
        self.assertEqual(card["data"]["sync"]["state"], "ok")

    def test_disconnected_card(self):
        campaign_id = self._campaign(account="act_gone")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        card = self._card(campaign_id)
        self.assertEqual(card["data"]["sync"]["state"], "disconnected")

    def test_shared_accounts_cache_reads_platform_once_per_list_call(self):
        # Two campaigns, same platform/account -- `list_campaigns` must share one
        # `reader.accounts()` read across the whole list (Done #1: "never per ad", extended here
        # to "never per campaign" for the card loop).
        for index in range(2):
            campaign_id = self._campaign(native_id=f"c{index}")
            external.record_sync(
                self.conn, self.org, self.brand, campaign_id, section="observations",
                state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                       "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
            )
        self.conn.commit()
        with patch.object(self.reader, "accounts", wraps=self.reader.accounts) as spy:
            repository.list_campaigns(self.conn, self.org, self.brand)
        spy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
