"""app/tests/test_ads_triage_capacity.py — F27-I06 falsifiers: Contract F, per-campaign capacity
and the cleanup candidate ads; F28-I02: the cut is chosen by grade against the one cap (白花
always, then 太貴 before 偏貴, highest cost first; 划算 and ungraded ads never).

`CapacityViewTest` proves `capacity_view()` in isolation (pure function, no DB) -- items are built
by hand (same isolation style as `test_ads_triage_scale.py::_CandidateFixture`). `CleanupCandidates
Test` proves `cleanup_candidates()` against real `ads_external_entity`/`ads_external_daily`/
`ads_change_set`/`ads_action`/`ads_handoff_item` rows (open-replacement-lineage exclusion needs the
real lineage link, same reason `test_ads_triage_ladder.py` inserts those directly rather than
driving the whole approval workflow).
"""

import unittest
from datetime import date, timedelta

from app.ads import external_repository as external
from app.ads import triage_capacity
from app.brand_intelligence import repository as brands
from app.core import db

WINDOW_END = date(2026, 1, 7)  # cutoff every CleanupCandidatesTest scenario judges against


class CapacityViewTest(unittest.TestCase):
    """Pure function -- `items` are hand-built `{"entity_id": ...}` dicts (Contract F only ever
    reads `entity_id`/`class`/`name`/`thumbnail_url` off each), `owner_by_entity` a hand-built
    `id -> {"id", "budget_amount", "currency"}` map (same shape `triage_scale.owner_lookup`
    returns)."""

    @staticmethod
    def _items(*entity_ids):
        return [{"entity_id": eid} for eid in entity_ids]

    @staticmethod
    def _owner(owner_id, *, amount, currency="TWD"):
        return {"id": owner_id, "budget_amount": amount, "currency": currency}

    def test_daily_budget_and_can_support_computed(self):
        owner = self._owner("own1", amount=1000)
        capacity = triage_capacity.capacity_view(
            self._items("ad1", "ad2"), 100, {"ad1": owner, "ad2": owner},
        )
        self.assertEqual(capacity, {
            "daily_budget": 1000.0, "currency": "TWD", "target": 100,
            "can_support": 5,  # floor(1000 / (100*2))
            "active_ads": 2,
        })

    def test_no_active_ads_daily_budget_is_null_not_zero(self):
        capacity = triage_capacity.capacity_view([], 100, {})
        self.assertEqual(capacity, {
            "daily_budget": None, "currency": None, "target": 100,
            "can_support": None, "active_ads": 0,
        })

    def test_any_active_ad_without_an_owner_makes_daily_budget_null(self):
        owner = self._owner("own1", amount=1000)
        capacity = triage_capacity.capacity_view(
            self._items("ad1", "ad2"), 100, {"ad1": owner},  # ad2 has no owner
        )
        self.assertIsNone(capacity["daily_budget"])
        self.assertIsNone(capacity["currency"])
        self.assertIsNone(capacity["can_support"])
        self.assertEqual(capacity["active_ads"], 2)

    def test_mixed_currency_owners_make_daily_budget_null(self):
        capacity = triage_capacity.capacity_view(
            self._items("ad1", "ad2"), 100,
            {
                "ad1": self._owner("own1", amount=500, currency="TWD"),
                "ad2": self._owner("own2", amount=500, currency="USD"),
            },
        )
        self.assertIsNone(capacity["daily_budget"])
        self.assertIsNone(capacity["currency"])

    def test_same_owner_shared_by_two_ads_counted_once(self):
        owner = self._owner("own1", amount=600)
        capacity = triage_capacity.capacity_view(
            self._items("ad1", "ad2"), 100, {"ad1": owner, "ad2": owner},
        )
        self.assertEqual(capacity["daily_budget"], 600.0)  # not 1200 -- one owner, not per-ad sum

    def test_target_none_makes_can_support_null(self):
        owner = self._owner("own1", amount=1000)
        capacity = triage_capacity.capacity_view(self._items("ad1"), None, {"ad1": owner})
        self.assertEqual(capacity["daily_budget"], 1000.0)
        self.assertIsNone(capacity["can_support"])

    def test_target_zero_makes_can_support_null(self):
        owner = self._owner("own1", amount=1000)
        capacity = triage_capacity.capacity_view(self._items("ad1"), 0, {"ad1": owner})
        self.assertIsNone(capacity["can_support"])

    def test_can_support_floors_not_rounds(self):
        owner = self._owner("own1", amount=999)
        capacity = triage_capacity.capacity_view(self._items("ad1"), 100, {"ad1": owner})
        self.assertEqual(capacity["can_support"], 4)  # floor(999 / 200) == 4.995 -> 4


class CleanupCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="清理提案測試", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "name": "活動一"},
        )
        self.conn.commit()

    # -- fixture helpers ------------------------------------------------------------------------

    def make_ad(self, native_id, *, name="廣告", thumbnail_url=None):
        creative = (
            {"fields": {"thumbnail_url": thumbnail_url}} if thumbnail_url is not None else None
        )
        payload = {
            "platform": "meta", "source_account": "act_1", "native_kind": "ad",
            "native_id": native_id, "name": name, "native_status": "ACTIVE",
            "parent_native_kind": "campaign", "parent_native_id": "c1",
        }
        if creative is not None:
            payload["creative"] = creative
        return external.upsert_entity(self.conn, self.org, self.brand, self.campaign, payload)["id"]

    def obs(self, entity_id, day, *, spend):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": entity_id, "day": day, "metric_scope": "ad",
             "attribution_key": str(day), "currency": "TWD", "source": "meta",
             "spend": spend, "impressions": 100, "purchases": None},
            result_kind="purchase", result_count=1, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    def full_week(self, entity_id, *, spend, end=WINDOW_END):
        for offset in range(7):
            self.obs(entity_id, end - timedelta(days=offset), spend=spend)

    @staticmethod
    def item(entity_id, grade, *, cost=None, spend=None, result_count=None, name="廣告",
             thumbnail_url=None):
        """The fields `cleanup_candidates` reads off one `classify()` item (F28-I02): `grade`
        plus the graded window's own `current` numbers."""
        return {
            "entity_id": entity_id, "name": name, "thumbnail_url": thumbnail_url,
            "grade": grade,
            "current": {"cost_per_result": cost, "spend": spend, "result_count": result_count},
        }

    def rows_by_entity(self, start, end):
        rows = self.conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND metric_scope='ad' AND day BETWEEN %s AND %s",
            (self.org, self.brand, self.campaign, start, end),
        ).fetchall()
        by_entity = {}
        for row in rows:
            by_entity.setdefault(row["entity_id"], []).append(dict(row))
        return by_entity

    def candidates(self, items, *, can_support, active_ads=None, window_end=WINDOW_END,
                   scale_owner_id=None):
        capacity = {
            "can_support": can_support,
            "active_ads": active_ads if active_ads is not None else len(items),
        }
        start = window_end - timedelta(days=6)
        return triage_capacity.cleanup_candidates(
            self.conn, self.org, self.brand, self.campaign, "活動一", items,
            self.rows_by_entity(start, window_end), window_end, capacity,
            scale_owner_id=scale_owner_id,
        )

    @staticmethod
    def ids(entries):
        return [entry["entity_id"] for entry in entries]

    # -- lineage fixture helpers (same shape test_ads_triage_ladder.py uses) ---------------------

    def _insert_new_ad_set(self, *, old_entity_id, new_item_id, status="approved"):
        set_id = db.new_id("acs")
        plan = {
            "items": [{"id": new_item_id, "kind": "new_ad", "target_id": "placement_1",
                      "before": {}, "after": {}, "reason": "x"}],
            "replaces_entity_id": old_entity_id,
        }
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", status, db.jsonb(plan), "test", db.now_utc()),
        )
        self.conn.commit()
        return set_id

    def _insert_action(self, item_id, set_id, target_id, *, state):
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (item_id, self.org, self.brand, self.campaign, "ad", target_id, "publish", set_id,
             state),
        )
        self.conn.commit()

    def _insert_handoff(self, item_id, set_id, entity_id):
        self.conn.execute(
            "INSERT INTO ads_handoff_item(id,org_id,brand_id,campaign_id,change_set_id,"
            "action_id,planned_kind,planned_id,name,expected_json,entity_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (db.new_id("ahi"), self.org, self.brand, self.campaign, set_id, item_id, "ad",
             entity_id, "新廣告", db.jsonb({}), entity_id),
        )
        self.conn.commit()

    def replace_ad(self, old_entity_id, new_entity_id, *, state="confirmed"):
        """Same 3-row shape `test_ads_triage_ladder.py::confirm_new_ad` inserts -- one
        `new_ad` change-set item (with `replaces_entity_id`), its `ads_action`, and the
        `ads_handoff_item` binding the created entity back to it."""
        item_id = db.new_id("adx")
        set_id = self._insert_new_ad_set(old_entity_id=old_entity_id, new_item_id=item_id)
        self._insert_action(item_id, set_id, new_entity_id, state=state)
        self._insert_handoff(item_id, set_id, new_entity_id)
        return set_id, item_id

    def insert_pause_item(self, entity_id, *, status="draft"):
        item_id = db.new_id("adx")
        set_id = db.new_id("acs")
        plan = {"items": [{"id": item_id, "kind": "pause", "target_id": entity_id, "before": {},
                           "after": {"status": "PAUSED"}, "reason": "x"}]}
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", status, db.jsonb(plan), "test"),
        )
        self.conn.commit()
        return set_id, item_id

    # -- no row -------------------------------------------------------------------------------

    def test_no_row_when_over_capacity_but_only_on_target_ads_remain(self):
        # 划算 never closes: over capacity with nothing closable raises no cleanup row -- the
        # owner's scale_budget row is the proposal instead.
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        items = [self.item(ad, "on_target", cost=50, spend=350) for ad in (a, b, c)]
        self.assertIsNone(self.candidates(items, can_support=1))

    def test_no_row_when_within_capacity_and_nothing_is_wasted(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [self.item(a, "over", cost=700, spend=4900), self.item(b, "watch", cost=500)]
        self.assertIsNone(self.candidates(items, can_support=2))

    def test_no_row_for_ungraded_ads_even_far_over_capacity(self):
        # 還太新／資料不足（unknown cost）／未判斷 never close, whatever the capacity says.
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        items = [
            self.item(a, "insufficient", cost=None, spend=100, result_count=0),
            self.item(b, "insufficient", cost=None, spend=None),
            self.item(c, "no_target", cost=80, spend=560),
        ]
        self.assertIsNone(self.candidates(items, can_support=1))

    # -- 白花 always closes ---------------------------------------------------------------------

    def test_wasted_closes_even_when_capacity_is_unknown(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        self.full_week(a, spend=220)
        items = [
            self.item(a, "wasted", cost=None, spend=1540, result_count=0, name="白花廣告"),
            self.item(b, "over", cost=700, spend=4900),
        ]
        result = self.candidates(items, can_support=None)  # null daily budget / no owner
        self.assertEqual(self.ids(result["ads"]), [a])
        self.assertIsNone(result["can_support"])
        self.assertEqual(result["short"], 0)
        self.assertEqual(self.ids(result["keep"]), [b])

    def test_wasted_closes_even_within_capacity(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [
            self.item(a, "wasted", spend=1540, result_count=0),
            self.item(b, "on_target", cost=50, spend=1400),
        ]
        result = self.candidates(items, can_support=5)
        self.assertEqual(self.ids(result["ads"]), [a])
        self.assertEqual(result["short"], 0)

    def test_capacity_below_one_ad_closes_only_wasted(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [
            self.item(a, "over", cost=700, spend=4900),
            self.item(b, "wasted", spend=1540, result_count=0),
        ]
        result = self.candidates(items, can_support=0)
        self.assertEqual(self.ids(result["ads"]), [b])
        self.assertEqual(result["short"], 0)

    def test_several_wasted_close_most_spend_first(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [
            self.item(a, "wasted", spend=1400, result_count=0),
            self.item(b, "wasted", spend=2000, result_count=0),
        ]
        self.assertEqual(self.ids(self.candidates(items, can_support=5)["ads"]), [b, a])

    # -- capacity order: 太貴 before 偏貴, highest cost first, 划算 never -------------------------

    def test_over_before_watch_highest_cost_first(self):
        ads = [self.make_ad(f"a{i}") for i in range(5)]
        items = [
            self.item(ads[0], "on_target", cost=50, spend=1400),
            self.item(ads[1], "watch", cost=500, spend=3500),
            self.item(ads[2], "over", cost=600, spend=4200),
            self.item(ads[3], "over", cost=700, spend=4900),
            self.item(ads[4], "on_target", cost=60, spend=1200),
        ]
        result = self.candidates(items, can_support=2)  # excess 3
        self.assertEqual(self.ids(result["ads"]), [ads[3], ads[2], ads[1]])
        self.assertEqual(result["short"], 0)
        result = self.candidates(items, can_support=3)  # excess 2
        self.assertEqual(self.ids(result["ads"]), [ads[3], ads[2]])

    def test_wasted_counts_toward_the_excess(self):
        ads = [self.make_ad(f"a{i}") for i in range(5)]
        items = [
            self.item(ads[0], "wasted", spend=1540, result_count=0),
            self.item(ads[1], "over", cost=617, spend=4319),
            self.item(ads[2], "watch", cost=520, spend=3640),
            self.item(ads[3], "on_target", cost=50, spend=1400),
            self.item(ads[4], "on_target", cost=48, spend=1344),
        ]
        result = self.candidates(items, can_support=3)  # excess 2: the 白花 + one more
        self.assertEqual(self.ids(result["ads"]), [ads[0], ads[1]])
        # keep: 偏貴 first (closest to closing), then 划算 by cost, highest first.
        self.assertEqual(self.ids(result["keep"]), [ads[2], ads[3], ads[4]])

    def test_short_counts_what_stays_over_capacity_and_echoes_the_scale_owner(self):
        ads = [self.make_ad(f"a{i}") for i in range(4)]
        items = [
            self.item(ads[0], "over", cost=700, spend=4900),
            self.item(ads[1], "on_target", cost=50, spend=1400),
            self.item(ads[2], "on_target", cost=60, spend=1200),
            self.item(ads[3], "insufficient", spend=100, result_count=0),  # 還太新
        ]
        result = self.candidates(items, can_support=1, scale_owner_id="own_1")  # excess 3
        self.assertEqual(self.ids(result["ads"]), [ads[0]])
        self.assertEqual(result["short"], 2)
        self.assertEqual(result["scale_owner_id"], "own_1")

    def test_scale_owner_id_null_when_nothing_stays_over_capacity(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [self.item(a, "over", cost=700, spend=4900),
                 self.item(b, "on_target", cost=50, spend=1400)]
        result = self.candidates(items, can_support=1, scale_owner_id="own_1")
        self.assertEqual(result["short"], 0)
        self.assertIsNone(result["scale_owner_id"])

    def test_equal_cost_ties_close_the_higher_spend_then_entity_id(self):
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        items = [
            self.item(a, "over", cost=600, spend=3000),
            self.item(b, "over", cost=600, spend=4200),
            self.item(c, "on_target", cost=50, spend=1400),
        ]
        self.assertEqual(self.ids(self.candidates(items, can_support=2)["ads"]), [b])
        items[0]["current"]["spend"] = 4200  # same cost, same spend -> entity id order
        self.assertEqual(
            self.ids(self.candidates(items, can_support=2)["ads"]), [min(a, b)],
        )

    # -- payload --------------------------------------------------------------------------------

    def test_entry_shape_and_daily_saving(self):
        a = self.make_ad("a1", name="廣告甲", thumbnail_url="https://x/1.jpg")
        b = self.make_ad("a2", name="廣告乙")
        c = self.make_ad("a3")
        self.full_week(a, spend=220)
        self.full_week(b, spend=617)
        self.full_week(c, spend=200)
        items = [
            self.item(a, "wasted", spend=1540, result_count=0, name="廣告甲",
                      thumbnail_url="https://x/1.jpg"),
            self.item(b, "over", cost=617, spend=4319, result_count=7, name="廣告乙"),
            self.item(c, "on_target", cost=50, spend=1400, result_count=28),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(result["ads"][0], {
            "entity_id": a, "name": "廣告甲", "thumbnail_url": "https://x/1.jpg",
            "spend_7d": 1540.0, "grade": "wasted", "cost_per_result": None, "spend": 1540,
            "result_count": 0, "daily_spend": 220.0, "rejected_before": None,
        })
        self.assertEqual(result["ads"][1]["grade"], "over")
        self.assertEqual(result["ads"][1]["cost_per_result"], 617)
        self.assertEqual(result["keep"][0]["entity_id"], c)
        self.assertEqual(result["keep"][0]["daily_spend"], 200.0)
        self.assertEqual(result["daily_saving"], 220.0 + 617.0)
        self.assertEqual(result["can_support"], 1)
        self.assertEqual(result["active_ads"], 3)
        self.assertEqual(result["campaign_id"], self.campaign)
        self.assertEqual(result["campaign_name"], "活動一")

    def test_incomplete_seven_day_spend_still_closes_but_saving_is_unknown(self):
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        self.full_week(a, spend=220)
        self.obs(b, WINDOW_END, spend=617)  # 1 of 7 days -- the 7-day average is unknown
        items = [
            self.item(a, "wasted", spend=1540, result_count=0),
            self.item(b, "over", cost=617, spend=4319),
            self.item(c, "on_target", cost=50, spend=1400),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [a, b])
        self.assertIsNone(result["ads"][1]["spend_7d"])
        self.assertIsNone(result["ads"][1]["daily_spend"])
        self.assertIsNone(result["daily_saving"])

    # -- open replacement lineage (correction 4) ----------------------------------------------

    def test_new_ad_not_yet_verified_never_closes(self):
        old = self.make_ad("old1")
        new = self.make_ad("new1")
        self.replace_ad(old, new, state="pending")  # not confirmed yet
        other = self.make_ad("other1")
        items = [
            self.item(new, "wasted", spend=1540, result_count=0),
            self.item(other, "over", cost=600, spend=4200),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [other])
        self.assertEqual(self.ids(result["keep"]), [new])

    def test_old_ad_awaiting_followup_pause_never_closes(self):
        old = self.make_ad("old2")
        new = self.make_ad("new2")
        self.replace_ad(old, new, state="confirmed")  # replacement is live
        other = self.make_ad("other2")
        items = [
            self.item(old, "over", cost=900, spend=6300),  # the most expensive, but pending
            self.item(other, "over", cost=600, spend=4200),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [other])

    def test_old_ad_eligible_again_once_its_own_followup_pause_exists(self):
        old = self.make_ad("old3")
        new = self.make_ad("new3")
        self.replace_ad(old, new, state="confirmed")
        self.insert_pause_item(old)  # the follow-up has happened (any non-superseded status)
        other = self.make_ad("other3")
        items = [
            self.item(old, "over", cost=900, spend=6300),
            self.item(other, "over", cost=600, spend=4200),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [old])

    def test_new_ad_lineage_without_replaces_entity_id_is_not_open_lineage(self):
        """A fresh, non-replacement `new_ad` item (no `replaces_entity_id`) is out of scope for
        `_open_lineage_entity_ids` (`triage_ladder._new_ad_by_created_entity` applies the same
        `replaces_entity_id`-required eligibility) -- never excluded on lineage grounds alone."""
        fresh = self.make_ad("fresh1")
        other = self.make_ad("other4")
        item_id = db.new_id("adx")
        set_id = db.new_id("acs")
        plan = {"items": [{"id": item_id, "kind": "new_ad", "target_id": "placement_1",
                           "before": {}, "after": {}, "reason": "x"}]}
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "測試清單",
             "2026-01", "approved", db.jsonb(plan), "test", db.now_utc()),
        )
        self.conn.commit()
        self._insert_action(item_id, set_id, fresh, state="pending")
        self._insert_handoff(item_id, set_id, fresh)
        items = [
            self.item(fresh, "over", cost=900, spend=6300),
            self.item(other, "over", cost=600, spend=4200),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [fresh])


if __name__ == "__main__":
    unittest.main()
