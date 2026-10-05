"""Expired imported source dates must never dispatch a legacy closeout."""

import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch

from app import background
from app.ads import closeout, jobs, repository, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db


class JobsOriginTest(unittest.TestCase):
    def test_expired_campaigns_keep_history_without_automatic_close(self):
        conn = db.current()
        org = db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="排程隔離", actor="test", client_name=None
        )["id"]
        imported = external.create_imported_campaign(conn, org, brand, name="來源已結束")
        internal = repository.create_campaign(
            conn,
            org,
            brand,
            {
                "name": "內部",
                "goal_text": "目標",
                "objective": "購買",
                "status": "ended",
                "start_date": date(2000, 1, 1),
                "end_date": date(2000, 1, 2),
            },
        )
        conn.execute(
            "UPDATE ads_campaign SET status='ended',end_date='2000-01-02' WHERE id=%s",
            (imported["id"],),
        )
        conn.commit()
        with patch.object(closeout, "close") as close:
            jobs.close_expired_campaigns(org)
        ids = [call.args[3] for call in close.call_args_list]
        self.assertNotIn(internal["id"], ids)
        self.assertNotIn(imported["id"], ids)
        self.assertEqual(
            repository.get_campaign(conn, org, brand, imported["id"])["status"], "ended"
        )


class QueueRefreshDailyTest(unittest.TestCase):
    """F27-I09 Contract I / Done #1: the daily periodic sweeps every brand with a non-closed
    campaign through `triage.refresh_queue`, the same "one distinct (org_id, brand_id) over
    non-closed campaigns" shape `_dispatch_runtime_beat`'s own falsifier
    (`test_ads_runtime_events.py::RuntimeBeatTest`) already covers for the beat wrapper."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每日佇列刷新（有在投）", actor="test",
            client_name=None,
        )["id"]
        self.closed_brand = brands.create_brand(
            self.conn, org_id=self.org, name="每日佇列刷新（全部關閉）", actor="test",
            client_name=None,
        )["id"]
        external.create_imported_campaign(self.conn, self.org, self.brand, name="投放中活動")
        closed = external.create_imported_campaign(
            self.conn, self.org, self.closed_brand, name="已關閉活動",
        )
        self.conn.execute(
            "UPDATE ads_campaign SET status='closed' WHERE id=%s", (closed["id"],),
        )
        self.conn.commit()

    def test_register_task_wires_the_periodic_cron(self):
        jobs.register_tasks()
        a = background.app()
        self.assertIn("ads.queue_refresh_daily", a.tasks,
                       "register_tasks() 必須連 periodic dispatch task 一起掛")
        key = ("ads.queue_refresh_daily", "ads_queue_refresh_daily")
        self.assertIn(key, a.periodic_registry.periodic_tasks,
                       "dispatch task 必須真的用 periodic() 註冊，不能只是掛了普通 task")
        self.assertEqual(a.periodic_registry.periodic_tasks[key].cron, "30 6 * * *")

    def test_dispatch_enqueues_one_refresh_job_per_brand_with_a_non_closed_campaign(self):
        # F50 Contract J: the dispatcher only enqueues; the refresh runs in each brand's own job.
        timestamp = int(db.now_utc().timestamp())
        with (
            patch.object(triage, "refresh_queue") as refresh,
            patch.object(background, "is_active", return_value=False),
            patch.object(background, "enqueue", return_value=True) as enqueue,
        ):
            jobs._dispatch_queue_refresh(timestamp)
        refresh.assert_not_called()
        calls = {call.kwargs["brand_id"]: call for call in enqueue.call_args_list}
        self.assertIn(self.brand, calls)
        self.assertNotIn(self.closed_brand, calls)
        call = calls[self.brand]
        self.assertEqual(call.args, (jobs.QUEUE_REFRESH_TASK,))
        self.assertEqual((call.kwargs["org_id"], call.kwargs["lock"]),
                         (self.org, "ads-queue-refresh:" + self.brand))

    def test_register_tasks_registers_the_per_brand_job_through_the_wrapper(self):
        jobs.register_tasks()
        task = background.app().tasks[jobs.QUEUE_REFRESH_TASK]
        self.assertTrue(background.is_registered_through_register(task))

    def test_a_refresh_raising_for_one_brand_fails_its_job_and_not_the_others(self):
        other = brands.create_brand(
            self.conn, org_id=self.org, name="每日佇列刷新（另一個）", actor="test",
            client_name=None,
        )["id"]
        external.create_imported_campaign(self.conn, self.org, other, name="另一個活動")
        self.conn.commit()
        background.register(jobs.QUEUE_REFRESH_TASK, jobs.refresh_brand_queue)
        task = background.app().tasks[jobs.QUEUE_REFRESH_TASK]

        def refresh(conn, org_id, brand_id):
            if brand_id == self.brand:
                raise RuntimeError("private refresh failure")
            return {"items": []}

        with patch.object(triage, "refresh_queue", side_effect=refresh) as called:
            with (
                self.assertRaises(background.JobFailed) as raised,
                self.assertLogs("app.ads.jobs", "ERROR"),
            ):
                task.func(org_id=self.org, brand_id=self.brand)
            self.assertEqual(raised.exception.code, jobs.QUEUE_REFRESH_FAILED)
            self.assertNotIn("private", raised.exception.text or "")
            self.assertIsNone(task.func(org_id=self.org, brand_id=other))
        self.assertEqual([c.args[2] for c in called.call_args_list], [self.brand, other])

    def test_a_failed_refresh_job_is_counted_failed_by_the_queue(self):
        # Real procrastinate: the raising brand's job ends failed (the bell's `failed_today`) with
        # its stored code; the other brand's job succeeds.
        other = brands.create_brand(
            self.conn, org_id=self.org, name="每日佇列刷新（成功）", actor="test",
            client_name=None,
        )["id"]
        self.conn.commit()
        # Only this task: a periodic one registered here would be deferred by the worker too.
        background.register(jobs.QUEUE_REFRESH_TASK, jobs.refresh_brand_queue)
        since = datetime(2000, 1, 1, tzinfo=UTC)
        before = background.queue_snapshot(since=since)["failed_today"].get(self.org, 0)
        lock_bad = "ads-queue-refresh:" + self.brand + ":" + db.new_id("t")
        lock_ok = "ads-queue-refresh:" + other + ":" + db.new_id("t")
        background.enqueue(jobs.QUEUE_REFRESH_TASK, org_id=self.org, lock=lock_bad,
                           brand_id=self.brand)
        background.enqueue(jobs.QUEUE_REFRESH_TASK, org_id=self.org, lock=lock_ok,
                           brand_id=other)

        def refresh(conn, org_id, brand_id):
            if brand_id == self.brand:
                raise RuntimeError("boom")
            return {"items": []}

        with patch.object(triage, "refresh_queue", side_effect=refresh):
            self.conn.commit()
            background.app().run_worker(wait=False)
        bad = background.outcome(lock_bad)
        self.assertEqual((bad["state"], bad["code"]), ("failed", jobs.QUEUE_REFRESH_FAILED))
        self.assertEqual(background.outcome(lock_ok)["state"], "done")
        after = background.queue_snapshot(since=since)["failed_today"].get(self.org, 0)
        self.assertEqual(after, before + 1)
