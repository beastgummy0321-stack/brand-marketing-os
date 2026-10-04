"""HTTP cache reads are read-only, refreshes only enqueue, unbound accounts are refused a
refresh, and nothing here calls the platform. F49 Contract O: every read serves the one sync
outcome."""

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

    def test_get_is_read_only_and_refresh_only_enqueues(self):
        # F49 Contract O: the listing GET never requests a read; it serves the account's job and
        # outcome (none yet: `not_read`). The refresh POST enqueues; neither calls the platform.
        listing = self.url + "/existing-campaigns?platform=other&source_account=account"
        response = self.client.get(listing)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["items"], [])
        self.assertIsNone(body["job"])
        self.assertEqual((body["outcome"]["state"], body["outcome"]["code"]), ("empty", "not_read"))
        refreshed = self.client.post(
            self.url + "/existing-campaigns/refresh",
            json={"platform": "other", "source_account": "account"},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(self.reader.calls, [])
        job = refreshed.json()["job"]
        body = self.client.get(listing).json()
        self.assertEqual(body["job"]["id"], job["id"])
        self.assertEqual(body["outcome"]["state"], "running")
        read = self.client.get(self.url + "/sync-jobs/" + job["id"])
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.json()["outcome"]["state"], "running")
        self.reader.connected = False
        self.assertFalse(self.client.get(self.url + "/sync-jobs/" + job["id"]).json()["connected"])
        self.assertEqual(
            self.client.post(
                self.url + "/existing-campaigns/refresh",
                json={"platform": "other", "source_account": "account"},
            ).status_code,
            409,
        )

    def test_unreadable_account_still_lists_its_cached_rows(self):
        # F49 Contract O: a disconnected account answers 200 with what was cached, `job: null`
        # and a failed outcome naming why -- never a 409 because a read could not be requested.
        from app.ads import external_repository as external

        external.cache_listing(self.conn, self.org, self.brand, "other", "account", {
            "platform": "other", "source_account": "account", "native_kind": "campaign",
            "native_id": "cached", "name": "快取的活動",
        })
        self.conn.commit()
        self.reader.connected = False
        response = self.client.get(
            self.url + "/existing-campaigns?platform=other&source_account=account"
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([i["native_id"] for i in body["items"]], ["cached"])
        self.assertIsNone(body["job"])
        self.assertEqual(body["outcome"]["state"], "failed")
        self.assertEqual(body["outcome"]["code"], "disconnected")
        self.assertIn(sync.SYNC_REASONS["disconnected"], body["outcome"]["text"])

    def test_job_read_scopes_its_outcome_to_a_campaign(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        tasks = {
            **{k: {**t, "status": "succeeded", "rows": 1} for k, t in job["tasks"].items()},
            "c1:observations": {"section": "observations", "campaign_id": "c1",
                                "status": "failed", "error_code": "permission_denied"},
            "c2:observations": {"section": "observations", "campaign_id": "c2",
                                "status": "succeeded", "rows": 4},
        }
        self.conn.execute(
            "UPDATE ads_external_sync_job SET tasks=%s,status='partial' WHERE id=%s",
            (db.jsonb(tasks), job["id"]),
        )
        self.conn.commit()
        read = lambda q: self.client.get(self.url + "/sync-jobs/" + job["id"] + q).json()  # noqa: E731
        self.assertEqual(read("")["outcome"]["state"], "partial")
        self.assertEqual(read("?campaign_id=c1")["outcome"]["code"], "permission_denied")
        self.assertEqual(read("?campaign_id=c2")["outcome"]["state"], "found")

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
        # Every requested job is served (`job` = the first, for callers not yet on `jobs`).
        body = response.json()
        self.assertEqual(len(body["jobs"]), len(request.call_args_list))
        self.assertEqual(body["job"], body["jobs"][0])

    def test_two_account_draft_names_both_jobs_and_the_worst_outcome(self):
        # F49 Contract O (drill-11 #14): a draft re-reads every bound account; its outcome is the
        # worst over both jobs, and names both.
        from app.ads import repository

        accounts = self.reader.accounts
        self.reader.accounts = lambda conn, org, brand: [
            *accounts(conn, org, brand), {**accounts(conn, org, brand)[0], "account_id": "second"},
        ]
        campaign = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": "兩帳戶草稿", "goal_text": "賣商品", "objective": "購買",
        })["id"]
        self.conn.commit()
        outcome_url = self.url + f"/campaigns/{campaign}/sync-outcome"
        before = self.client.get(outcome_url).json()
        self.assertEqual((before["state"], before["code"], before["job_ids"]),
                         ("empty", "not_read", []))
        response = self.client.post(self.url + f"/campaigns/{campaign}/sync", json={})
        self.assertEqual(response.status_code, 200, response.text)
        jobs = response.json()["jobs"]
        self.assertEqual({j["source_account"] for j in jobs}, {"account", "second"})
        self.assertEqual(response.json()["job"], jobs[0])
        self.assertEqual(self.client.get(outcome_url).json()["state"], "running")
        # One account read cleanly, the other failed: the campaign's outcome is the failure.
        for job in jobs:
            failed = job["source_account"] == "second"
            tasks = {
                key: {**task, "status": "failed", "error_code": "permission_denied"} if failed
                else {**task, "status": "succeeded", "rows": 2}
                for key, task in job["tasks"].items()
            }
            self.conn.execute(
                "UPDATE ads_external_sync_job SET tasks=%s,last_success_at=now() WHERE id=%s",
                (db.jsonb(tasks), job["id"]),
            )
        self.conn.commit()
        body = self.client.get(outcome_url).json()
        self.assertEqual(set(body["job_ids"]), {j["id"] for j in jobs})
        self.assertEqual((body["state"], body["code"]), ("failed", "permission_denied"))
        self.assertIn(sync.SYNC_REASONS["permission_denied"], body["text"])
        self.assertIsNotNone(body["last_success_at"])
        self.assertEqual(
            self.client.get(self.url + "/campaigns/missing/sync-outcome").status_code, 404
        )
