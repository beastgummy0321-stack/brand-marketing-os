"""app/tests/test_ads_lifecycle.py — F49 Contract L: one owner of "what state is this campaign in"
and "is this ad running" (`app/ads/lifecycle.py`).

Pure rules first (the Meta status table, internal and imported states, the grace days), then the
writer (`record`), the selectors and the closeout refusal on a draft, against the database.
"""

import unittest
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
from app.ads import closeout, lifecycle
from app.ads import external_repository as external
from app.ads import repository as campaigns
from app.ads.adapters import meta_read
from app.brand_intelligence import repository as brands
from app.core import db, settings

TODAY = date(2026, 10, 4)

# Contract L's Meta table, written out once here: the falsifier for `meta_read.STATUS_TABLE`.
META = {
    "ACTIVE": ("running", "投放中"),
    "IN_PROCESS": ("not_running", "審核中"),
    "PENDING_REVIEW": ("not_running", "審核中"),
    "PREAPPROVED": ("not_running", "審核中"),
    "PENDING_BILLING_INFO": ("not_running", "待付款設定"),
    "WITH_ISSUES": ("not_running", "有問題"),
    "DISAPPROVED": ("not_running", "被拒登"),
    "PAUSED": ("off", "已暫停"),
    "ADSET_PAUSED": ("off", "所屬廣告組已暫停"),
    "CAMPAIGN_PAUSED": ("off", "所屬活動已暫停"),
    "ARCHIVED": ("off", "已封存"),
    "DELETED": ("off", "已刪除"),
}
UNKNOWN = {"state": "unknown", "label": "平台狀態不明"}


def _meta(status):
    return {"platform": "meta", "native_status": status}


class DeliveryTest(unittest.TestCase):
    def test_every_meta_code_maps_to_its_state_and_label(self):
        self.assertEqual(set(meta_read.STATUS_TABLE), set(META))
        for code, (state, label) in META.items():
            with self.subTest(code=code):
                self.assertEqual(lifecycle.delivery(_meta(code)), {"state": state, "label": label})

    def test_none_an_unmapped_code_and_an_unknown_platform_are_unknown(self):
        self.assertEqual(lifecycle.delivery(_meta(None)), UNKNOWN)
        self.assertEqual(lifecycle.delivery(_meta("SOME_FUTURE_STATUS")), UNKNOWN)
        self.assertEqual(lifecycle.delivery({"platform": "other", "native_status": "ACTIVE"}),
                         UNKNOWN)

    def test_the_simulated_platform_reads_metas_vocabulary(self):
        self.assertEqual(
            lifecycle.delivery({"platform": "simulated", "native_status": "ACTIVE"})["state"],
            "running",
        )

    def test_running_judged_and_may_spend(self):
        self.assertIs(lifecycle.ad_running(_meta("ACTIVE")), True)
        self.assertIs(lifecycle.ad_running(_meta("DISAPPROVED")), False)
        self.assertIs(lifecycle.ad_running(_meta("PAUSED")), False)
        self.assertIsNone(lifecycle.ad_running(_meta(None)))
        # Judged = running + unknown (unknown is never dropped).
        self.assertTrue(lifecycle.judged(_meta(None)))
        self.assertFalse(lifecycle.judged(_meta("WITH_ISSUES")))
        # A not-delivering object may still spend; an off one may not.
        self.assertTrue(lifecycle.may_spend(_meta("PENDING_REVIEW")))
        self.assertTrue(lifecycle.may_spend(_meta(None)))
        self.assertFalse(lifecycle.may_spend(_meta("CAMPAIGN_PAUSED")))

    def test_gone_is_the_deleted_object_only(self):
        self.assertTrue(lifecycle.gone(_meta("DELETED")))
        self.assertFalse(lifecycle.gone(_meta("ARCHIVED")))
        self.assertFalse(lifecycle.gone({"platform": "other", "native_status": "DELETED"}))


def _internal(status, *, end=TODAY + timedelta(days=3)):
    return {"origin": "internal", "status": status, "end_date": end}


ROOT = {"platform": "meta", "native_status": "ACTIVE", "end_date": None}


class StateTest(unittest.TestCase):
    def state(self, campaign, root=None):
        return lifecycle.state(campaign, root=root, today=TODAY)

    def test_internal_states(self):
        self.assertEqual(self.state(_internal("draft")), "draft")
        self.assertEqual(self.state(_internal("ready")), "draft")
        self.assertEqual(self.state(_internal("ready"), ROOT), "live")
        self.assertEqual(self.state(_internal("live")), "live")
        self.assertEqual(self.state(_internal("ended")), "ended")
        self.assertEqual(self.state(_internal("closed", end=TODAY - timedelta(days=9))), "closed")

    def test_internal_ends_after_its_end_date_not_on_it(self):
        # The end date is the last delivery day (supersedes §6.36's `end_date <= today`).
        self.assertEqual(self.state(_internal("live", end=TODAY)), "live")
        self.assertEqual(self.state(_internal("live", end=TODAY - timedelta(days=1))), "ended")
        # Never on a platform: a draft past its dates is still a draft.
        self.assertEqual(self.state(_internal("draft", end=TODAY - timedelta(days=1))), "draft")

    def test_imported_states(self):
        imported = {"origin": "imported", "status": "draft", "end_date": None}
        self.assertEqual(self.state(imported), "draft")
        self.assertEqual(self.state(imported, ROOT), "live")
        self.assertEqual(self.state(imported, {**ROOT, "native_status": "PAUSED"}), "ended")
        self.assertEqual(self.state(imported, {**ROOT, "end_date": TODAY}), "live")
        self.assertEqual(
            self.state(imported, {**ROOT, "end_date": TODAY - timedelta(days=1)}), "ended",
        )
        # An unmapped root status is unknown, not off: it never ends the campaign by itself.
        self.assertEqual(self.state(imported, {**ROOT, "native_status": "NEW_CODE"}), "live")

    def test_labels_and_can_close(self):
        self.assertEqual(
            lifecycle.view(_internal("ended"), root=ROOT, today=TODAY),
            {"state": "ended", "label": "已結束・待結案", "can_close": True},
        )
        self.assertEqual(
            lifecycle.view(_internal("live"), root=ROOT, today=TODAY),
            {"state": "live", "label": "投放中", "can_close": True},
        )
        self.assertEqual(
            lifecycle.view(_internal("draft"), root=None, today=TODAY),
            {"state": "draft", "label": "草稿", "can_close": False},
        )
        self.assertEqual(
            lifecycle.view(_internal("closed"), root=ROOT, today=TODAY),
            {"state": "closed", "label": "已結案", "can_close": False},
        )
        imported = {"origin": "imported", "status": "ended"}
        self.assertEqual(
            lifecycle.view(imported, root={**ROOT, "native_status": "ARCHIVED"}, today=TODAY),
            {"state": "ended", "label": "已結束", "can_close": False},
        )

    def test_monitored_inside_and_past_the_grace_days(self):
        grace = lifecycle.ENDED_GRACE_DAYS
        self.assertEqual(grace, 7)
        self.assertTrue(lifecycle.monitored(_internal("live"), TODAY, root=ROOT))
        last_day = TODAY - timedelta(days=grace)
        self.assertTrue(lifecycle.monitored(_internal("ended", end=last_day), TODAY, root=ROOT))
        self.assertFalse(lifecycle.monitored(
            _internal("ended", end=last_day - timedelta(days=1)), TODAY, root=ROOT,
        ))
        self.assertFalse(lifecycle.monitored(_internal("closed"), TODAY, root=ROOT))
        self.assertFalse(lifecycle.monitored(_internal("draft"), TODAY, root=None))
        imported = {"origin": "imported", "status": "live"}
        self.assertTrue(lifecycle.monitored(
            imported, TODAY, root={**ROOT, "end_date": TODAY - timedelta(days=2)},
        ))
        # Switched off with no end date: no grace to measure.
        self.assertFalse(lifecycle.monitored(
            imported, TODAY, root={**ROOT, "native_status": "PAUSED"},
        ))

    def test_unknown_selector_state_is_refused(self):
        with self.assertRaises(ValueError):
            lifecycle._wanted({"live", "paused"})


class _Db(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="生命週期品牌", actor="test", client_name=None,
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        self.conn.commit()

    def internal(self, status, *, end):
        campaign = campaigns.create_campaign(self.conn, self.org, self.brand, {
            "name": f"內部-{status}", "goal_text": "g", "objective": "awareness",
            "start_date": end - timedelta(days=6), "end_date": end,
        })["id"]
        self.conn.execute("UPDATE ads_campaign SET status=%s WHERE id=%s", (status, campaign))
        self.conn.commit()
        return campaign

    def stored(self, campaign):
        return campaigns.get_campaign(self.conn, self.org, self.brand, campaign)["status"]


class RecordTest(_Db):
    def test_record_writes_live_to_ended_once_and_never_touches_closed(self):
        yesterday = self.today - timedelta(days=1)
        live = self.internal("live", end=yesterday)
        closed = self.internal("closed", end=yesterday)
        running = self.internal("live", end=self.today)
        for _ in range(2):
            self.assertEqual(lifecycle.record(self.conn, self.org, self.brand, live), "ended")
        self.assertEqual(lifecycle.record(self.conn, self.org, self.brand, closed), "closed")
        self.assertEqual(lifecycle.record(self.conn, self.org, self.brand, running), "live")
        self.conn.commit()
        self.assertEqual(self.stored(live), "ended")
        self.assertEqual(self.stored(closed), "closed")
        self.assertEqual(self.stored(running), "live")
        self.assertIsNone(lifecycle.record(self.conn, self.org, self.brand, "adc_missing"))

    def test_an_imported_root_write_records_its_lifecycle(self):
        imported = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="既有活動",
        )["id"]
        self.assertEqual(self.stored(imported), "draft")
        root = {"platform": "meta", "source_account": "act", "native_kind": "campaign",
                "native_id": "c1", "native_status": "ACTIVE"}
        external.upsert_entity(self.conn, self.org, self.brand, imported, root)
        self.assertEqual(self.stored(imported), "live")
        # A child write leaves the campaign state to its root.
        external.upsert_entity(self.conn, self.org, self.brand, imported, {
            "platform": "meta", "source_account": "act", "native_kind": "ad", "native_id": "a1",
            "native_status": "PAUSED", "parent_native_kind": "campaign", "parent_native_id": "c1",
        })
        self.assertEqual(self.stored(imported), "live")
        external.upsert_entity(self.conn, self.org, self.brand, imported,
                               {**root, "native_status": "PAUSED"})
        self.conn.commit()
        self.assertEqual(self.stored(imported), "ended")


class SelectorTest(_Db):
    def test_campaign_ids_pick_by_state(self):
        yesterday = self.today - timedelta(days=1)
        draft = self.internal("draft", end=self.today + timedelta(days=5))
        live = self.internal("live", end=self.today + timedelta(days=5))
        past = self.internal("live", end=yesterday)  # stored live, derived ended
        closed = self.internal("closed", end=yesterday)
        ids = lambda states: lifecycle.campaign_ids(self.conn, self.org, self.brand, states)  # noqa: E731
        self.assertEqual(set(ids(lifecycle.NOT_CLOSED)), {draft, live, past})
        self.assertEqual(set(ids({"live"})), {live})
        self.assertEqual(set(ids({"live", "ended"})), {live, past})
        self.assertEqual(ids({"closed"}), [closed])
        brands_with_ended = lifecycle.brands(self.conn, {"ended"})
        self.assertIn({"org_id": self.org, "brand_id": self.brand}, brands_with_ended)


class CloseDraftTest(_Db):
    def test_a_draft_cannot_be_closed(self):
        draft = self.internal("draft", end=self.today + timedelta(days=5))
        with self.assertRaisesRegex(ValueError, "campaign_not_launched"):
            closeout.close(self.conn, self.org, self.brand, draft, actor="test")
        self.conn.rollback()
        response = TestClient(main.app).post(
            f"/api/ads/brands/{self.brand}/campaigns/{draft}/close", json={},
        )
        self.assertEqual(response.status_code, 409, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "campaign_not_launched")
        self.assertEqual(error["message"], "這個活動還沒上架，沒有可以結案的一期。")
        self.assertEqual(self.stored(draft), "draft")


if __name__ == "__main__":
    unittest.main()
