"""Monitoring remains independent of human review disposition and platform mutation."""

import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import background
from app.ads import external_repository as external
from app.ads import (
    external_sync,
    handoff_check,
    handoff_data,
    lifecycle,
    repository,
    runtime,
)
from app.ads.adapters.external import SourceReadError
from app.brand_intelligence import repository as brands
from app.core import db, interrupts, settings


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn,
            org_id=self.org,
            name="持續追蹤",
            actor="test",
            client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn,
            self.org,
            self.brand,
            name="持續活動",
        )["id"]
        self.entity = external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "campaign",
                "native_id": "campaign",
                "native_status": "ACTIVE",
            },
        )
        self.conn.commit()

    def test_bound_account_is_read_even_without_imported_campaigns(self):
        # Drill 5: a new-campaign-only brand never got the account's month spend, so the
        # month-budget guard blocked its first launch forever.
        class Reader:
            def accounts(self, conn, org_id, brand_id):
                return [{"account_id": "acct-1"}] if brand_id == brand else []

        brand = self.brand
        now = db.now_utc()
        with (
            patch.object(runtime.channels, "external_reader", return_value=Reader()),
            patch.object(runtime.external_sync, "request_sync") as request,
        ):
            runtime._sync_brand_accounts(self.conn, now)
            calls = [c.args[2:] for c in request.call_args_list if c.args[2] == brand]
            self.assertIn((brand, runtime.channels.CHANNELS[0]["key"], "acct-1"), calls)
            for channel in runtime.channels.CHANNELS:
                self.conn.execute(
                    "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,"
                    "status) VALUES (%s,%s,%s,%s,'acct-1','succeeded')",
                    (db.new_id("aes"), self.org, brand, channel["key"]),
                )
            request.reset_mock()
            runtime._sync_brand_accounts(self.conn, now)
            self.assertFalse([c for c in request.call_args_list if c.args[2] == brand])

    def test_unreadable_bound_account_is_recorded_with_its_reason(self):
        # F50 Contract J: `_sync_brand_accounts` never drops an account silently -- the failed
        # request is recorded on the account's own job (Contract O names the reason), so the
        # month budget's 「餘額不確定」 has one, and the stamped attempt backs the next tick off.
        class Reader:
            def accounts(self, conn, org_id, brand_id):
                return [{"account_id": "acct-x"}] if brand_id == brand else []

        brand = self.brand
        key = runtime.channels.CHANNELS[0]["key"]
        with (
            patch.object(runtime.channels, "external_reader", return_value=Reader()),
            patch.object(runtime.external_sync, "request_sync",
                         side_effect=SourceReadError("private", "permission_denied")),
            self.assertLogs("app.ads.runtime", "WARNING"),
        ):
            runtime._sync_brand_accounts(self.conn, db.now_utc())
        job = self.conn.execute(
            "SELECT * FROM ads_external_sync_job WHERE org_id=%s AND brand_id=%s AND platform=%s "
            "AND source_account='acct-x'", (self.org, brand, key),
        ).fetchone()
        read = external_sync.outcome(job["tasks"])
        self.assertEqual((read["state"], read["code"]), ("failed", "permission_denied"))
        self.assertEqual(job["status"], "failed")
        self.assertNotIn("private", str(job["tasks"]))
        self.assertIsNotNone(job["last_attempt_at"])

    def test_unreadable_account_listing_is_logged_not_silent(self):
        class Reader:
            def accounts(self, conn, org_id, brand_id):
                raise RuntimeError("listing broke")

        with (
            patch.object(runtime.channels, "external_reader", return_value=Reader()),
            self.assertLogs("app.ads.runtime", "ERROR") as logs,
        ):
            self.assertEqual(runtime._sync_brand_accounts(self.conn, db.now_utc()), 0)
        self.assertTrue(any(self.brand in line for line in logs.output))

    def test_a_raising_readback_keeps_health_then_fails_the_job_and_logs(self):
        # F50 Contract J (triage #3): the swallowed step still writes its health row, then the
        # job ends `Failed("runtime_error")` -- the wrapper raises `JobFailed`, so procrastinate
        # marks it failed and the bell counts it.
        with (
            patch.object(runtime, "_sync_sources", return_value=0),
            patch.object(runtime, "_readback", side_effect=ValueError("private readback")),
            self.assertLogs("app.ads.runtime", "ERROR") as logs,
        ):
            result = runtime.run_campaign(self.org, self.brand, self.campaign)
        self.assertIsInstance(result, background.Failed)
        assert isinstance(result, background.Failed)
        self.assertEqual(result.code, runtime.RUNTIME_ERROR)
        self.assertNotIn("private", result.text or "")
        self.assertTrue(any("readback" in line for line in logs.output))
        value = runtime.view(self.conn, self.org, self.brand, self.campaign)
        self.assertIn("partial", [h["code"] for h in value["health"]])
        self.assertIsNotNone(value["last_checked_at"])

        background.register(runtime.TASK, runtime.run_campaign)
        task = background.app().tasks[runtime.TASK]
        with (
            patch.object(runtime, "_sync_sources", return_value=0),
            patch.object(runtime, "_readback", side_effect=ValueError("private readback")),
            self.assertLogs("app.ads.runtime", "ERROR"),
            self.assertRaises(background.JobFailed) as raised,
        ):
            task.func(org_id=self.org, brand_id=self.brand, campaign_id=self.campaign)
        self.assertEqual(raised.exception.code, runtime.RUNTIME_ERROR)

    def test_a_clean_tick_is_done(self):
        with (
            patch.object(runtime, "_sync_sources", return_value=0),
            patch.object(runtime, "_readback", return_value=0),
        ):
            self.assertIsNone(runtime.run_campaign(self.org, self.brand, self.campaign))

    def test_run_saves_health_and_reopen_does_not_execute_platform_or_ai(self):
        with patch.object(runtime, "_sync_sources", return_value=1) as sync:
            runtime.run_campaign(self.org, self.brand, self.campaign)
        sync.assert_called_once()
        value = runtime.view(self.conn, self.org, self.brand, self.campaign)
        self.assertIsNotNone(value["last_checked_at"])
        self.assertTrue(any(h["code"] == "budget_unknown" for h in value["health"]))
        self.assertIsNone(value["budget"]["available"])
        with patch.object(runtime, "_sync_sources") as sync:
            self.assertEqual(
                runtime.view(self.conn, self.org, self.brand, self.campaign)["last_checked_at"],
                value["last_checked_at"],
            )
        sync.assert_not_called()
        # F49 Contract L (decision 12): the tick records the imported campaign's lifecycle -- its
        # root was read and has not ended, so it is live (never closed).
        self.assertEqual(
            repository.get_campaign(self.conn, self.org, self.brand, self.campaign)["status"],
            "live",
        )

    def test_failed_source_keeps_health_and_does_not_claim_complete(self):
        with patch.object(runtime, "_sync_sources", side_effect=ValueError("private detail")):
            runtime.run_campaign(self.org, self.brand, self.campaign)
        value = runtime.view(self.conn, self.org, self.brand, self.campaign)
        self.assertIn("partial", [h["code"] for h in value["health"]])
        self.assertNotIn("private detail", str(value))
        self.assertIsNone(value["sources"][0]["last_success_at"])
        self.assertIsNone(value["sources"][0]["coverage"])

    def test_health_failure_persists_check_time_and_unknown_without_private_error(self):
        with (
            patch.object(runtime, "_sync_sources"),
            patch.object(runtime, "_readback"),
            patch.object(runtime, "_health", side_effect=RuntimeError("private connection detail")),
        ):
            runtime.run_campaign(self.org, self.brand, self.campaign)
        value = runtime.view(self.conn, self.org, self.brand, self.campaign)
        self.assertIsNotNone(value["last_checked_at"])
        self.assertIsNone(value["budget"])
        self.assertTrue(value["health"])
        self.assertTrue(all(item["severity"] == "unknown" for item in value["health"]))
        self.assertNotIn("private connection detail", str(value))
        self.assertFalse(runtime._due(value["last_checked_at"], db.now_utc(), 900))

    def test_active_page_checkpoint_is_not_reset_by_monitor_tick(self):
        self.conn.execute(
            "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,"
            "status,tasks) VALUES(%s,%s,%s,'fixture','account','pending',%s)",
            (
                db.new_id("aes"),
                self.org,
                self.brand,
                db.jsonb(
                    {
                        "list": {
                            "section": "list",
                            "status": "pending",
                            "cursor": "page-two",
                            "generation": "original",
                        }
                    }
                ),
            ),
        )
        self.conn.commit()
        with patch.object(runtime.external_sync, "request_sync") as request:
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, db.now_utc())
        request.assert_not_called()
        task = self.conn.execute(
            "SELECT tasks FROM ads_external_sync_job WHERE brand_id=%s",
            (self.brand,),
        ).fetchone()["tasks"]["list"]
        self.assertEqual((task["cursor"], task["generation"]), ("page-two", "original"))

    def test_backfill_splits_full_prior_and_current_windows_without_skipping_older_days(self):
        from app.ads import review_monitor

        today = db.now_utc().date()
        start, end = today - timedelta(days=90), today - timedelta(days=29)
        with (
            patch.object(
                review_monitor,
                "required_windows",
                return_value=[
                    {
                        "platform": "fixture",
                        "source_account": "account",
                        "start": str(start),
                        "end": str(end),
                        "entity_id": "ad",
                        "reason": "waiting",
                    }
                ],
            ),
            patch.object(runtime.external_sync, "request_sync") as request,
        ):
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, db.now_utc())
        ranges = {(c.kwargs["start"], c.kwargs["end"]) for c in request.call_args_list}
        self.assertTrue(all((b - a).days <= 30 for a, b in ranges))
        day = start
        while day <= end:
            self.assertTrue(any(a <= day <= b for a, b in ranges), str(day))
            day += timedelta(days=1)

    def test_runtime_api_is_scoped_and_never_treats_read_as_worker_recovery(self):
        from app.main import app

        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        with patch.object(runtime, "bootstrap") as recover:
            response = client.get(base + "/runtime")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(response.json()["last_bootstrap_at"])
            self.assertEqual(
                client.get(base.replace(self.brand, "missing") + "/runtime").status_code, 404
            )
        recover.assert_not_called()

    def _native_ad(self, campaign, root, native_id):
        return external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "ad",
                "native_id": native_id,
                "parent_native_kind": "campaign",
                "parent_native_id": root["native_id"],
                "native_status": "ACTIVE",
            },
        )

    def test_shared_account_collects_both_campaign_windows_and_keeps_active_cursor(self):
        today = settings.today_for_org(self.conn, org_id=self.org)
        other = external.create_imported_campaign(
            self.conn,
            self.org,
            self.brand,
            name="同帳戶另一活動",
        )["id"]
        other_root = external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            other,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "campaign",
                "native_id": "other-root",
                "native_status": "ACTIVE",
            },
        )
        periods = []
        for campaign, root, days_ago in (
            (self.campaign, self.entity, 80),
            (other, other_root, 150),
        ):
            ad = self._native_ad(campaign, root, db.new_id("native"))
            start, end = today - timedelta(days=days_ago), today - timedelta(days=days_ago - 6)
            periods.append((start - timedelta(days=7), end))
            # Pausing AI interpretation must not remove either observation window.
            self.conn.execute(
                "INSERT INTO ads_review_monitor(id,org_id,brand_id,campaign_id,entity_id,"
                "enabled,state,window_start,window_end) "
                "VALUES(%s,%s,%s,%s,%s,false,'paused',%s,%s)",
                (db.new_id("arm"), self.org, self.brand, campaign, ad["id"], start, end),
            )
        self.conn.commit()
        with (
            patch.object(external_sync, "account_reader", return_value=(object(), {})),
            patch.object(external_sync, "_enqueue"),
        ):
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, db.now_utc())
            job = self.conn.execute(
                "SELECT * FROM ads_external_sync_job WHERE brand_id=%s",
                (self.brand,),
            ).fetchone()
            observations = [t for t in job["tasks"].values() if t["section"] == "observations"]
            for campaign in (self.campaign, other):
                ranges = {
                    (t["start"], t["end"]) for t in observations if t["campaign_id"] == campaign
                }
                self.assertTrue({(str(start), str(end)) for start, end in periods} <= ranges)
                self.assertIn((str(today - timedelta(days=29)), str(today)), ranges)
            tasks = job["tasks"]
            tasks["list"]["cursor"] = {"after": "page-two"}
            self.conn.execute(
                "UPDATE ads_external_sync_job SET tasks=%s WHERE id=%s",
                (db.jsonb(tasks), job["id"]),
            )
            self.conn.commit()
            runtime._sync_sources(self.conn, self.org, self.brand, other, db.now_utc())
        reopened = self.conn.execute(
            "SELECT tasks FROM ads_external_sync_job WHERE id=%s",
            (job["id"],),
        ).fetchone()["tasks"]
        self.assertEqual(reopened, tasks)

    def test_backoff_is_written_only_through_record_request_failure(self):
        with (
            patch.object(external_sync, "account_reader",
                         side_effect=SourceReadError("private detail", "unsupported")),
            patch.object(external_sync, "record_request_failure") as record,
        ):
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, db.now_utc())
        record.assert_called_once_with(
            self.conn, self.org, self.brand, "fixture", "account", "unsupported",
        )

    def test_reader_failure_before_job_insert_persists_backoff_and_unknown_health(self):
        now = db.now_utc()
        with patch.object(
            external_sync,
            "account_reader",
            side_effect=SourceReadError("private detail", "disconnected"),
        ) as reader:
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, now)
            self.assertEqual(reader.call_count, 1)
            job = self.conn.execute(
                "SELECT * FROM ads_external_sync_job WHERE brand_id=%s",
                (self.brand,),
            ).fetchone()
            # F49 Contract O: the backoff row is written through
            # `external_sync.record_request_failure` -- a failed `request` account task the one
            # outcome reads (nothing else was read: `failed`, naming the code).
            self.assertEqual(job["status"], "failed")
            self.assertIsNotNone(job["last_attempt_at"])
            self.assertEqual(set(job["tasks"]), {external_sync.REQUEST_TASK})
            self.assertIsNone(job["last_success_at"])
            self.assertNotIn("private detail", job["error"])
            read = external_sync.outcome(job["tasks"], campaign_id=self.campaign)
            self.assertEqual((read["state"], read["code"]), ("failed", "disconnected"))
            self.assertEqual(job["error"], read["text"])
            source = runtime._sources(self.conn, self.org, self.brand, self.campaign)[0]
            self.assertEqual(source["error"], read["text"])
            runtime._sync_sources(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                now + timedelta(minutes=1),
            )
            self.assertEqual(reader.call_count, 1)
            later = now + timedelta(seconds=runtime.SYNC_SECONDS + 1)
            runtime._sync_sources(self.conn, self.org, self.brand, self.campaign, later)
            self.assertEqual(reader.call_count, 2)
        health, _ = runtime._health(self.conn, self.org, self.brand, self.campaign, now)
        incomplete = next(item for item in health if item["code"] == "source_incomplete")
        self.assertEqual(incomplete["severity"], "unknown")

    def _internal_campaign(self, status, end_offset_days):
        today = settings.today_for_org(self.conn, org_id=self.org)
        campaign = repository.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": f"人工上架 {status}",
                "goal_text": "檢驗結案入口",
                "objective": "awareness",
                "start_date": today - timedelta(days=14),
                "end_date": today + timedelta(days=end_offset_days),
                "status": status,
            },
            created_by="test",
        )
        self.conn.commit()
        return campaign["id"]

    def _campaign_status(self, campaign_id):
        return repository.get_campaign(self.conn, self.org, self.brand, campaign_id)["status"]

    def test_health_marks_live_campaign_ended_once_plan_end_date_passed(self):
        # F32-I01: nothing wrote `ended`, so a hand-launched campaign never reached 結案.
        campaign = self._internal_campaign("live", -1)
        health, _ = runtime._health(self.conn, self.org, self.brand, campaign, db.now_utc())
        # F49 Contract N: the passed end date is no runtime alert (the queue's closeout row
        # carries it).
        self.assertNotIn("plan_date_passed", [item["code"] for item in health])
        self.assertEqual(self._campaign_status(campaign), "ended")
        # The beat is idempotent: `ended` stays `ended`, never advances to `closed`.
        runtime._health(self.conn, self.org, self.brand, campaign, db.now_utc())
        self.assertEqual(self._campaign_status(campaign), "ended")

    def test_health_leaves_closed_and_still_running_campaigns_alone(self):
        closed = self._internal_campaign("closed", -1)
        running = self._internal_campaign("live", 3)
        for campaign in (closed, running):
            runtime._health(self.conn, self.org, self.brand, campaign, db.now_utc())
        self.assertEqual(self._campaign_status(closed), "closed")
        self.assertEqual(self._campaign_status(running), "live")

    def _handoffs(self, status):
        old = db.now_utc() - timedelta(days=2)
        change = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,'fixture','fixture','既有核准',%s,'approved',%s,'test')",
            (
                change,
                self.org,
                self.brand,
                self.campaign,
                db.new_id("op"),
                old.strftime("%Y-%m"),
                db.jsonb({"items": []}),
            ),
        )
        result = []
        for index in range(4):
            ad = self._native_ad(self.campaign, self.entity, db.new_id("native"))
            action = db.new_id("adx")
            self.conn.execute(
                "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,"
                "kind,change_set_id,verification_state,first_observed_at,verified_at) "
                "VALUES(%s,%s,%s,%s,'ad',%s,'pause',%s,%s,%s,%s)",
                (action, self.org, self.brand, self.campaign, ad["id"], change, status, old, old),
            )
            item = handoff_data.insert(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                change,
                action,
                "ad",
                ad["id"],
                f"已核對 {index + 1}",
                {},
            )
            self.conn.execute(
                "UPDATE ads_handoff_item SET entity_id=%s,status=%s,observed_at=%s,"
                "created_at=%s,updated_at=%s,evidence_json=%s WHERE id=%s",
                (
                    ad["id"],
                    status,
                    old,
                    old + timedelta(seconds=index),
                    old,
                    db.jsonb(
                        {
                            "entity_exists": True,
                            "setting_matches": True,
                            "observed_at": old.isoformat(),
                            "historical_note": "前次已讀回",
                        }
                    ),
                    item,
                ),
            )
            result.append((item, action))
        self.conn.commit()
        return old, result

    def test_failed_first_three_handoffs_rotate_and_keep_history_as_unknown(self):
        old, items = self._handoffs("reported")
        # Exercise real handoff.check: account_reader raises before its HTTP try block.
        with (
            patch.object(
                external_sync,
                "account_reader",
                side_effect=SourceReadError("已解除連線", "disconnected"),
            ),
            patch.object(handoff_check, "check", wraps=handoff_check.check) as check,
        ):
            with self.assertRaisesRegex(ValueError, "部分平台項目未讀回"):
                runtime._readback(self.conn, self.org, self.brand, self.campaign)
            self.assertEqual([c.args[4] for c in check.call_args_list], [i[0] for i in items[:3]])
            for item, action in items[:3]:
                value = handoff_data.get(self.conn, self.org, self.brand, self.campaign, item)
                self.assertEqual(value["status"], "unknown")
                self.assertIsNone(value["setting_matches"])
                self.assertEqual(value["observed_at"], old)
                self.assertEqual(value["evidence_json"]["historical_note"], "前次已讀回")
                self.assertEqual(value["evidence_json"]["observed_at"], old.isoformat())
                self.assertIn("runtime_checked_at", value["evidence_json"])
                saved = self.conn.execute(
                    "SELECT verification_state,verified_at FROM ads_action WHERE id=%s",
                    (action,),
                ).fetchone()
                self.assertEqual(saved["verification_state"], "unknown")
                self.assertEqual(saved["verified_at"], old)
            check.reset_mock()
            with self.assertRaisesRegex(ValueError, "部分平台項目未讀回"):
                runtime._readback(self.conn, self.org, self.brand, self.campaign)
            self.assertEqual(check.call_args_list[0].args[4], items[3][0])
            fourth = handoff_data.get(self.conn, self.org, self.brand, self.campaign, items[3][0])
            self.assertEqual(fourth["status"], "unknown")
            self.assertEqual(fourth["observed_at"], old)

    def test_confirmed_handoffs_are_not_reread_by_the_tick(self):
        # F49 Contract N: a confirmed item or action is final for the tick (the user's 重新核對
        # still reads it); only the unconfirmed ones are read.
        _, items = self._handoffs("confirmed")
        with patch.object(handoff_check, "check") as check, patch(
            "app.ads.change_control_verify.check"
        ) as verify:
            self.assertEqual(
                runtime._readback(self.conn, self.org, self.brand, self.campaign), 0
            )
        check.assert_not_called()
        verify.assert_not_called()
        for item, _action in items:
            value = handoff_data.get(self.conn, self.org, self.brand, self.campaign, item)
            self.assertEqual(value["status"], "confirmed")
            self.assertNotIn("runtime_checked_at", value["evidence_json"])

    def test_bootstrap_scans_past_unchanged_unknowns_to_dead_running_review(self):
        ids = []
        for index in range(3):
            review = db.new_id("arr")
            ids.append(review)
            self.conn.execute(
                "INSERT INTO ads_review_round(id,org_id,brand_id,campaign_id,entity_id,"
                "window_start,window_end,evidence_json,evidence_hash,status,created_by,created_at) "
                "VALUES(%s,%s,%s,%s,%s,current_date-2,current_date-1,'{}',%s,%s,'test',%s)",
                (review, self.org, self.brand, self.campaign, self.entity["id"], review,
                 "running" if index == 2 else "unknown",
                 db.now_utc() - timedelta(days=3-index)),
            )
        self.conn.commit()
        empty = dict(reviews_recovered=0, reviews_unknown=0, reviews_failed=0,
                     reviews_enqueued=0, has_more=False)
        with patch.object(runtime, "dispatch", return_value=empty):
            receipt = runtime.bootstrap(self.conn, int(db.now_utc().timestamp()), limit=1)
        self.assertEqual(receipt["reviews_unknown"], 1)
        row = self.conn.execute(
            "SELECT status,recovery_checked_at,reservation_state FROM ads_review_round WHERE id=%s",
            (ids[-1],),
        ).fetchone()
        self.assertEqual(row["status"], "unknown")
        self.assertIsNotNone(row["recovery_checked_at"])
        self.assertEqual(row["reservation_state"], "held")


ALERT_MESSAGE = "廣告追蹤有待確認項目，請檢視"


class MonitoredOnlyTest(unittest.TestCase):
    """F49 Contract N: the runtime follows the lifecycle -- a closed campaign and one ended past
    `ENDED_GRACE_DAYS` are never enqueued nor re-read in the background (an explicit 重新讀取 still
    reads them); one ended inside the grace days still is. Health alerts are one row per
    (campaign, code), resolved by the tick once the condition clears."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="只讀還在監測的活動", actor="test", client_name=None,
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        grace = lifecycle.ENDED_GRACE_DAYS
        self.live = self._campaign("live", 3, "live-root")
        self.in_grace = self._campaign("live", -grace, "grace-root")
        self.past_grace = self._campaign("ended", -(grace + 1), "past-root")
        self.closed = self._campaign("closed", -1, "closed-root")
        self.conn.commit()

    def _campaign(self, status, end_offset_days, native_id):
        campaign = repository.create_campaign(
            self.conn, self.org, self.brand,
            {
                "name": f"監測 {native_id}", "goal_text": "監測範圍", "objective": "awareness",
                "start_date": self.today - timedelta(days=30),
                "end_date": self.today + timedelta(days=end_offset_days), "status": status,
            },
            created_by="test",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign,
            {
                "platform": "fixture", "source_account": "account", "native_kind": "campaign",
                "native_id": native_id, "native_status": "ACTIVE",
            },
        )
        return campaign

    def _raise(self, *keys):
        for key in keys:
            interrupts.enqueue(
                self.conn, org_id=self.org, brand_id=self.brand,
                category=runtime.ALERT_CATEGORY, dedupe_key=key, message=ALERT_MESSAGE,
            )
        self.conn.commit()

    def _open_keys(self):
        return {
            row["dedupe_key"] for row in interrupts.list_open(
                self.conn, org_id=self.org, brand_id=self.brand, category=runtime.ALERT_CATEGORY,
                archive_stale=False,
            )
        }

    def _only_this_brand(self):
        return patch.object(runtime.lifecycle, "brands",
                            return_value=[{"org_id": self.org, "brand_id": self.brand}])

    def _dispatch(self):
        empty = dict(reviews_recovered=0, reviews_unknown=0, reviews_failed=0,
                     reviews_enqueued=0, has_more=False)
        with (
            self._only_this_brand(),
            patch("app.ads.review_jobs.recover", return_value=empty),
            patch("app.ads.review_monitor.dispatch_due",
                  return_value={"reviews_enqueued": 0, "monitors_checked": 0, "has_more": False}),
            patch.object(runtime, "_sync_brand_accounts", return_value=0),
            patch.object(runtime.background, "is_active", return_value=False),
            patch.object(runtime.background, "enqueue", return_value=1) as enqueue,
        ):
            runtime.dispatch(int(db.now_utc().timestamp()))
        return {c.kwargs["campaign_id"] for c in enqueue.call_args_list}

    def test_dispatch_enqueues_only_monitored_campaigns(self):
        self.assertEqual(self._dispatch(), {self.live, self.in_grace})

    def test_dispatch_sweeps_alerts_of_campaigns_that_left_the_monitored_set_once_a_day(self):
        # A campaign past the grace days is never ticked again: the dispatcher resolves its open
        # runtime alerts (old dated keys too) once a day; a monitored campaign's stay open.
        left = [
            f"ads-runtime:{self.past_grace}:source_incomplete:{self.today}",
            f"ads-runtime:{self.past_grace}:{self.today}:budget_unknown",
        ]
        kept = f"ads-runtime:{self.live}:budget_unknown:{self.today}"
        self._raise(*left, kept)
        with patch.object(runtime, "_last_sweep_day", None):
            self._dispatch()
            self.assertEqual(self._open_keys(), {kept})
            late = f"ads-runtime:{self.past_grace}:source_incomplete:late"
            self._raise(late)
            self._dispatch()  # the same day: no second sweep
            self.assertIn(late, self._open_keys())

    def test_compatibility_handler_enqueues_only_monitored_campaigns(self):
        from app.ads import jobs

        with (
            self._only_this_brand(),
            patch.object(jobs.background, "is_active", return_value=False),
            patch.object(jobs.background, "enqueue", return_value=1) as enqueue,
        ):
            jobs.close_expired_campaigns(self.org)
        self.assertEqual(
            {c.kwargs["campaign_id"] for c in enqueue.call_args_list}, {self.live, self.in_grace}
        )

    def test_run_returns_without_a_read_for_a_campaign_no_longer_monitored(self):
        key = f"ads-runtime:{self.past_grace}:source_incomplete"
        self._raise(key)
        with (
            patch.object(runtime, "_sync_sources") as sync,
            patch.object(runtime, "_readback") as readback,
            patch.object(runtime, "_health") as health,
        ):
            runtime.run_campaign(self.org, self.brand, self.past_grace)
        sync.assert_not_called()
        readback.assert_not_called()
        health.assert_not_called()
        self.assertNotIn(key, self._open_keys())

    def _task_campaigns(self, job):
        return {
            task["campaign_id"] for task in job["tasks"].values() if task.get("campaign_id")
        }

    def test_request_sync_builds_sections_only_for_monitored_roots(self):
        with (
            patch.object(external_sync, "account_reader", return_value=(object(), {})),
            patch.object(external_sync, "_enqueue"),
        ):
            job = external_sync.request_sync(self.conn, self.org, self.brand, "fixture", "account")
            self.assertEqual(self._task_campaigns(job), {self.live, self.in_grace})
            # Account tasks are unchanged: the month budget keeps reading the account.
            self.assertIn("list", job["tasks"])
            self.assertTrue(any(key.startswith("monthly:") for key in job["tasks"]))
            # The user's 重新讀取 of a closed campaign still reads it.
            jobs = external_sync.request_campaign_sync(
                self.conn, self.org, self.brand, self.closed
            )
        self.assertIn(self.closed, self._task_campaigns(jobs[0]))
        self.assertNotIn(self.past_grace, self._task_campaigns(jobs[0]))

    def test_campaign_sync_route_reads_a_campaign_past_the_grace_days(self):
        from app.main import app

        client = TestClient(app)
        with (
            patch.object(external_sync, "account_reader", return_value=(object(), {})),
            patch.object(external_sync, "_enqueue"),
        ):
            response = client.post(
                f"/api/ads/brands/{self.brand}/campaigns/{self.past_grace}/sync", json={}
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(self.past_grace, self._task_campaigns(response.json()["job"]))

    def _episode_key(self, code, since=None):
        return f"ads-runtime:{self.live}:{code}:{since or self.today}"

    def _tick(self, *, budget_known=False, today=None):
        """One `_health` of the live campaign, with the month budget known or not (the
        `budget_unknown` alert) and, optionally, another org day."""
        budget = {
            "month": self.today.strftime("%Y-%m"), "currency": "TWD", "amount": 1000.0,
            "known_spend": 0.0, "available": 1000.0 if budget_known else None,
            "uncertainties": [], "can_increase": budget_known,
        }
        day = today or self.today
        with (
            patch.object(runtime.month_budget, "view", return_value=budget),
            patch.object(settings, "today_for_org", return_value=day),
        ):
            health, _ = runtime._health(self.conn, self.org, self.brand, self.live, db.now_utc())
        return {item["code"] for item in health}

    def test_two_ticks_on_the_same_alert_leave_one_open_row(self):
        for _ in range(2):
            health, _ = runtime._health(self.conn, self.org, self.brand, self.live, db.now_utc())
        codes = {item["code"] for item in health}
        self.assertIn("budget_unknown", codes)
        self.assertEqual(self._open_keys(), {self._episode_key(code) for code in codes})

    def test_a_cleared_alert_that_returns_raises_a_new_row(self):
        self.assertIn("budget_unknown", self._tick())
        first = self._episode_key("budget_unknown")
        self.assertIn(first, self._open_keys())
        # The next day it persists: the same episode, still one row.
        tomorrow = self.today + timedelta(days=1)
        self._tick(today=tomorrow)
        self.assertIn(first, self._open_keys())
        # It clears: the row resolves and the episode ends.
        self.assertNotIn("budget_unknown", self._tick(budget_known=True, today=tomorrow))
        self.assertNotIn(first, self._open_keys())
        # It returns later: a new episode, a new open row.
        later = self.today + timedelta(days=2)
        self._tick(today=later)
        self.assertIn(self._episode_key("budget_unknown", later), self._open_keys())
        self.assertNotIn(first, self._open_keys())

    def test_a_row_the_user_resolved_is_not_raised_again_while_the_alert_persists(self):
        self._tick()
        key = self._episode_key("budget_unknown")
        row = next(
            row for row in interrupts.list_open(
                self.conn, org_id=self.org, brand_id=self.brand, category=runtime.ALERT_CATEGORY,
                archive_stale=False,
            ) if row["dedupe_key"] == key
        )
        interrupts.resolve(self.conn, row["id"], actor="test", org_id=self.org)
        self._tick(today=self.today + timedelta(days=1))
        self.assertNotIn(key, self._open_keys())
        self.assertFalse(
            [k for k in self._open_keys() if k.startswith(f"ads-runtime:{self.live}:budget")]
        )

    def test_a_cleared_alert_and_old_dated_keys_resolve_on_the_next_tick(self):
        stale = [
            f"ads-runtime:{self.live}:source_date_passed",
            f"ads-runtime:{self.live}:{self.today}:budget_unknown",
            f"ads-runtime:{self.live}:{self.today}:plan_date_passed",
        ]
        other = f"ads-runtime:{self.in_grace}:source_date_passed"
        self._raise(*stale, other)
        health, _ = runtime._health(self.conn, self.org, self.brand, self.live, db.now_utc())
        codes = {item["code"] for item in health}
        self.assertNotIn("source_date_passed", codes)
        open_keys = self._open_keys()
        self.assertFalse(set(stale) & open_keys)
        self.assertIn(other, open_keys)  # another campaign's row is not this tick's
        self.assertEqual(
            {key for key in open_keys if key.startswith(f"ads-runtime:{self.live}:")},
            {self._episode_key(code) for code in codes},
        )
