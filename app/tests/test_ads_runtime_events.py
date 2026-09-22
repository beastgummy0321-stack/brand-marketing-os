"""app/tests/test_ads_runtime_events.py — F27-I00 Contract J: the ads-owned
`ads_runtime_event` trail and `ads_external_entity.status_changed_at` bookkeeping.

Four things falsified here:
- the wrapped per-minute periodic task (`jobs._dispatch_runtime_beat`) writes one `beat` event
  with no org/brand scope;
- `runtime_events.prune()` deletes only rows past its own cutoff;
- `triage.refresh_queue` writes one `queue_refresh` event scoped to the brand it just refreshed;
- `external_repository.upsert_entity` sets `status_changed_at` only on an actual
  active<->closed crossing, never on a first insert and never when both sides stay closed.
"""

import unittest
from datetime import UTC, datetime, timedelta

from app.ads import external_repository as external
from app.ads import jobs, runtime_events, triage
from app.brand_intelligence import repository as brands
from app.core import db

# A fixed, far-past floor for `list_since()` reads below -- comparing against `db.now_utc()`
# captured on the test process would race the DB server's own `now()` (a few ms of client/server
# clock skew is enough to drop or double-count a row depending on which direction it points, both
# observed while writing this file). Reading "everything of this kind" and diffing by id against
# an `existing` snapshot taken before the action side-steps clock comparisons entirely.
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


class RuntimeBeatTest(unittest.TestCase):
    def test_periodic_wrapper_writes_one_unscoped_beat(self):
        conn = db.current()
        existing = {row["id"] for row in runtime_events.list_since(conn, "beat", _EPOCH)}
        timestamp = int(db.now_utc().timestamp())
        jobs._dispatch_runtime_beat(timestamp)
        new_rows = [
            row for row in runtime_events.list_since(conn, "beat", _EPOCH)
            if row["id"] not in existing
        ]
        self.assertEqual(len(new_rows), 1)
        self.assertIsNone(new_rows[0]["org_id"])
        self.assertIsNone(new_rows[0]["brand_id"])

    def test_prune_deletes_only_rows_past_its_cutoff(self):
        conn = db.current()
        existing = {row["id"] for row in runtime_events.list_since(conn, "beat", _EPOCH)}
        runtime_events.record(conn, "beat")
        old_id = db.new_id("are")
        conn.execute(
            "INSERT INTO ads_runtime_event(id,kind,at) VALUES (%s,'beat',%s)",
            (old_id, db.now_utc() - timedelta(hours=49)),
        )
        conn.commit()
        deleted = runtime_events.prune(conn, older_than_hours=48)
        conn.commit()
        self.assertEqual(deleted, 1)
        new_rows = [
            row for row in runtime_events.list_since(conn, "beat", _EPOCH)
            if row["id"] not in existing
        ]
        self.assertEqual(len(new_rows), 1)
        self.assertNotEqual(new_rows[0]["id"], old_id)


class RuntimeQueueRefreshEventTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="心跳與佇列刷新", actor="test", client_name=None,
        )["id"]
        self.conn.commit()

    def test_refresh_queue_records_one_scoped_event(self):
        triage.refresh_queue(self.conn, self.org, self.brand)
        rows = runtime_events.list_since(self.conn, "queue_refresh", _EPOCH, brand_id=self.brand)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["org_id"], self.org)
        self.assertEqual(rows[0]["brand_id"], self.brand)


class StatusChangedAtTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="狀態轉換時間戳", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="狀態轉換活動",
        )["id"]
        self.conn.commit()

    def _entity(self, native_id, native_status):
        return external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "native_status": native_status},
        )

    def test_first_insert_leaves_it_null(self):
        entity = self._entity("ad_new", "ACTIVE")
        self.assertIsNone(entity["status_changed_at"])

    def test_active_to_paused_crossing_sets_it(self):
        self._entity("ad_cross", "ACTIVE")
        entity = self._entity("ad_cross", "PAUSED")
        self.assertIsNotNone(entity["status_changed_at"])

    def test_paused_to_archived_stays_closed_and_does_not_move_it(self):
        self._entity("ad_stay_closed", "ACTIVE")
        first = self._entity("ad_stay_closed", "PAUSED")
        stamp = first["status_changed_at"]
        self.assertIsNotNone(stamp)
        second = self._entity("ad_stay_closed", "ARCHIVED")
        self.assertEqual(second["status_changed_at"], stamp)
