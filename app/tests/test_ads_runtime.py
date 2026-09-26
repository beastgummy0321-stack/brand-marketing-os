"""Monitoring remains independent of human review disposition and platform mutation."""

import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import external_repository as external
from app.ads import external_sync, handoff_check, handoff_data, repository, runtime
from app.ads.adapters.external import SourceReadError
from app.brand_intelligence import repository as brands
from app.core import db, settings


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
        self.assertEqual(
            repository.get_campaign(self.conn, self.org, self.brand, self.campaign)["status"],
            "draft",
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
            self.assertEqual(job["status"], "partial")
            self.assertEqual(job["last_attempt_at"], now)
            self.assertEqual(job["tasks"], {})
            self.assertIsNone(job["last_success_at"])
            self.assertNotIn("private detail", job["error"])
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
        self.assertIn("plan_date_passed", [item["code"] for item in health])
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

    def _confirmed_handoffs(self):
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
                "VALUES(%s,%s,%s,%s,'ad',%s,'pause',%s,'confirmed',%s,%s)",
                (action, self.org, self.brand, self.campaign, ad["id"], change, old, old),
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
                "UPDATE ads_handoff_item SET entity_id=%s,status='confirmed',observed_at=%s,"
                "created_at=%s,updated_at=%s,evidence_json=%s WHERE id=%s",
                (
                    ad["id"],
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
        old, items = self._confirmed_handoffs()
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
