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
