"""app/tests/test_ads_triage_ladder.py — F27-I01 falsifiers: Contract A, the handling ladder and
history `triage.classify()` attaches to every ACTIVE ad's own item. Change sets/actions/handoff
rows are inserted directly (same isolation style as `test_ads_triage_queue.py::QueueProposalTest`)
so each scenario's `approved_at`/`verified_at`/`verification_state` can be set precisely without
driving the whole approval workflow -- `replaces_entity_id` (F27-I05, not yet merged) is written
straight into `plan_json` the same way.
"""

import unittest
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.ads import channels, repository, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db

ACCOUNT_TZ = "Asia/Taipei"


class _Reader:
    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": ACCOUNT_TZ}]


class TriageLadderTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="階梯與紀錄測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign,
            result_kind="purchase", basis="own", value=1, expected_revision=0, actor="測試員",
        )
        self.conn.commit()

    # -- fixture helpers --------------------------------------------------------------------

    def make_ad(self, native_id, *, name="廣告", status="ACTIVE"):
        return external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": name, "native_status": status,
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )["id"]

    def obs(self, entity_id, day, *, spend, result_count):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": entity_id, "day": day, "metric_scope": "ad",
             "attribution_key": str(day), "currency": "TWD", "source": "meta",
             "spend": spend, "impressions": 1000, "purchases": None},
            result_kind="purchase", result_count=result_count, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    def week(self, entity_id, end_day, *, spend, result_count):
        """7 known days of observations, `end_day` inclusive -- the exact window `_cost` needs to
        read back a non-null `cost_before`/`cost_after`."""
        for offset in range(7):
            self.obs(entity_id, end_day - timedelta(days=offset), spend=spend,
                     result_count=result_count)

    def _insert_set(self, *, items, replaces_entity_id=None, approved_at=None,
                     campaign_id=None):
        campaign_id = campaign_id or self.campaign
        set_id = db.new_id("acs")
        plan = {"items": items}
        if replaces_entity_id is not None:
            plan["replaces_entity_id"] = replaces_entity_id
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, campaign_id, set_id, set_id, set_id, "測試清單",
             "2026-01", "approved", db.jsonb(plan), "test", approved_at or db.now_utc()),
        )
        self.conn.commit()
        return set_id

    def _insert_action(self, item_id, set_id, target_id, action_kind, *, verified_at=None,
                        state="confirmed", campaign_id=None):
        campaign_id = campaign_id or self.campaign
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state,verified_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (item_id, self.org, self.brand, campaign_id, "ad", target_id, action_kind, set_id,
             state, verified_at),
        )
        self.conn.commit()

    def _insert_handoff(self, item_id, set_id, entity_id, campaign_id=None):
        campaign_id = campaign_id or self.campaign
        self.conn.execute(
            "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,"
            "action_id,planned_kind,planned_id,name,expected_json,entity_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (db.new_id("ahi"), self.org, self.brand, campaign_id, set_id, item_id, "ad",
             entity_id, "新廣告", db.jsonb({}), entity_id),
        )
        self.conn.commit()

    def confirm_copy(self, entity_id, *, approved_at=None, verified_at=None,
                      state="confirmed"):
        item_id = db.new_id("adx")
        item = {"id": item_id, "kind": "copy", "target_id": entity_id, "before": {},
                "after": {"body": "新文案"}, "reason": "x"}
        set_id = self._insert_set(items=[item], approved_at=approved_at)
        self._insert_action(item_id, set_id, entity_id, "creative", verified_at=verified_at,
                             state=state)
        return set_id, item_id

    def confirm_pause(self, entity_id, *, approved_at=None, verified_at=None,
                       state="confirmed"):
        item_id = db.new_id("adx")
        item = {"id": item_id, "kind": "pause", "target_id": entity_id, "before": {},
                "after": {"status": "PAUSED"}, "reason": "x"}
        set_id = self._insert_set(items=[item], approved_at=approved_at)
        self._insert_action(item_id, set_id, entity_id, "pause", verified_at=verified_at,
                             state=state)
        return set_id, item_id

    def confirm_new_ad(self, old_entity_id, new_entity_id, *, approved_at=None,
                        verified_at=None, state="confirmed"):
        item_id = db.new_id("adx")
        item = {"id": item_id, "kind": "new_ad", "target_id": "placement_1", "before": {},
                "after": {}, "reason": "x"}
        set_id = self._insert_set(
            items=[item], replaces_entity_id=old_entity_id, approved_at=approved_at,
        )
        self._insert_action(item_id, set_id, new_entity_id, "publish", verified_at=verified_at,
                             state=state)
        self._insert_handoff(item_id, set_id, new_entity_id)
        return set_id, item_id

    def item_for(self, entity_id):
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        for item in result["items"]:
            if item["entity_id"] == entity_id:
                return item, result
        raise AssertionError(f"{entity_id} not among active items")

    # -- step 0/1/2 ---------------------------------------------------------------------------

    def test_step_zero_when_no_confirmed_change_exists(self):
        ad = self.make_ad("ad0")
        item, _ = self.item_for(ad)
        self.assertEqual(item["ladder"], {
            "step": 0, "copy_changes": 0, "image_changes": 0, "lineage_from": None,
        })
        self.assertEqual(item["history"], [])

    def test_step_one_after_a_confirmed_copy_change(self):
        ad = self.make_ad("ad1")
        self.confirm_copy(ad, approved_at=db.now_utc() - timedelta(days=3))
        item, _ = self.item_for(ad)
        self.assertEqual(item["ladder"]["step"], 1)
        self.assertEqual(item["ladder"]["copy_changes"], 1)
        self.assertEqual(item["ladder"]["image_changes"], 0)
        self.assertIsNone(item["ladder"]["lineage_from"])

    def test_pending_copy_change_never_counts(self):
        ad = self.make_ad("ad1b")
        self.confirm_copy(ad, approved_at=db.now_utc() - timedelta(days=3), state="pending")
        item, _ = self.item_for(ad)
        self.assertEqual(item["ladder"], {
            "step": 0, "copy_changes": 0, "image_changes": 0, "lineage_from": None,
        })

    def test_step_two_after_a_confirmed_replacement(self):
        old = self.make_ad("ad2_old", status="PAUSED")
        new = self.make_ad("ad2_new")
        self.confirm_new_ad(old, new, approved_at=db.now_utc() - timedelta(days=5))
        item, _ = self.item_for(new)
        self.assertEqual(item["ladder"]["step"], 2)
        self.assertEqual(item["ladder"]["image_changes"], 1)
        self.assertEqual(item["ladder"]["lineage_from"], old)

    def test_pending_new_ad_never_links_lineage(self):
        old = self.make_ad("ad2b_old", status="PAUSED")
        new = self.make_ad("ad2b_new")
        self.confirm_new_ad(
            old, new, approved_at=db.now_utc() - timedelta(days=5), state="pending",
        )
        item, _ = self.item_for(new)
        self.assertEqual(item["ladder"], {
            "step": 0, "copy_changes": 0, "image_changes": 0, "lineage_from": None,
        })

    # -- lineage carried to the replacement ad -------------------------------------------------

    def test_copy_changes_carry_through_lineage_to_the_replacement_ad(self):
        old = self.make_ad("ad3_old", status="PAUSED")
        new = self.make_ad("ad3_new")
        self.confirm_copy(old, approved_at=db.now_utc() - timedelta(days=10))
        self.confirm_new_ad(old, new, approved_at=db.now_utc() - timedelta(days=5))
        item, _ = self.item_for(new)
        self.assertEqual(item["ladder"]["step"], 2)  # image_changes wins over copy_changes
        self.assertEqual(item["ladder"]["copy_changes"], 1)  # inherited from `old`
        self.assertEqual(item["ladder"]["image_changes"], 1)
        self.assertEqual(item["ladder"]["lineage_from"], old)

    def test_lineage_walks_two_replacements_back(self):
        gen1 = self.make_ad("ad4_gen1", status="PAUSED")
        gen2 = self.make_ad("ad4_gen2", status="PAUSED")
        gen3 = self.make_ad("ad4_gen3")
        self.confirm_new_ad(gen1, gen2, approved_at=db.now_utc() - timedelta(days=10))
        self.confirm_new_ad(gen2, gen3, approved_at=db.now_utc() - timedelta(days=3))
        item, _ = self.item_for(gen3)
        self.assertEqual(item["ladder"]["image_changes"], 2)
        self.assertEqual(item["ladder"]["lineage_from"], gen2)  # the ad it DIRECTLY replaced

    # -- closed ads unaffected ------------------------------------------------------------------

    def test_closed_lineage_predecessor_carries_no_ladder_key_of_its_own(self):
        old = self.make_ad("ad5_old", status="PAUSED")
        new = self.make_ad("ad5_new")
        self.confirm_new_ad(old, new, approved_at=db.now_utc() - timedelta(days=5))
        _, result = self.item_for(new)
        closed_ids = {row["entity_id"]: row for row in result["closed"]["items"]}
        self.assertIn(old, closed_ids)
        self.assertNotIn("ladder", closed_ids[old])
        self.assertNotIn("history", closed_ids[old])

    # -- history ordering and the 7-day null rule ----------------------------------------------

    def test_history_lists_newest_first(self):
        ad = self.make_ad("ad6")
        older = db.now_utc() - timedelta(days=20)
        newer = db.now_utc() - timedelta(days=3)
        _, older_item_id = self.confirm_copy(ad, approved_at=older)
        _, newer_item_id = self.confirm_pause(ad, approved_at=newer)
        item, _ = self.item_for(ad)
        kinds_in_order = [(entry["kind"], entry["approved_at"]) for entry in item["history"]]
        self.assertEqual([k for k, _ in kinds_in_order], ["pause", "copy"])
        self.assertGreater(kinds_in_order[0][1], kinds_in_order[1][1])

    def test_cost_before_is_null_with_fewer_than_seven_known_days(self):
        ad = self.make_ad("ad7")
        approved_at = db.now_utc() - timedelta(days=3)
        # Only 5 of the 7 days before `approved_at` have a row.
        for offset in range(2, 7):
            self.obs(ad, approved_at.date() - timedelta(days=offset), spend=10, result_count=1)
        self.confirm_copy(ad, approved_at=approved_at)
        item, _ = self.item_for(ad)
        self.assertEqual(len(item["history"]), 1)
        self.assertIsNone(item["history"][0]["cost_before"])

    def test_cost_before_and_after_are_real_when_seven_days_are_known(self):
        ad = self.make_ad("ad8")
        approved_at = db.now_utc() - timedelta(days=20)
        verified_at = db.now_utc() - timedelta(days=10)
        self.week(ad, approved_at.date() - timedelta(days=1), spend=50, result_count=5)
        self.week(ad, verified_at.date() + timedelta(days=7), spend=20, result_count=2)
        self.confirm_copy(ad, approved_at=approved_at, verified_at=verified_at)
        item, _ = self.item_for(ad)
        entry = item["history"][0]
        self.assertEqual(entry["kind"], "copy")
        self.assertAlmostEqual(entry["cost_before"], 10.0)  # 7*50 spend / 7*5 results
        self.assertAlmostEqual(entry["cost_after"], 10.0)  # 7*20 spend / 7*2 results

    def test_new_ad_history_entry_prices_the_replaced_ad_before_and_the_new_ad_after(self):
        old = self.make_ad("ad9_old", status="PAUSED")
        new = self.make_ad("ad9_new")
        approved_at = db.now_utc() - timedelta(days=20)
        verified_at = db.now_utc() - timedelta(days=10)
        self.week(old, approved_at.date() - timedelta(days=1), spend=40, result_count=4)
        self.week(new, verified_at.date() + timedelta(days=7), spend=30, result_count=3)
        self.confirm_new_ad(old, new, approved_at=approved_at, verified_at=verified_at)
        item, _ = self.item_for(new)
        entry = item["history"][0]
        self.assertEqual(entry["kind"], "new_ad")
        self.assertAlmostEqual(entry["cost_before"], 10.0)  # priced on the OLD (replaced) ad
        self.assertAlmostEqual(entry["cost_after"], 10.0)  # priced on the NEW ad
