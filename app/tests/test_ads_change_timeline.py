"""app/tests/test_ads_change_timeline.py — F27-I08 falsifiers: Contract H (pre-dispatch
correction 1), read-time timeline facts on every change item -- nothing is ever scheduled at
approve; `spend_stopped`/`delivery_started`/`next_review_at` are recomputed from the item's own
stored `approved_at`/`verified_at` and the campaign's synced coverage on every `data.get()` call.
"""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from app.ads import change_control_data as data
from app.ads import change_control_verify as verification
from app.ads import external_repository as external
from app.ads import external_sync
from app.core import db
from app.tests.test_ads_change_control import ChangeControlTest as _ChangeFixture


class ChangeTimelineTest(unittest.TestCase):
    # Reuse ads-owned fixture operations, not a second private setup (same seam
    # `test_ads_review_monitor.py` uses against `test_ads_review_cycle.py`).
    setUp = _ChangeFixture.setUp
    entity = _ChangeFixture.entity
    create = _ChangeFixture.create
    approve = _ChangeFixture.approve

    # -- fixture helpers ----------------------------------------------------------------------

    def daily(self, entity_id, day, *, spend=0.0, impressions=0):
        self.conn.execute(
            "INSERT INTO ads_external_daily(id,org_id,brand_id,campaign_id,entity_id,day,"
            "metric_scope,attribution_key,currency,spend,impressions,availability,source) "
            "VALUES(%s,%s,%s,%s,%s,%s,'ad','default','TWD',%s,%s,%s,'fixture') "
            "ON CONFLICT (org_id,brand_id,entity_id,day,metric_scope,attribution_key,currency) "
            "DO UPDATE SET spend=EXCLUDED.spend,impressions=EXCLUDED.impressions",
            (
                db.new_id("aed"), self.org, self.brand, self.campaign, entity_id, day,
                spend, impressions, db.jsonb({"spend": "available", "impressions": "available"}),
            ),
        )
        self.conn.commit()

    def coverage(self, start, end):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": start.isoformat(), "end": end.isoformat()},
            },
        )
        self.conn.commit()

    def readback(self, current, *, native_status=None, body=None):
        ad = copy.deepcopy(self.ad)
        if native_status is not None:
            ad["native_status"] = native_status
        if body is not None:
            ad["creative"]["fields"]["body"] = body
        proof = {"entity": ad, "parents": [self.group, self.root]}

        class Reader:
            def verify_native(self, *args, **kwargs):
                return proof

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            return verification.check(
                self.conn, self.org, self.brand, self.campaign,
                current["id"], current["items"][0]["id"], "test",
            )

    def new_ad_item(self, *, verified_at=None):
        """`new_ad` items are really created through `handoff_new_ad`/`handoff_check` (out of this
        issue's scope) -- inserted directly, same isolation style `test_ads_triage_ladder.py
        ::confirm_new_ad` uses, plus the `target` dict `change_control_data.get()`'s own
        `platform_url` lookup needs."""
        created = self.entity(
            "9", "ad", parent_native_kind="adset", parent_native_id="2",
            creative={"kind": "image", "fields": {"body": "新廣告"}},
        )
        item_id, set_id = db.new_id("adx"), db.new_id("acs")
        item = {
            "id": item_id, "kind": "new_ad", "target_id": self.group["id"], "before": {},
            "after": {}, "reason": "x", "target": {"platform": "fake"},
        }
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s,'test',%s)",
            (
                set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "新增",
                self.month, db.jsonb({"items": [item]}), db.now_utc(),
            ),
        )
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state,verified_at) "
            "VALUES(%s,%s,%s,%s,'group',%s,'publish',%s,%s,%s)",
            (
                item_id, self.org, self.brand, self.campaign, self.group["id"], set_id,
                "confirmed" if verified_at else "pending", verified_at,
            ),
        )
        self.conn.execute(
            "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,"
            "action_id,planned_kind,planned_id,name,expected_json,entity_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,'ad',%s,'新廣告','{}',%s)",
            (
                db.new_id("ahi"), self.org, self.brand, self.campaign, set_id, item_id,
                "placement_1", created["id"],
            ),
        )
        self.conn.commit()
        return set_id, item_id, created

    # -- pause: spend_stopped -------------------------------------------------------------------

    def test_pause_spend_stopped_null_before_verified_and_by_coverage_then_spend(self):
        first = self.create(
            items=[{
                "kind": "pause", "target_id": self.ad["id"], "after": {"status": "PAUSED"},
                "reason": "停止風險",
            }]
        )
        approved = self.approve(first)
        timeline = approved["items"][0]["timeline"]
        self.assertIsNone(timeline["spend_stopped"])
        self.assertIsNone(timeline["delivery_started"])
        self.assertIsNone(timeline["next_review_at"])

        confirmed = self.readback(approved, native_status="PAUSED")
        self.assertEqual(confirmed["items"][0]["verification_state"], "confirmed")
        verified_at = confirmed["items"][0]["verified_at"]
        self.assertIsNotNone(verified_at)
        day = verified_at.date() + timedelta(days=1)

        # No coverage recorded at all -> unknown, not a guess.
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertIsNone(current["items"][0]["timeline"]["spend_stopped"])
        # `next_review_at` stays null for `pause` even once verified (correction 1).
        self.assertIsNone(current["items"][0]["timeline"]["next_review_at"])

        # Coverage recorded, but the day after `verified_at` is not inside it yet.
        self.coverage(day - timedelta(days=30), verified_at.date())
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertIsNone(current["items"][0]["timeline"]["spend_stopped"])

        # Day covered, no synced row for it -> true ("no row" branch).
        self.coverage(day - timedelta(days=30), day)
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertTrue(current["items"][0]["timeline"]["spend_stopped"])

        # Day covered, a synced row with zero spend -> still true ("spend 0" branch).
        self.daily(self.ad["id"], day, spend=0)
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertTrue(current["items"][0]["timeline"]["spend_stopped"])

        # Real spend on that day -> false.
        self.daily(self.ad["id"], day, spend=50)
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertFalse(current["items"][0]["timeline"]["spend_stopped"])

    # -- copy: delivery_started + next_review_at -------------------------------------------------

    def test_copy_delivery_started_null_by_coverage_then_impressions_and_next_review_at(self):
        first = self.create()
        approved = self.approve(first)
        timeline = approved["items"][0]["timeline"]
        self.assertIsNone(timeline["delivery_started"])
        self.assertIsNone(timeline["spend_stopped"])
        self.assertIsNone(timeline["next_review_at"])

        confirmed = self.readback(approved, body="新文案")
        self.assertEqual(confirmed["items"][0]["verification_state"], "confirmed")
        verified_at = confirmed["items"][0]["verified_at"]
        self.assertEqual(
            confirmed["items"][0]["timeline"]["next_review_at"],
            (verified_at + timedelta(days=7)).date(),
        )
        day = verified_at.date() + timedelta(days=1)

        # No coverage yet -> unknown.
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertIsNone(current["items"][0]["timeline"]["delivery_started"])

        # Coverage recorded, but has not reached a day past `verified_at` yet.
        self.coverage(day - timedelta(days=30), verified_at.date())
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertIsNone(current["items"][0]["timeline"]["delivery_started"])

        # A covered day past `verified_at`, no impressions -> false.
        self.coverage(day - timedelta(days=30), day)
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertFalse(current["items"][0]["timeline"]["delivery_started"])

        # That day shows impressions -> true.
        self.daily(self.ad["id"], day, impressions=100)
        current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertTrue(current["items"][0]["timeline"]["delivery_started"])

    # -- budget: next_review_at = approved_at + 3 days, never spend/delivery --------------------

    def test_budget_next_review_at_three_days_after_approval_regardless_of_verification(self):
        first = self.create(
            items=[{
                "kind": "budget", "target_id": self.group["id"], "after": {"daily_amount": 800},
                "reason": "降低風險",
            }]
        )
        approved = self.approve(first)
        timeline = approved["items"][0]["timeline"]
        self.assertEqual(
            timeline["next_review_at"], (approved["approved_at"] + timedelta(days=3)).date()
        )
        self.assertIsNone(timeline["spend_stopped"])
        self.assertIsNone(timeline["delivery_started"])

    # -- new_ad: delivery_started + next_review_at (7 days), via the created entity -------------

    def test_new_ad_delivery_started_and_next_review_at_use_the_created_entity(self):
        set_id, item_id, created = self.new_ad_item()
        unverified = data.get(self.conn, self.org, self.brand, self.campaign, set_id)
        timeline = unverified["items"][0]["timeline"]
        self.assertIsNone(timeline["delivery_started"])
        self.assertIsNone(timeline["next_review_at"])

        verified_at = db.now_utc() - timedelta(days=2)
        self.conn.execute(
            "UPDATE ads_action SET verification_state='confirmed',verified_at=%s WHERE id=%s",
            (verified_at, item_id),
        )
        self.conn.commit()
        day = verified_at.date() + timedelta(days=1)
        self.coverage(day - timedelta(days=30), day)
        self.daily(created["id"], day, impressions=1)
        current = data.get(self.conn, self.org, self.brand, self.campaign, set_id)
        item = current["items"][0]
        self.assertTrue(item["timeline"]["delivery_started"])
        self.assertEqual(
            item["timeline"]["next_review_at"], (item["verified_at"] + timedelta(days=7)).date()
        )
        self.assertIsNone(item["timeline"]["spend_stopped"])


# Do not collect the imported fixture class as another copy of its own tests.
del _ChangeFixture
