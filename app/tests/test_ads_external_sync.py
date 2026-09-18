"""Real isolated PostgreSQL + fake source capability, no platform writes or LLM."""

import unittest
from datetime import date
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
        self.assertIsNone(job["tasks"]["list"].get("error_code"))
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

    def test_worker_refreshes_snapshot_after_lock(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        original = repo.get_job
        calls = 0

        def stale_first(conn, org, brand, job_id):
            nonlocal calls
            current = original(conn, org, brand, job_id)
            calls += 1
            if calls == 1:
                conn.execute(
                    "UPDATE ads_external_sync_job SET tasks=%s,status='succeeded' WHERE id=%s",
                    (
                        db.jsonb(
                            {"list": {"section": "list", "status": "succeeded", "cursor": None}}
                        ),
                        job_id,
                    ),
                )
                conn.commit()
            return current

        with patch.object(repo, "get_job", side_effect=stale_first):
            sync.run_sync(self.org, self.brand, job["id"])
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(
            original(self.conn, self.org, self.brand, job["id"])["status"], "succeeded"
        )

    def test_parallel_import_returns_one_workspace(self):
        from concurrent.futures import ThreadPoolExecutor

        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        self.conn.commit()

        def do_import():
            with db.connection() as conn:
                result = repo.import_cached(
                    conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
                )
                conn.commit()
                return result["id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: do_import(), range(2)))
        self.assertEqual(ids[0], ids[1])

    def test_partial_creative_failure_retains_prior_success(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        prior = repo.external_view(self.conn, self.org, self.brand, campaign["id"])
        with patch.object(self.reader, "read_creatives", side_effect=ValueError("failed")):
            job = self.run_pages(
                sync.request_sync(self.conn, self.org, self.brand, "other", "account")
            )
        view = repo.external_view(self.conn, self.org, self.brand, campaign["id"])
        self.assertEqual(job["status"], "partial")
        self.assertEqual(
            view["sync"]["creatives"]["last_success_at"],
            prior["sync"]["creatives"]["last_success_at"],
        )
        self.assertEqual(
            [e["creative"] for e in view["entities"]], [e["creative"] for e in prior["entities"]]
        )

    def test_new_window_request_during_read_is_not_overwritten(self):
        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.conn.commit()
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        original = self.reader.list_existing

        def append_request(*args, **kwargs):
            with db.connection() as conn:
                sync.request_sync(
                    conn,
                    self.org,
                    self.brand,
                    "other",
                    "account",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 2),
                )
            return original(*args, **kwargs)

        with patch.object(self.reader, "list_existing", side_effect=append_request):
            sync.run_sync(self.org, self.brand, job["id"])
        current = repo.get_job(self.conn, self.org, self.brand, job["id"])
        key = campaign["id"] + ":observations:2026-01-01:2026-01-02"
        self.assertEqual(current["tasks"][key]["status"], "pending")

    def test_legacy_binding_reused_only_for_its_platform_and_kind(self):
        from app.ads import repository

        self.run_pages(sync.request_sync(self.conn, self.org, self.brand, "other", "account"))
        campaign = repository.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {"name": "內部", "goal_text": "目標", "objective": "購買", "success_metric": "cpa"},
        )
        repository.bind_campaign(
            self.conn,
            self.org,
            self.brand,
            campaign["id"],
            external_id="root",
            external_name="來源",
            external_status="PAUSED",
        )
        self.conn.commit()
        foreign = repo.import_cached(
            self.conn, self.org, self.brand, "other", "account", "portfolio", "root", "test"
        )
        self.assertNotEqual(foreign["id"], campaign["id"])
        repo.cache_listing(
            self.conn,
            self.org,
            self.brand,
            "meta",
            "account",
            self.reader.root() | {"platform": "meta", "native_kind": "campaign"},
        )
        result = repo.import_cached(
            self.conn, self.org, self.brand, "meta", "account", "campaign", "root", "test"
        )
        self.assertEqual(result["id"], campaign["id"])
        self.assertEqual(result["origin"], "internal")

    def test_contending_account_job_remains_durable_until_unlock(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "other", "account")
        lock = f"external-account:{self.org}:other:account"
        with db.connection() as holder:
            holder.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (lock,))
            holder.commit()
            try:
                sync.run_sync(self.org, self.brand, job["id"])
                self.assertEqual(self.reader.calls, [])
                self.assertEqual(
                    repo.get_job(self.conn, self.org, self.brand, job["id"])["status"], "pending"
                )
            finally:
                holder.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
                holder.commit()
        result = self.run_pages(job)
        self.assertEqual(result["status"], "succeeded")
