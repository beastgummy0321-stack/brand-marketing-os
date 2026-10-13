"""Real PostgreSQL falsifiers for the complete close operation, including helper commits."""

from datetime import timedelta
from unittest.mock import patch

from app.ads import closeout, repository, triage
from app.brand_intelligence import repository as brands
from app.core import db, interrupts
from app.tests.test_ads_closeout import ACTOR, CloseoutTestBase


class AtomicCloseTest(CloseoutTestBase):
    def prepared(self):
        row = self._campaign(
            cap=300, start_date=self.complete_day - timedelta(days=2), end_date=self.complete_day
        )
        self._three_days(row, spend=1000, purchases=5, revenue=2500)
        interrupts.enqueue(
            self.conn,
            org_id=self.org_id,
            brand_id=self.brand_id,
            category="ads_triage_closeout",
            message="待結案",
            dedupe_key=f"ads-triage:closeout:{row['id']}:{self.complete_day}",
        )
        self.conn.commit()
        return row["id"]

    def snapshot(self, campaign_id):
        with db.connection() as observer:
            row = repository.get_campaign(observer, self.org_id, self.brand_id, campaign_id)
            assert row is not None
            return {
                "campaign": {k: row[k] for k in ("status", "verdict", "verdict_json", "closed_at")},
                "learnings": [r["id"] for r in brands.list_learnings(observer, self.brand_id)],
                "open": [
                    r["id"]
                    for r in interrupts.list_open(
                        observer, org_id=self.org_id, brand_id=self.brand_id, archive_stale=False
                    )
                ],
            }

    def test_failure_at_each_write_boundary_rolls_back_and_retry_is_unique(self):
        stages = [
            (closeout.ads_learning, "write_learning"),
            (closeout.visual_learning, "write_visual_learnings"),
            (closeout.coordinate_learning, "write_coordinate_learnings"),
            (closeout.runtime, "resolve_alerts"),
            (triage, "resolve_campaign"),
        ]
        for owner, name in stages:
            with self.subTest(stage=name):
                campaign_id = self.prepared()
                before = self.snapshot(campaign_id)
                original = getattr(owner, name)

                def fail_after(conn, *args, **kwargs):
                    original(conn, *args, **kwargs)
                    conn.commit()
                    raise RuntimeError("injected_close_failure")

                with patch.object(owner, name, fail_after):
                    with self.assertRaisesRegex(RuntimeError, "injected_close_failure"):
                        closeout.close(
                            self.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR
                        )
                self.conn.commit()
                self.assertEqual(self.snapshot(campaign_id), before)

                closed = closeout.close(
                    self.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR
                )
                self.conn.commit()
                after = self.snapshot(campaign_id)
                self.assertEqual(after["campaign"]["status"], "closed")
                self.assertEqual(len(after["learnings"]), len(before["learnings"]) + 1)
                self.assertNotEqual(after["open"], before["open"])
                again = closeout.close(
                    self.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR
                )
                self.conn.commit()
                self.assertEqual(again["verdict_json"], closed["verdict_json"])
                self.assertEqual(again["closed_at"], closed["closed_at"])
                self.assertEqual(self.snapshot(campaign_id), after)

    def test_nested_failure_preserves_prior_outer_work(self):
        campaign_id = self.prepared()
        self.conn.execute("UPDATE brand SET name=%s WHERE id=%s", ("Prior receipt", self.brand_id))
        with patch.object(triage, "resolve_campaign", side_effect=RuntimeError("late_failure")):
            with self.assertRaisesRegex(RuntimeError, "late_failure"):
                closeout.close(self.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR)
        self.conn.commit()
        with db.connection() as observer:
            self.assertEqual(brands.get_brand(observer, self.brand_id)["name"], "Prior receipt")
        self.assertEqual(self.snapshot(campaign_id)["campaign"]["status"], "live")

    def test_foreign_brand_or_org_cannot_close(self):
        campaign_id = self.prepared()
        before = self.snapshot(campaign_id)
        for org, brand in ((self.org_id, "foreign-brand"), ("foreign-org", self.brand_id)):
            with self.subTest(org=org, brand=brand):
                with self.assertRaises(ValueError):
                    closeout.close(self.conn, org, brand, campaign_id, actor=ACTOR)
                self.conn.commit()
                self.assertEqual(self.snapshot(campaign_id), before)
