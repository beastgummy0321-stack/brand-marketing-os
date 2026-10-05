"""Durable per-ad monitoring and restart recovery, using Postgres and the real fake gateway."""

import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import (
    external_repository,
    review_jobs,
    review_monitor,
    review_monitor_source,
    review_rounds,
)
from app.core import db
from app.llm import gateway
from app.main import app
from app.tests.test_ads_review_cycle import ReviewCycleTest as _CycleFixture


class ReviewMonitorTest(unittest.TestCase):
    # Reuse ads-owned fixture operations, not another module's private repository.
    setUp = _CycleFixture.setUp
    observation = _CycleFixture.observation
    request = _CycleFixture.request
    reply = _CycleFixture.reply
    run_review = _CycleFixture.run_review

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute("DELETE FROM ads_review_monitor WHERE brand_id=%s", (self.brand,))
        self.conn.execute("DELETE FROM ads_review_round WHERE brand_id=%s", (self.brand,))
        self.conn.commit()

    def monitor(self):
        return review_monitor.get(self.conn, self.org, self.brand, self.campaign, self.ad["id"])

    def configure(self, **extra):
        current = self.monitor()
        return review_monitor.put(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            self.ad["id"],
            {
                "expected_revision": current["revision"] if current else 0,
                "enabled": True,
                "window_days": 3,
                "cadence_days": 7,
                "reset_window": False,
                **extra,
            },
        )

    def tick(self, now=None):
        return review_monitor.dispatch_due(self.conn, int((now or db.now_utc()).timestamp()) + 1)

    def account(self):
        return patch(
            "app.ads.external_sync.account_reader",
            return_value=(object(), {"timezone_name": "Asia/Taipei"}),
        )

    def fill_window(self):
        for days in range(6):
            self.observation(self.end - timedelta(days=days))

    def test_waiting_window_freezes_and_same_data_does_not_submit_again(self):
        self.configure()
        with self.account():
            self.tick()
            first = self.monitor()
            review = review_rounds.get(
                self.conn, self.org, self.brand, self.campaign, first["review_id"]
            )
            self.assertEqual(review["status"], "waiting")
            self.assertEqual(review["reserved_amount"], 0)
            self.configure()
            self.tick(db.now_utc() + timedelta(days=1))
            second = self.monitor()
            self.assertEqual(second["window"], first["window"])
            self.assertEqual(second["review_id"], first["review_id"])
            self.enqueue.assert_not_called()
            self.fill_window()
            self.configure()
            self.tick()
            filled = self.monitor()
            self.assertNotEqual(filled["review_id"], first["review_id"])
            self.assertEqual(filled["state"], "queued")
            self.assertEqual(self.enqueue.call_count, 1)
            self.configure()
            self.tick()
            self.assertEqual(self.enqueue.call_count, 1)
        self.assertEqual(self.fake.calls, [])

    def test_timezone_unknown_and_missing_dates_wait_without_paid_reservation(self):
        self.account_zone = None  # the bound account has no stored zone
        self.fill_window()
        # The unknown zone fails closed one more day back (F50 Contract K), so the frozen window
        # and its prior period reach one day earlier than `fill_window`.
        self.observation(self.end - timedelta(days=6))
        self.configure()
        self.tick()
        first = self.monitor()
        self.assertEqual(first["state"], "waiting")
        self.assertIsNotNone(first["window"])
        self.assertEqual(self.fake.calls, [])
        self.enqueue.assert_not_called()
        with self.account():
            self.configure()
            self.tick()
        self.assertEqual(self.monitor()["state"], "queued")

    def test_manual_http_optin_and_pause_are_preserved_and_sources_continue(self):
        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        self.assertIsNone(client.get(base + f"/review-monitors/{self.ad['id']}").json()["monitor"])
        body = {
            "entity_id": self.ad["id"],
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }
        response = client.post(base + "/reviews", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        monitor = response.json()["monitor"]
        self.assertTrue(monitor["enabled"])
        self.assertEqual(monitor["cadence_days"], 7)
        paused = client.put(
            base + f"/review-monitors/{self.ad['id']}",
            json={
                "expected_revision": monitor["revision"],
                "enabled": False,
                "window_days": 3,
                "cadence_days": 7,
            },
        )
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertFalse(client.post(base + "/reviews", json=body).json()["monitor"]["enabled"])
        windows = review_monitor.required_windows(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(windows[0]["start"], (self.start - timedelta(days=3)).isoformat())
        self.assertEqual(self.monitor()["state"], "paused")
        self.assertEqual(self.tick()["reviews_enqueued"], 0)
        conflict = client.put(
            base + f"/review-monitors/{self.ad['id']}",
            json={
                "expected_revision": 0,
                "enabled": True,
            },
        )
        self.assertEqual(conflict.status_code, 409)

    def test_completed_and_deferred_advance_only_at_due_and_keep_same_ad_previous(self):
        self.observation()
        self.reply()
        row = self.run_review(
            self.request(end=self.end - timedelta(days=1), start=self.start - timedelta(days=1))
        )
        # That older window has no sample; provide it and create the usable round.
        if row["status"] == "waiting":
            self.observation(self.end - timedelta(days=1))
            row = self.run_review(
                self.request(end=self.end - timedelta(days=1), start=self.start - timedelta(days=1))
            )
        self.assertEqual(row["status"], "ready")
        review_monitor.track_manual(self.conn, row)
        self.configure(window_days=3)
        due = db.now_utc() + timedelta(seconds=30)
        review_rounds.decide(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            row["id"],
            "deferred",
            "等待重看",
            due.isoformat(),
        )
        self.assertIsNone(self.monitor()["window"])
        self.assertEqual(self.tick()["monitors_checked"], 0)
        self.fill_window()
        with self.account():
            self.tick(due + timedelta(seconds=1))
        next_round = review_rounds.get(
            self.conn, self.org, self.brand, self.campaign, self.monitor()["review_id"]
        )
        self.assertEqual(next_round["previous_id"], row["id"])
        self.assertEqual(next_round["status"], "queued")
        self.assertEqual(len(self.fake.calls), 1)

    def test_saved_output_gap_recovers_once_without_provider_and_unknown_is_held(self):
        self.observation()
        self.reply()
        row = self.request()
        with patch.object(review_jobs, "apply_saved_task", side_effect=RuntimeError("crash")):
            broken = self.run_review(row)
        self.assertEqual(broken["status"], "unknown")
        self.assertIsNone(broken["llm_task_id"])
        self.assertEqual(len(self.fake.calls), 1)
        result = review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(result["reviews_recovered"], 1)
        ready = review_rounds.get(self.conn, self.org, self.brand, self.campaign, row["id"])
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["reservation_state"], "settled")
        self.assertIsNotNone(ready["llm_task_id"])
        review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(len(self.fake.calls), 1)
        self.observation(clicks=21)
        unknown = self.request()
        self.conn.execute(
            "UPDATE ads_review_round SET status='running' WHERE id=%s", (unknown["id"],)
        )
        self.conn.commit()
        result = review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(result["reviews_unknown"], 1)
        unknown = review_rounds.get(self.conn, self.org, self.brand, self.campaign, unknown["id"])
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["reservation_state"], "held")
        before = self.enqueue.call_count
        review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(self.enqueue.call_count, before)

    def test_queued_gap_requeues_only_without_saved_or_active_task(self):
        self.observation()
        row = self.request()
        self.enqueue.reset_mock()
        with patch("app.ads.review_jobs.background.is_active", return_value=False):
            result = review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(result["reviews_enqueued"], 1)
        self.enqueue.assert_called_once_with(self.org, self.brand, self.campaign, row["id"])
        self.enqueue.reset_mock()
        with patch("app.ads.review_jobs.background.is_active", return_value=True):
            review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.enqueue.assert_not_called()

    def source_handoff(self, review, *, observed=None, native_id="new-B2"):
        entity = external_repository.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "ad",
                "native_id": native_id,
                "creative": {},
                "name": "新測試",
            },
        )
        set_id, action_id, handoff_id = db.new_id("acs"), db.new_id("act"), db.new_id("ahi")
        plan = {
            "review_id": review["id"],
            "review_evidence_hash": review["evidence_hash"],
            "recommendation_id": "recommendation-1",
            "source_entity_id": self.ad["id"],
            "items": [{"kind": "new_ad"}],
        }
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,'hash','hash','新增','2026-09','approved',%s,'test')",
            (set_id, self.org, self.brand, self.campaign, db.new_id("op"), db.jsonb(plan)),
        )
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "before_json,after_json,change_set_id,first_observed_at) "
            "VALUES(%s,%s,%s,%s,'ad','placement','publish','{}','{}',%s,%s)",
            (action_id, self.org, self.brand, self.campaign, set_id, observed),
        )
        self.conn.execute(
            "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,action_id,"
            "planned_kind,planned_id,name,expected_json,entity_id,status,evidence_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,'ad','placement','新廣告','{}',%s,'unknown',%s)",
            (
                handoff_id,
                self.org,
                self.brand,
                self.campaign,
                set_id,
                action_id,
                entity["id"],
                db.jsonb(
                    {"entity_exists": True, "setting_matches": None, "material_evidence": "unknown"}
                ),
            ),
        )
        self.conn.commit()
        return entity

    def test_b2_inherits_monitor_without_faking_previous_or_early_ai(self):
        self.observation()
        self.reply(recommendation="new_test", suggested_copy={})
        row = self.run_review(self.request())
        review_monitor.track_manual(self.conn, row)
        entity = self.source_handoff(row, observed=db.now_utc())
        with self.account():
            result = self.tick()
        self.assertEqual(result["monitors_discovered"], 1)
        new = review_monitor.get(self.conn, self.org, self.brand, self.campaign, entity["id"])
        self.assertEqual(new["state"], "waiting")
        self.assertIsNone(new["review_id"])
        self.assertIsNone(new["window"]["previous_id"])
        source = review_monitor_source.source_review(
            self.conn, self.org, self.brand, self.campaign, entity["id"]
        )
        self.assertEqual(source["review_id"], row["id"])
        self.assertFalse(source["readback"]["delivery_confirmed"])
        self.assertIsNone(source["readback"]["setting_matches"])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.tick()["monitors_discovered"], 0)

    def test_compact_action_evidence_retains_counterevidence_without_raw_snapshots(self):
        raw = {
            "id": "act",
            "verification_state": "deviated",
            "first_observed_at": "date",
            "before_json": {"body": "舊"},
            "after_json": {"body": "計畫"},
            "evidence_json": {
                "setting_matches": False,
                "observed": {"body": "實際"},
                "snapshot": {"parents": ["x" * 20000]},
            },
        }
        summary = review_monitor_source.action_summary(raw)
        self.assertEqual(summary["evidence_json"]["observed"], {"body": "實際"})
        self.assertFalse(summary["evidence_json"]["setting_matches"])
        self.assertEqual(summary["first_observed_at"], "date")
        self.assertNotIn("snapshot", summary["evidence_json"])

    def test_first_b2_window_can_judge_without_inventing_pre_creation_zeroes(self):
        self.observation()
        self.reply(recommendation="new_test", suggested_copy={})
        source = self.run_review(self.request())
        review_monitor.track_manual(self.conn, source)
        self.configure(window_days=3)
        entity = self.source_handoff(source, observed=db.now_utc() - timedelta(days=4))
        self.ad = entity
        for days in range(3):
            self.observation(self.end - timedelta(days=days))
        with self.account():
            self.tick()
        current = self.monitor()
        row = review_rounds.get(
            self.conn, self.org, self.brand, self.campaign, current["review_id"]
        )
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["previous_id"])
        self.assertEqual(row["evidence_json"]["previous"]["series"], [])
        self.assertFalse(row["evidence_json"]["previous"]["comparison_available"])
        self.assertEqual(row["evidence_json"]["source_review"]["review_id"], source["id"])
        self.assertEqual(row["evidence_json"]["current"]["days_present"], 3)

    def test_bounded_recovery_does_not_starve_queued_behind_unknown_rows(self):
        self.observation()
        first = self.request()
        self.conn.execute(
            "UPDATE ads_review_round SET status='unknown' WHERE id=%s", (first["id"],)
        )
        self.observation(clicks=99)
        queued = self.request()
        self.enqueue.reset_mock()
        with patch("app.ads.review_jobs.background.is_active", return_value=False):
            now = int(db.now_utc().timestamp())
            review_jobs.recover(self.conn, now, limit=1, bootstrap=True)
            self.enqueue.assert_not_called()
            review_jobs.recover(self.conn, now + 1, limit=1, bootstrap=True)
        self.enqueue.assert_called_once_with(self.org, self.brand, self.campaign, queued["id"])

    def test_invalid_source_does_not_starve_later_b2_and_paused_source_stays_paused(self):
        self.observation()
        self.reply(recommendation="new_test", suggested_copy={})
        source = self.run_review(self.request())
        review_monitor.track_manual(self.conn, source)
        self.configure(enabled=False)
        invalid = self.source_handoff(source)
        self.conn.execute(
            "UPDATE ads_change_set SET plan_json=jsonb_set(plan_json,'{review_evidence_hash}',"
            "'\"wrong\"') WHERE id IN (SELECT change_set_id FROM ads_handoff_item "
            "WHERE entity_id=%s)",
            (invalid["id"],),
        )
        valid = self.source_handoff(source, native_id="new-B3")
        now = int(db.now_utc().timestamp())
        first = review_monitor.dispatch_due(self.conn, now, limit=1)
        self.assertEqual(first["monitors_discovered"], 0)
        second = review_monitor.dispatch_due(self.conn, now + 1, limit=1)
        self.assertEqual(second["monitors_discovered"], 1)
        child = review_monitor.get(self.conn, self.org, self.brand, self.campaign, valid["id"])
        self.assertFalse(child["enabled"])
        self.assertEqual(child["state"], "paused")
        self.assertIsNone(
            review_monitor_source.source_review(
                self.conn, self.org, self.brand, self.campaign, invalid["id"]
            )
        )
        self.assertEqual(len(self.fake.calls), 1)

    def test_unknown_saved_task_is_not_repeatedly_counted_or_resubmitted(self):
        from app.llm.providers import ProviderTimeoutError

        self.observation()
        self.fake.exception = ProviderTimeoutError("timeout")
        self.fake.fail_first_n = 1
        unknown = self.run_review(self.request())
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNotNone(unknown["llm_task_id"])
        self.enqueue.reset_mock()
        result = review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertEqual(result["reviews_unknown"], 0)
        self.enqueue.assert_not_called()
        self.assertEqual(len(self.fake.calls), 1)

    def test_completed_round_advances_cadence_without_closing_campaign(self):
        self.observation()
        self.reply()
        row = self.run_review(self.request())
        review_monitor.track_manual(self.conn, row)
        review_rounds.decide(
            self.conn, self.org, self.brand, self.campaign, row["id"], "completed", "本回結束"
        )
        monitor = self.monitor()
        self.assertIsNone(monitor["window"])
        self.assertIsNone(monitor["review_id"])
        self.assertGreater(monitor["next_check_at"], db.now_utc() + timedelta(days=6))
        self.assertEqual(self.tick()["reviews_enqueued"], 0)
        latest = review_rounds.get(self.conn, self.org, self.brand, self.campaign, row["id"])
        review_monitor.track_manual(self.conn, latest)
        self.assertIsNone(self.monitor()["window"])

    def test_http_enqueue_gap_has_durable_monitor_link_before_recovery(self):
        self.observation()
        old = self.request()
        self.conn.execute("UPDATE ads_review_round SET status='unknown' WHERE id=%s", (old["id"],))
        self.conn.commit()
        review_monitor.track_manual(self.conn, old)
        configured = self.configure(enabled=False, window_days=5, cadence_days=9)
        self.observation(clicks=99)
        self.reply()
        captured = {}

        def crash_before_enqueue(org, brand, campaign, review_id):
            # A separate connection must already see BOTH records before dispatch is attempted.
            with db.connection() as connection:
                db.set_tenant_scope(connection, org)
                monitor = review_monitor.get(connection, org, brand, campaign, self.ad["id"])
                row = review_rounds.get(connection, org, brand, campaign, review_id)
                self.assertEqual(monitor["review_id"], review_id)
                self.assertEqual(row["status"], "queued")
                self.assertFalse(monitor["enabled"])
                self.assertEqual((monitor["window_days"], monitor["cadence_days"]), (5, 9))
                self.assertEqual(monitor["revision"], configured["revision"])
            captured["review_id"] = review_id
            raise RuntimeError("Simulated web loss after commit and before enqueue")

        client = TestClient(app, raise_server_exceptions=False)
        route = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        with patch.object(review_jobs, "enqueue", side_effect=crash_before_enqueue):
            response = client.post(
                route + "/reviews",
                json={
                    "entity_id": self.ad["id"],
                    "start": self.start.isoformat(),
                    "end": self.end.isoformat(),
                },
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.fake.calls), 0)
        self.assertEqual(self.monitor()["review_id"], captured["review_id"])
        self.enqueue.reset_mock()
        with patch("app.ads.review_jobs.background.is_active", return_value=False):
            review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.enqueue.assert_called_once_with(
            self.org, self.brand, self.campaign, captured["review_id"]
        )
        restored = self.run_review({"id": captured["review_id"]})
        self.assertEqual(restored["status"], "ready")
        self.assertEqual(self.monitor()["review_id"], restored["id"])
        self.assertFalse(self.monitor()["enabled"])
        self.assertEqual(len(self.fake.calls), 1)
        self.enqueue.reset_mock()
        review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.enqueue.assert_not_called()
        self.assertEqual(len(self.fake.calls), 1)

    def test_monitor_link_failure_rolls_back_new_manual_review(self):
        self.observation()
        client = TestClient(app, raise_server_exceptions=False)
        route = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        with patch.object(review_monitor, "track_manual", side_effect=RuntimeError("crash")):
            response = client.post(
                route + "/reviews",
                json={
                    "entity_id": self.ad["id"],
                    "start": self.start.isoformat(),
                    "end": self.end.isoformat(),
                },
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) AS n FROM ads_review_round WHERE brand_id=%s", (self.brand,)
            ).fetchone()["n"],
            0,
        )
        self.assertIsNone(self.monitor())
        self.enqueue.assert_not_called()
        self.assertEqual(len(self.fake.calls), 0)

    def test_decision_and_monitor_update_are_one_commit(self):
        self.observation()
        self.reply()
        ready = self.run_review(self.request())
        review_monitor.track_manual(self.conn, ready)
        before = self.monitor()
        client = TestClient(app, raise_server_exceptions=False)
        route = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        with patch.object(review_monitor, "on_decision", side_effect=RuntimeError("crash")):
            response = client.post(
                route + f"/reviews/{ready['id']}/decision",
                json={
                    "decision": "deferred",
                    "reason": "之後重看",
                    "revisit_at": (db.now_utc() + timedelta(days=1)).isoformat(),
                },
            )
        self.assertEqual(response.status_code, 500)
        unchanged = review_rounds.get(self.conn, self.org, self.brand, self.campaign, ready["id"])
        self.assertEqual(unchanged["status"], "ready")
        self.assertEqual(self.monitor()["next_check_at"], before["next_check_at"])
        self.assertEqual(self.monitor()["review_id"], ready["id"])

    def test_legacy_task_missing_explicit_scope_is_unknown_not_adopted(self):
        self.reply()
        for index, missing in enumerate(("campaign_id", "evidence_hash")):
            with self.subTest(missing=missing):
                self.observation(clicks=20 + index)
                review = self.request()
                evidence = review["evidence_json"]
                self.conn.execute(
                    "UPDATE ads_review_round SET status='running' WHERE id=%s", (review["id"],)
                )
                self.conn.commit()
                scope = {
                    "brand_id": self.brand,
                    "review_id": review["id"],
                    "campaign_id": self.campaign,
                    "evidence_hash": review["evidence_hash"],
                }
                del scope[missing]
                task = gateway.run_task(
                    self.conn,
                    self.fake,
                    brand_id=self.brand,
                    task_type=review_rounds.TASK_TYPE,
                    prompt_template_id="ads/review_round",
                    prompt_template_version=evidence["template_hash"],
                    system=review_rounds.PROMPT.read_text(encoding="utf-8"),
                    messages=[{"role": "user", "content": "legacy fixture"}],
                    context=gateway.TaskContext(scope, [], evidence["brand_version"]),
                    options=gateway.TaskOptions(model=evidence["model"], max_retries=0),
                )
                self.assertEqual(task["status"], "succeeded")
                calls = len(self.fake.calls)
                self.enqueue.reset_mock()
                review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
                saved = review_rounds.get(
                    self.conn, self.org, self.brand, self.campaign, review["id"]
                )
                self.assertEqual(saved["status"], "unknown")
                self.assertEqual(saved["result_json"], {})
                self.assertEqual(saved["reservation_state"], "held")
                self.assertIsNone(saved["llm_task_id"])
                review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
                self.assertEqual(len(self.fake.calls), calls)
                self.enqueue.assert_not_called()


# Do not collect the imported fixture class as another copy of its own tests.
del _CycleFixture
