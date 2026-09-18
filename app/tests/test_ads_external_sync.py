"""Real isolated PostgreSQL + fake source capability, no platform writes or LLM."""

import unittest
from unittest.mock import patch

from app.ads import external_repository as repo
from app.ads import external_sync as sync
from app.ads.adapters.external import SourcePage
from app.brand_intelligence import repository as brands
from app.core import db


def setup_brand(conn):
    org = db.DEV_ORG_ID
    brand = brands.create_brand(conn, org_id=org, name="來源測試", client_name=None, actor="test")[
        "id"
    ]
    conn.commit()
    return org, brand


class Reader:
    def __init__(self):
        self.connected = True
        self.calls = []
        self.fail_second = False

    def accounts(self, conn, org, brand):
        return (
            [{"account_id": "account", "currency": "TWD", "name": "來源"}] if self.connected else []
        )

    def root(self, native_id="root", **values):
        return {
            "platform": "other",
            "source_account": "account",
            "native_kind": "portfolio",
            "native_id": native_id,
            "name": "暫停但存在",
            "native_status": "PAUSED",
            **values,
        }

    def list_existing(self, *args, cursor=None, **kwargs):
        self.calls.append(("list", cursor))
        if cursor and self.fail_second:
            raise ValueError("private-provider-message")
        return SourcePage(
            [self.root("second" if cursor else "root")], None if cursor else {"after": "page2"}
        )

    def read_structure(self, *args, native_id, **kwargs):
        self.calls.append(("structure", None))
        return SourcePage(
            [
                self.root(native_id),
                self.root(
                    "child",
                    native_kind="line",
                    parent_native_kind="portfolio",
                    parent_native_id=native_id,
                ),
            ]
        )

    def read_creatives(self, *args, **kwargs):
        return SourcePage(
            [
                {
                    "platform": "other",
                    "source_account": "account",
                    "native_kind": "line",
                    "native_id": "child",
                    "creative": {"kind": "video", "video_original": None},
                }
            ]
        )

    def read_observations(self, *args, start, **kwargs):
        return SourcePage(
            [
                {
                    "native_kind": "line",
                    "native_id": "child",
                    "day": start,
                    "metric_scope": "line",
                    "attribution_key": "own-window",
                    "currency": "TWD",
                    "source": "other",
                    "spend": 0,
                    "purchases": None,
                }
            ]
        )


class ExternalSyncTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org, self.brand = setup_brand(self.conn)
        self.reader = Reader()
        self.patches = [
            patch.object(sync.channels, "external_reader", return_value=self.reader),
            patch.object(sync.background, "enqueue", return_value=True),
            patch.object(sync.background, "is_active", return_value=False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def run_pages(self, job):
        for _ in range(12):
            sync.run_sync(self.org, self.brand, job["id"])
            job = repo.get_job(self.conn, self.org, self.brand, job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
        self.fail("cursor did not terminate")

    def test_second_page_failure_resumes_and_preserves_cache(self):
        self.reader.fail_second = True
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        job = self.run_pages(job)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["tasks"]["list"]["cursor"], {"after": "page2"})
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 1
        )
        self.assertNotIn("private-provider-message", str(job))
        self.reader.fail_second = False
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 2
        )
        self.assertEqual(self.reader.calls[-1], ("list", {"after": "page2"}))

    def test_generic_adapter_import_and_source_observations(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        first = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        duplicate = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.assertEqual(first["id"], duplicate["id"])
        self.conn.commit()
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.assertEqual(job["status"], "succeeded", job["tasks"])
        view = repo.external_view(self.conn, self.org, self.brand, first["id"])
        self.assertEqual(len(view["entities"]), 2)
        self.assertEqual(view["observations"][0]["spend"], 0)
        self.assertIsNone(view["observations"][0]["purchases"])

    def test_revoked_account_blocks_pending_read_without_erasing_data(self):
        job = self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        self.reader.connected = False
        job = self.run_pages(job)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(
            len(repo.listing(self.conn, self.org, self.brand, "other", "account")["items"]), 2
        )
        with self.assertRaisesRegex(ValueError, "解除"):
            sync.request_sync(self.conn, self.org, self.brand, "other", "account")

    def test_requests_merge_and_jobs_remain_brand_scoped(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        again = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        self.assertEqual(job["id"], again["id"])
        _, other = setup_brand(self.conn)
        separate = sync.request_sync(self.conn, self.org, other, "other", "account")
        self.assertNotEqual(job["id"], separate["id"])
        with self.assertRaises(ValueError):
            repo.get_job(self.conn, self.org, other, job["id"])
