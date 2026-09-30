"""app/tests/test_ads_recovery.py — Contract K (F27-I10) falsifiers: `recovery.get_recovery()`
-- the gap definition (two consecutive `beat` events of THIS brand more than 120 minutes apart),
the 24h recovering window, the step order/labels, and each of the five steps' own done condition
(pre-dispatch correction 10 for step 3: judged per sync SECTION, never the job-level
`last_success_at`).
"""

import unittest
from datetime import timedelta
from unittest.mock import patch

from app.ads import channels, handoff_data, recovery
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings


class _Reader:
    """Reports one bound account, `act_1` (same stand-in shape as
    `test_ads_status_summary.py::_Reader`) -- keeps a campaign's sync state off `"disconnected"`
    so an `auth_expired` fixture actually reads as `auth_expired`, not `disconnected`."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": "Asia/Taipei"}]


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F27-I10 系統恢復測試", actor="test",
            client_name=None,
        )["id"]
        self.conn.commit()
        self.reader = _Reader()
        patcher = patch.object(
            channels, "external_reader", side_effect=lambda platform: self.reader,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- fixtures -----------------------------------------------------------------------------

    def _beat(self, at):
        self.conn.execute(
            "INSERT INTO ads_runtime_event(id,kind,org_id,brand_id,at) VALUES(%s,'beat',%s,%s,%s)",
            (db.new_id("are"), self.org, self.brand, at),
        )
        self.conn.commit()

    def _queue_refresh(self, at):
        self.conn.execute(
            "INSERT INTO ads_runtime_event(id,kind,org_id,brand_id,at) "
            "VALUES(%s,'queue_refresh',%s,%s,%s)",
            (db.new_id("are"), self.org, self.brand, at),
        )
        self.conn.commit()

    def _campaign(self, *, native_id="c1", account="act_1", name="恢復測試活動"):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": account, "native_kind": "campaign",
             "native_id": native_id},
        )
        self.conn.commit()
        return campaign_id

    def _change_set(self, campaign_id):
        change = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,'fixture','fixture','恢復測試核准',%s,'approved',%s,'test')",
            (change, self.org, self.brand, campaign_id, db.new_id("op"),
             coresettings.today_for_org(self.conn, org_id=self.org).strftime("%Y-%m"),
             db.jsonb({"items": []})),
        )
        self.conn.commit()
        return change

    def _reported_action(self, campaign_id, change_set_id, *, checked_at=None):
        """An `ads_action` with no handoff item of its own -- `_readback`'s second query, a
        simple settings change reported by the human and not yet confirmed."""
        action = db.new_id("adx")
        evidence = {} if checked_at is None else {"runtime_checked_at": checked_at.isoformat()}
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state,evidence_json) "
            "VALUES(%s,%s,%s,%s,'campaign',%s,'budget',%s,'reported',%s)",
            (action, self.org, self.brand, campaign_id, campaign_id, change_set_id,
             db.jsonb(evidence)),
        )
        self.conn.commit()
        return action

    def _reported_handoff(self, campaign_id, change_set_id, entity_id, *, checked_at=None):
        action = db.new_id("adx")
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) "
            "VALUES(%s,%s,%s,%s,'ad',%s,'creative',%s,'reported')",
            (action, self.org, self.brand, campaign_id, entity_id, change_set_id),
        )
        item = handoff_data.insert(
            self.conn, self.org, self.brand, campaign_id, change_set_id, action, "ad",
            entity_id, "恢復測試交接", {},
        )
        evidence = {} if checked_at is None else {"runtime_checked_at": checked_at.isoformat()}
        self.conn.execute(
            "UPDATE ads_handoff_item SET entity_id=%s,status='reported',evidence_json=%s "
            "WHERE id=%s",
            (entity_id, db.jsonb(evidence), item),
        )
        self.conn.commit()
        return item

    def get(self):
        return recovery.get_recovery(self.conn, self.org, self.brand)

    # -- gap detection / recovering window -----------------------------------------------------

    def test_no_beats_reads_not_recovering(self):
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})

    def test_regular_beats_no_gap_reads_not_recovering(self):
        now = db.now_utc()
        for i in range(5):
            self._beat(now - timedelta(minutes=10 * i))
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})

    def test_gap_over_120_minutes_ended_within_24h_is_recovering_with_five_steps_in_order(self):
        now = db.now_utc()
        gap_start = now - timedelta(hours=3, minutes=10)
        gap_end = now - timedelta(hours=1)
        self._beat(gap_start)
        self._beat(gap_end)
        result = self.get()
        self.assertTrue(result["recovering"])
        self.assertEqual(result["gap"]["minutes"], 130)
        self.assertEqual(
            [s["key"] for s in result["steps"]],
            ["reconnect", "auth", "resync", "requeue", "reports"],
        )
        self.assertEqual(result["steps"][2]["label"], "補 2 小時的資料")
        # Nothing to catch up on (no campaigns, nothing pending) except the two events this
        # test never wrote (a beat/queue_refresh after the gap) -- the first not-done step
        # ("reconnect") reads "active", everything after it reads "todo" regardless of its own
        # individually-true condition (order is sequential, not independently evaluated).
        self.assertEqual(result["steps"][0]["state"], "active")
        self.assertEqual([s["state"] for s in result["steps"][1:]], ["todo"] * 4)

    def test_gap_120_minutes_exactly_does_not_count(self):
        now = db.now_utc()
        self._beat(now - timedelta(hours=3))
        self._beat(now - timedelta(hours=1))
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})

    def test_gap_ended_over_24h_ago_reads_not_recovering(self):
        now = db.now_utc()
        gap_start = now - timedelta(hours=27)
        gap_end = now - timedelta(hours=25)
        self._beat(gap_start)
        self._beat(gap_end)
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})

    def test_all_steps_done_reads_not_recovering_even_within_24h(self):
        now = db.now_utc()
        gap_start = now - timedelta(hours=3, minutes=10)
        gap_end = now - timedelta(hours=1)
        self._beat(gap_start)
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        self._queue_refresh(gap_end + timedelta(minutes=1))
        result = self.get()
        self.assertEqual(result, {"recovering": False, "gap": None, "steps": []})

    # -- step 1: 重新連線 --------------------------------------------------------------------

    def test_reconnect_needs_a_beat_strictly_after_gap_end(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self.assertEqual(self.get()["steps"][0]["state"], "active")
        self._beat(gap_end + timedelta(minutes=1))
        self.assertEqual(self.get()["steps"][0]["state"], "done")

    # -- step 2: 確認讀取權限 ----------------------------------------------------------------

    def test_auth_step_blocked_by_auth_expired_campaign_then_clears(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))  # step 1 done, so step 2 can surface
        campaign_id = self._campaign()
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "error", "error": "沒有讀取權限", "error_code": "permission_denied"},
        )
        self.conn.commit()
        result = self.get()
        self.assertEqual(result["steps"][1]["key"], "auth")
        self.assertEqual(result["steps"][1]["state"], "active")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        self.assertEqual(self.get()["steps"][1]["state"], "done")

    # -- step 3: 補 N 小時的資料 (pre-dispatch correction 10) --------------------------------

    def test_resync_step_reads_per_section_last_success_at_not_job_level(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        campaign_id = self._campaign()
        before_gap = (gap_end - timedelta(minutes=5)).isoformat()
        after_gap = (gap_end + timedelta(minutes=5)).isoformat()
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": before_gap,
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        result = self.get()
        self.assertEqual(result["steps"][2]["key"], "resync")
        self.assertEqual(result["steps"][2]["state"], "active")
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": after_gap,
                   "coverage": {"start": "2026-08-01", "end": "2026-08-30"}},
        )
        self.conn.commit()
        self.assertEqual(self.get()["steps"][2]["state"], "done")

    # -- step 4: 重新判斷廣告 -----------------------------------------------------------------

    def test_requeue_needs_a_queue_refresh_event_after_gap_end(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        # Step 5 stays permanently unmet so the response never fully collapses to "not
        # recovering" once step 4 (this test's own subject) is satisfied below -- it sits
        # AFTER step 4, so it never masks step 4's own state either way.
        campaign_id = self._campaign()
        change_set = self._change_set(campaign_id)
        self._reported_action(campaign_id, change_set, checked_at=None)
        result = self.get()
        self.assertEqual(result["steps"][3]["key"], "requeue")
        self.assertEqual(result["steps"][3]["state"], "active")
        self._queue_refresh(gap_end + timedelta(minutes=1))
        self.assertEqual(self.get()["steps"][3]["state"], "done")

    # -- step 5: 核對你回報的操作 -------------------------------------------------------------

    def test_reports_step_needs_every_reported_item_checked_after_gap_end(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        self._queue_refresh(gap_end + timedelta(minutes=1))
        campaign_id = self._campaign()
        change_set = self._change_set(campaign_id)
        self._reported_action(campaign_id, change_set, checked_at=gap_end - timedelta(minutes=5))
        result = self.get()
        self.assertEqual(result["steps"][4]["key"], "reports")
        self.assertEqual(result["steps"][4]["state"], "active")

    def test_reports_step_done_once_pending_action_checked_after_gap_end(self):
        # Once the last outstanding item is checked after `gap.end`, ALL five steps read done
        # -- the response collapses to "not recovering" entirely (no banner left to show), so
        # this is observed as the whole shape flipping, not a `steps[4]` value in isolation.
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        self._queue_refresh(gap_end + timedelta(minutes=1))
        campaign_id = self._campaign()
        change_set = self._change_set(campaign_id)
        self._reported_action(campaign_id, change_set, checked_at=gap_end - timedelta(minutes=5))
        self.assertEqual(self.get()["steps"][4]["state"], "active")
        self.conn.execute(
            "UPDATE ads_action SET evidence_json=%s WHERE campaign_id=%s",
            (db.jsonb({"runtime_checked_at": (gap_end + timedelta(minutes=5)).isoformat()}),
             campaign_id),
        )
        self.conn.commit()
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})

    def test_reports_step_covers_reported_handoff_items_too(self):
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        self._queue_refresh(gap_end + timedelta(minutes=1))
        campaign_id = self._campaign()
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad_1"},
        )
        change_set = self._change_set(campaign_id)
        self._reported_handoff(
            campaign_id, change_set, entity["id"], checked_at=gap_end - timedelta(minutes=5),
        )
        result = self.get()
        self.assertEqual(result["steps"][4]["state"], "active")

    def test_reports_step_vacuously_done_with_nothing_pending_collapses_the_whole_response(self):
        # Same collapse as above, from the vacuous side: nothing was ever pending, so as soon
        # as steps 1-4 are met there is nothing left to wait on at all.
        now = db.now_utc()
        gap_end = now - timedelta(hours=1)
        self._beat(gap_end - timedelta(hours=3))
        self._beat(gap_end)
        self._beat(gap_end + timedelta(minutes=1))
        self._queue_refresh(gap_end + timedelta(minutes=1))
        self.assertEqual(self.get(), {"recovering": False, "gap": None, "steps": []})


if __name__ == "__main__":
    unittest.main()
