"""No platform write: fresh parent verification and scoped immutable evidence."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg

from app.ads import (
    asset_binding as binding,
)
from app.ads import (
    asset_binding_repository as repo,
)
from app.ads import (
    external_repository as external,
)
from app.ads import (
    external_sync,
)
from app.ads import user_assets_repository as assets
from app.ads.adapters.meta_read import MetaReader
from app.brand_intelligence import repository as brands
from app.core import db


class Fixture:
    def __init__(self, test):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="版本", actor="test", client_name=None
        )["id"]
        self.account = self.brand
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="native"
        )["id"]
        self.root = self.entity("root", "portfolio")
        self.leaf = self.entity(
            "leaf",
            "unit",
            parent_native_kind="portfolio",
            parent_native_id="root",
            creative={
                "kind": "image",
                "fields": {"id": "creative-one", "image_hash": "not-sha256"},
            },
        )
        self.conn.commit()
        self.reader = FakeReader(self)
        patch.object(external_sync.channels, "external_reader", return_value=self.reader).start()
        test.addCleanup(patch.stopall)

    def entity(self, native_id, kind, **extra):
        return external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fake",
                "source_account": self.account,
                "native_kind": kind,
                "native_id": native_id,
                **extra,
            },
        )

    def placement(self, copy_fields=None):
        asset_id = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,'key','original.png',"
            "'image/png',1,'ready')",
            (asset_id, self.org, self.brand, asset_id),
        )
        row = assets.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            asset_id,
            copy_fields or {"headline": "原標題", "body": "", "description": "原說明"},
            "test",
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human',"
            "status='manual_ready',suggested_copy=%s WHERE id=%s",
            (db.jsonb({"body": "補齊內文"}), row["id"]),
        )
        self.conn.commit()
        return assets.placement(self.conn, self.org, self.brand, self.campaign, row["id"])

    def verify(self, p, **kwargs):
        return binding.verify(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            p["id"],
            p["revision"],
            self.leaf["id"],
            "test",
            **kwargs,
        )


class FakeReader:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = 0
        self.failure = False
        self.cross = False
        self.prove = False
        self.intervals = []
        self.hook = None

    def accounts(self, conn, org, brand):
        return (
            [{"account_id": self.fixture.account, "timezone_name": "Asia/Taipei"}]
            if org == self.fixture.org and brand == self.fixture.brand
            else []
        )

    def binding_kinds(self):
        return ("unit",)

    def verify_native(self, conn, org, brand, account, **kwargs):
        self.calls += 1
        if self.hook:
            self.hook()
        if self.failure:
            raise ValueError("remote failure")
        f = self.fixture
        leaf = {
            k: f.leaf[k]
            for k in (
                "platform",
                "source_account",
                "native_kind",
                "native_id",
                "parent_native_kind",
                "parent_native_id",
                "creative",
            )
        }
        root = {
            k: f.root[k]
            for k in (
                "platform",
                "source_account",
                "native_kind",
                "native_id",
                "parent_native_kind",
                "parent_native_id",
            )
        }
        if self.cross:
            root["source_account"] = "other"
        proof = {
            "entity": copy.deepcopy(leaf),
            "parents": [root],
            "timezone_name": "Asia/Taipei",
            "continuous_intervals": self.intervals,
        }
        if self.prove:
            proof["media_equivalence"] = {
                "asset_sha256": kwargs["original"]["sha256"],
                "copy_hash": kwargs["original"]["copy_hash"],
                "creative_hash": repo.creative_hash(leaf["creative"]),
                "basis": "fake adapter explicit byte and copy identity contract",
            }
        return proof


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)

    def test_handoff_and_self_report_never_claim_platform_evidence(self):
        f = self.f
        p = f.placement()
        view = binding.handoff(f.conn, f.org, f.brand, f.campaign, p["id"], 1)
        self.assertEqual(view["effective_copy"]["body"], "補齊內文")
        self.assertEqual(view["original_copy"]["body"], "")
        self.assertFalse(view["platform_written"])
        reported = repo.report(f.conn, f.org, f.brand, f.campaign, p["id"], 1, "human")
        self.assertEqual(reported["existence_status"], "self_reported")
        self.assertIsNone(reported["last_verified_at"])
        self.assertEqual(f.reader.calls, 0)

    def test_candidates_scope_fresh_get_and_user_evidence_retained(self):
        f = self.f
        p = f.placement()
        candidates = binding.candidates(
            f.conn, f.org, f.brand, f.campaign, p["id"], 1, platform="fake", account_id=f.account
        )
        self.assertEqual(candidates["candidates"][0]["entity_id"], f.leaf["id"])
        self.assertEqual(f.reader.calls, 0)
        first = f.verify(p, user_verified=True)
        self.assertEqual(first["existence_status"], "platform_confirmed")
        self.assertEqual(first["evidence_level"], "user_verified")
        again = f.verify(p)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["evidence_level"], "user_verified")
        self.assertEqual(f.reader.calls, 2)
        with self.assertRaises(ValueError):
            binding.candidates(
                f.conn, f.org, f.brand, f.campaign, p["id"], 1, platform="fake", account_id="other"
            )

    def test_parent_mismatch_and_failure_keep_previous_success(self):
        f = self.f
        p = f.placement()
        first = f.verify(p)
        f.reader.cross = True
        with self.assertRaises(ValueError):
            f.verify(p)
        row = repo.list_bindings(f.conn, f.org, f.brand, f.campaign, p["id"], 1)[0]
        self.assertEqual(row["last_verified_at"], first["last_verified_at"])
        self.assertTrue(row["stale_reason"])
        self.assertEqual(row["evidence_level"], "unknown")

    def test_revision_changed_during_http_is_rejected(self):
        f = self.f
        p = f.placement()

        def change():
            with db.connection() as conn:
                assets.revise(
                    conn, f.org, f.brand, f.campaign, p["id"], 1, {"purpose": "changed"}, "other"
                )
                conn.commit()

        f.reader.hook = change
        with self.assertRaises(ValueError):
            f.verify(p)
        self.assertEqual(
            f.conn.execute(
                "SELECT COUNT(*) n FROM ads_asset_binding WHERE brand_id=%s", (f.brand,)
            ).fetchone()["n"],
            0,
        )

    def test_parallel_occupancy_one_winner(self):
        f = self.f
        rows = [f.placement(), f.placement()]

        def verify(p):
            with db.connection() as conn:
                try:
                    binding.verify(
                        conn, f.org, f.brand, f.campaign, p["id"], 1, f.leaf["id"], "test"
                    )
                    return True
                except ValueError:
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(verify, rows))
        self.assertEqual(sorted(result), [False, True])

    def test_old_binding_can_be_ended_after_revision_changes(self):
        f = self.f
        p = f.placement()
        first = f.verify(p)
        assets.revise(f.conn, f.org, f.brand, f.campaign, p["id"], 1, {"purpose": "new"}, "human")
        f.conn.commit()
        ended = binding.end(f.conn, f.org, f.brand, f.campaign, p["id"], 1, first["id"])
        self.assertIsNotNone(ended["valid_to"])
        self.assertIsNotNone(
            assets.placement(f.conn, f.org, f.brand, f.campaign, p["id"], 1)["confirmed_at"]
        )

    def test_creative_change_stales_but_status_only_does_not(self):
        f = self.f
        p = f.placement()
        first = f.verify(p)
        job = {
            "org_id": f.org,
            "brand_id": f.brand,
            "platform": "fake",
            "source_account": f.account,
        }
        task = {"campaign_id": f.campaign, "section": "structure"}
        from app.ads.adapters.external import SourcePage

        external_sync._save_page(
            f.conn,
            job,
            task,
            SourcePage(
                [
                    {
                        "platform": "fake",
                        "source_account": f.account,
                        "native_kind": "unit",
                        "native_id": "leaf",
                        "native_status": "PAUSED",
                    }
                ]
            ),
        )
        self.assertIsNone(
            repo.list_bindings(f.conn, f.org, f.brand, f.campaign, p["id"], 1)[0]["stale_reason"]
        )
        task["section"] = "creatives"
        external_sync._save_page(
            f.conn,
            job,
            task,
            SourcePage(
                [
                    {
                        "platform": "fake",
                        "source_account": f.account,
                        "native_kind": "unit",
                        "native_id": "leaf",
                        "creative": {"kind": "image", "fields": {"id": "different"}},
                    }
                ]
            ),
        )
        row = repo.list_bindings(f.conn, f.org, f.brand, f.campaign, p["id"], 1)[0]
        self.assertTrue(row["stale_reason"])
        self.assertIsNotNone(row["valid_to"])
        self.assertEqual(row["creative_snapshot"], first["creative_snapshot"])

    def test_meta_reads_exact_ad_parent_and_campaign_without_equivalence(self):
        reader = MetaReader()
        account = {"account_id": "1", "timezone_name": "Asia/Taipei"}
        values = {
            "ad": {
                "id": "3",
                "account_id": "1",
                "campaign_id": "5",
                "adset_id": "4",
                "creative": {"id": "6", "image_hash": "not-sha"},
            },
            "adset": {"id": "4", "account_id": "1", "campaign_id": "5"},
            "campaign": {"id": "5", "account_id": "1"},
        }
        with patch(
            "app.ads.adapters.meta_read.source.read_external_object",
            side_effect=lambda conn, org, brand, acct, kind, native: values[kind],
        ) as get:
            result = reader.verify_native(
                None,
                "org",
                "brand",
                account,
                native_kind="ad",
                native_id="3",
                root_kind="campaign",
                root_id="5",
                original={"sha256": "not-sha"},
            )
        self.assertEqual(
            [call.args[-2:] for call in get.call_args_list],
            [("ad", "3"), ("adset", "4"), ("campaign", "5")],
        )
        self.assertIsNone(result["media_equivalence"])
        self.assertEqual(result["continuous_intervals"], [])

    def test_database_overlap_trigger_serializes_two_connections(self):
        import threading

        f = self.f
        rows = [f.placement(), f.placement()]
        barrier = threading.Barrier(2)

        def insert(p):
            with db.connection() as conn:
                barrier.wait(5)
                try:
                    conn.execute(
                        "INSERT INTO ads_asset_binding(id,org_id,brand_id,campaign_id,"
                        "placement_id,placement_revision,entity_id,platform,source_account,"
                        "native_kind,native_id,existence_status,valid_from) VALUES(%s,%s,"
                        "%s,%s,%s,1,%s,'fake',%s,'unit','leaf','platform_confirmed',"
                        "'2026-01-01T00:00:00Z')",
                        (
                            db.new_id("aab"),
                            f.org,
                            f.brand,
                            f.campaign,
                            p["id"],
                            f.leaf["id"],
                            f.account,
                        ),
                    )
                    conn.commit()
                    return True
                except psycopg.errors.CheckViolation:
                    conn.rollback()
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(insert, rows))
        self.assertEqual(sorted(results), [False, True])

    def test_failure_update_does_not_invert_native_and_row_locks(self):
        import queue
        import time

        f = self.f
        first = f.verify(f.placement())
        worker_pid = queue.Queue()

        def fail_sync():
            with db.connection() as conn:
                conn.execute("SET LOCAL statement_timeout='5s'")
                worker_pid.put(conn.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
                repo.sync_failed(conn, f.org, f.brand, f.campaign)
                conn.commit()

        repo.lock_native(f.conn, first)
        f.conn.execute("SET LOCAL statement_timeout='5s'")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fail_sync)
            try:
                pid = worker_pid.get(timeout=5)
                deadline = time.monotonic() + 3
                while not future.done() and time.monotonic() < deadline:
                    wait = f.conn.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid=%s", (pid,)
                    ).fetchone()
                    if wait and wait["wait_event"] == "advisory":
                        break
                    time.sleep(0.01)
                # Old trigger: B holds the row and waits for A's native lock;
                # this A row read closes the cycle and PostgreSQL detects it.
                f.conn.execute(
                    "SELECT id FROM ads_asset_binding WHERE id=%s FOR UPDATE", (first["id"],)
                )
                future.result(timeout=5)
            finally:
                f.conn.rollback()
        current = f.conn.execute(
            "SELECT stale_reason,last_verified_at FROM ads_asset_binding WHERE id=%s",
            (first["id"],),
        ).fetchone()
        self.assertTrue(current["stale_reason"])
        self.assertEqual(current["last_verified_at"], first["last_verified_at"])

    def test_meta_verify_patch_keeps_previously_synced_dates_and_budget(self):
        f = self.f
        account = {"account_id": "1"}
        raw = {
            "ad": {
                "id": "3",
                "account_id": "1",
                "campaign_id": "5",
                "adset_id": "4",
                "creative": {"id": "6"},
            },
            "adset": {"id": "4", "account_id": "1", "campaign_id": "5"},
            "campaign": {"id": "5", "account_id": "1"},
        }
        with patch(
            "app.ads.adapters.meta_read.source.read_external_object",
            side_effect=lambda conn, org, brand, acct, kind, native: raw[kind],
        ):
            proof = MetaReader().verify_native(
                None,
                f.org,
                f.brand,
                account,
                native_kind="ad",
                native_id="3",
                root_kind="campaign",
                root_id="5",
                original={},
            )
        for parent in reversed(proof["parents"]):
            external.upsert_entity(f.conn, f.org, f.brand, f.campaign, parent)
        before = external.upsert_entity(
            f.conn,
            f.org,
            f.brand,
            f.campaign,
            {
                "platform": "meta",
                "source_account": "1",
                "native_kind": "adset",
                "native_id": "4",
                "start_date": "2026-01-01",
                "budget_raw": {"daily_budget": "15000"},
                "budget_type": "daily",
            },
        )
        after = external.upsert_entity(f.conn, f.org, f.brand, f.campaign, proof["parents"][0])
        self.assertEqual(after["start_date"], before["start_date"])
        self.assertEqual(after["budget_raw"], before["budget_raw"])
        self.assertEqual(after["budget_type"], "daily")

    def test_successful_sync_page_does_not_mark_binding_failed(self):
        from app.ads.adapters.external import SourcePage

        f = self.f
        p = f.placement()
        f.verify(p)
        job_id = db.new_id("aes")
        task = {
            "section": "creatives",
            "campaign_id": f.campaign,
            "native_id": "root",
            "status": "pending",
            "cursor": None,
            "errors": [],
        }
        f.conn.execute(
            "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,"
            "tasks,status) VALUES(%s,%s,%s,'fake',%s,%s,'pending')",
            (job_id, f.org, f.brand, f.account, db.jsonb({"creative": task})),
        )
        f.conn.commit()
        f.reader.read_creatives = lambda *args, **kwargs: SourcePage(
            [
                {
                    k: f.leaf[k]
                    for k in ("platform", "source_account", "native_kind", "native_id", "creative")
                }
            ]
        )
        external_sync.run_sync(f.org, f.brand, job_id)
        current = external.get_job(f.conn, f.org, f.brand, job_id)
        self.assertEqual(current["status"], "succeeded", current)
        self.assertIsNone(
            repo.list_bindings(f.conn, f.org, f.brand, f.campaign, p["id"], 1)[0]["stale_reason"]
        )

    def test_failed_first_read_is_visible_after_reopening_handoff(self):
        f = self.f
        p = f.placement()
        f.reader.failure = True
        with self.assertRaises(ValueError):
            f.verify(p)
        view = binding.handoff(f.conn, f.org, f.brand, f.campaign, p["id"], 1)
        self.assertEqual(view["bindings"][0]["existence_status"], "pending")
        self.assertIsNone(view["bindings"][0]["last_verified_at"])
        self.assertTrue(view["bindings"][0]["stale_reason"])

    def test_api_handoff_self_report_and_verification_are_distinct(self):
        from fastapi.testclient import TestClient

        from app.main import app

        f = self.f
        p = f.placement()
        client = TestClient(app)
        prefix = f"/api/ads/brands/{f.brand}/campaigns/{f.campaign}/placements/{p['id']}"
        handoff = client.get(prefix + "/handoff?revision=1")
        self.assertEqual(handoff.status_code, 200, handoff.text)
        reported = client.post(prefix + "/self-report", json={"expected_revision": 1})
        self.assertEqual(reported.status_code, 200, reported.text)
        self.assertEqual(reported.json()["binding"]["existence_status"], "self_reported")
        verified = client.post(
            prefix + "/verify-binding",
            json={"expected_revision": 1, "entity_id": f.leaf["id"], "user_verified": True},
        )
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(verified.json()["binding"]["evidence_level"], "user_verified")
        self.assertEqual(f.reader.calls, 1)
