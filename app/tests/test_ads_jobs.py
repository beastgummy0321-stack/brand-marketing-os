"""Expired imported source dates must never dispatch a legacy closeout."""

import unittest
from datetime import date
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

    def test_dispatch_refreshes_queue_for_every_brand_with_a_non_closed_campaign(self):
        timestamp = int(db.now_utc().timestamp())
        with patch.object(triage, "refresh_queue", return_value={"items": []}) as refresh:
            jobs._dispatch_queue_refresh(timestamp)
        called_brands = {call.args[2] for call in refresh.call_args_list}
        self.assertIn(self.brand, called_brands)
        self.assertNotIn(self.closed_brand, called_brands)
