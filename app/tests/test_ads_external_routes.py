"""HTTP cache reads enqueue work, reject unbound accounts, and never call the platform."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ads import external_sync as sync
from app.core import db
from app.tests.test_ads_external_sync import Reader, setup_brand


class ExternalRoutesTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org, self.brand = setup_brand(self.conn)
        self.reader = Reader()
        self.client = TestClient(main.app)
        self.url = f"/api/ads/brands/{self.brand}"
        for p in (
            patch.object(sync.channels, "external_reader", return_value=self.reader),
            patch.object(sync.background, "enqueue", return_value=True),
            patch.object(sync.background, "is_active", return_value=False),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_get_returns_immediately_and_only_enqueues(self):
        response = self.client.get(
            self.url + "/existing-campaigns?platform=other&source_account=account"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(self.reader.calls, [])
        job = response.json()["job"]
        self.assertEqual(self.client.get(self.url + "/sync-jobs/" + job["id"]).status_code, 200)
        self.reader.connected = False
        self.assertFalse(self.client.get(self.url + "/sync-jobs/" + job["id"]).json()["connected"])
        self.assertEqual(
            self.client.post(
                self.url + "/existing-campaigns/refresh",
                json={"platform": "other", "source_account": "account"},
            ).status_code,
            409,
        )

    def test_listing_items_carry_the_workspace_campaign_they_are_bound_to(self):
        """F47-I08 (drill-10 c4-08): a listed platform campaign already in a workspace carries
        that campaign's id; one not imported yet carries null."""
        from app.ads import external_repository as external

        for native_id in ("bound", "free"):
            external.cache_listing(self.conn, self.org, self.brand, "other", "account", {
                "platform": "other", "source_account": "account", "native_kind": "campaign",
                "native_id": native_id, "name": native_id,
            })
        campaign = external.create_imported_campaign(self.conn, self.org, self.brand, name="已納入")
        external.upsert_entity(self.conn, self.org, self.brand, campaign["id"], {
            "platform": "other", "source_account": "account", "native_kind": "campaign",
            "native_id": "bound",
        })
        self.conn.commit()
        response = self.client.get(
            self.url + "/existing-campaigns?platform=other&source_account=account"
        )
        self.assertEqual(response.status_code, 200, response.text)
        bound = {i["native_id"]: i["campaign_id"] for i in response.json()["items"]}
        self.assertEqual(bound, {"bound": campaign["id"], "free": None})

    def test_unread_or_wrong_account_import_is_refused(self):
        for account in ("account", "foreign"):
            response = self.client.post(
                self.url + "/imports",
                json={
                    "platform": "other",
                    "source_account": account,
                    "native_kind": "portfolio",
                    "native_id": "not-read",
                },
            )
            self.assertEqual(response.status_code, 409, response.text)


class CampaignWithoutRootTest(unittest.TestCase):
    setUp = ExternalRoutesTest.setUp

    def test_campaign_not_yet_on_platform_refreshes_the_bound_account(self):
        # Drill 5: a first-launch handoff has no native root; refreshing candidates must read the
        # brand's bound account (where the just-built campaign is listed), not 409.
        from app.ads import repository

        campaign = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": "新活動", "goal_text": "賣商品", "objective": "購買",
        })["id"]
        self.conn.commit()
        with patch.object(sync, "request_sync", return_value={"id": "job"}) as request:
            response = self.client.post(self.url + f"/campaigns/{campaign}/sync", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({c.args[4] for c in request.call_args_list}, {"account"})
