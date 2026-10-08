"""app/tests/test_ads_triage_capacity.py — F27-I06 falsifiers: Contract F, per-campaign capacity
and the cleanup candidate ads; F48-I02: the cut follows `learning_rank.rank` (sold ads by cost per
sale, 沒賣出 after), closed from the bottom -- every 沒賣出, then 換掉 rows most expensive first
while over capacity; 留下 (keep／keep_relative) and ungraded ads never close.

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
GRADE_LABELS = {"on_target": "划算", "watch": "偏貴", "over": "太貴", "wasted": "沒賣出"}


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

    def test_can_support_is_the_one_pure_formula(self):
        self.assertEqual(triage_capacity.can_support(1000, 100), 5)
        self.assertEqual(triage_capacity.can_support(999, 100), 4)
        self.assertIsNone(triage_capacity.can_support(None, 100))
        self.assertIsNone(triage_capacity.can_support(1000, None))
        self.assertIsNone(triage_capacity.can_support(1000, 0))


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

    CAP = 450  # the campaign's one cap: 划算 <= 450 < 偏貴 <= 540 < 太貴

    def item(self, entity_id, grade, *, cost=None, spend=None, result_count=None, name="廣告",
             thumbnail_url=None):
        """The fields `cleanup_candidates` reads off one `classify()` item (F28-I02): `grade`
        plus the graded window's own `current` numbers and the cap (F48-I02: ranked by
        `learning_rank.rank` over spend／results). A sold item given only `cost` (and maybe
        `spend`) gets the result count that makes `spend ÷ results == cost`."""
        if grade in GRADE_LABELS and grade != "wasted" and cost is not None:
            if result_count is None:
                result_count = round(spend / cost) if spend else 1
            if spend is None:
                spend = cost * result_count
        return {
            "entity_id": entity_id, "name": name, "thumbnail_url": thumbnail_url,
            "grade": grade, "grade_label": GRADE_LABELS.get(grade, "剛開始、數字還不夠"),
            "current": {"cost_per_result": cost, "spend": spend, "result_count": result_count,
                        "currency": "TWD"},
            "target": {"value": self.CAP},
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
                   scale_owner_id=None, memory=None):
        capacity = {
            "can_support": can_support,
            "active_ads": active_ads if active_ads is not None else len(items),
        }
        start = window_end - timedelta(days=6)
        return triage_capacity.cleanup_candidates(
            self.conn, self.org, self.brand, self.campaign, "活動一", items,
            self.rows_by_entity(start, window_end), window_end, capacity,
            scale_owner_id=scale_owner_id, memory=memory,
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
        # 剛開始／資料不足（unknown cost）／未判斷 never close, whatever the capacity says.
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        items = [
            self.item(a, "insufficient", cost=None, spend=100, result_count=0),
            self.item(b, "insufficient", cost=None, spend=None),
            self.item(c, "no_target", cost=80, spend=560),
        ]
        self.assertIsNone(self.candidates(items, can_support=1))

    # -- 沒賣出 always closes -------------------------------------------------------------------

    def test_wasted_closes_even_when_capacity_is_unknown(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        self.full_week(a, spend=220)
        items = [
            self.item(a, "wasted", cost=None, spend=1540, result_count=0, name="沒賣出廣告"),
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

    def test_several_wasted_all_close_served_in_rank_order(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        items = [
            self.item(b, "wasted", spend=2000, result_count=0),
            self.item(a, "wasted", spend=1400, result_count=0),
        ]
        result = self.candidates(items, can_support=5)
        # learning_rank places 沒賣出 cheapest spend first; the list is served in that order.
        self.assertEqual(self.ids(result["ads"]), [a, b])
        self.assertEqual([(ad["rank"], ad["of"]) for ad in result["ads"]], [(1, 2), (2, 2)])

    # -- capacity order: learning_rank's, closed from the bottom; 留下 never ----------------------

    def test_replace_rows_close_from_the_bottom_and_are_served_in_rank_order(self):
        ads = [self.make_ad(f"a{i}") for i in range(5)]
        items = [
            self.item(ads[0], "on_target", cost=50, spend=1400),
            self.item(ads[1], "watch", cost=500, spend=3500),
            self.item(ads[2], "over", cost=600, spend=4200),
            self.item(ads[3], "over", cost=700, spend=4900),
            self.item(ads[4], "on_target", cost=60, spend=1200),
        ]
        result = self.candidates(items, can_support=2)  # excess 3
        self.assertEqual(self.ids(result["ads"]), [ads[1], ads[2], ads[3]])
        self.assertEqual([ad["rank"] for ad in result["ads"]], [3, 4, 5])
        self.assertEqual(result["short"], 0)
        result = self.candidates(items, can_support=3)  # excess 2: the two most expensive
        self.assertEqual(self.ids(result["ads"]), [ads[2], ads[3]])
        self.assertEqual(self.ids(result["keep"]), [ads[0], ads[4], ads[1]])

    def test_h1_two_sold_ads_order_by_cost_per_sale_not_by_grade_label(self):
        # Drill-11 H1: 634 a sale over 4 sales stays, 1,009 a sale over 1 sale closes -- whatever
        # label each one carries (here the dearer ad is even labelled the milder 偏貴).
        cheap, dear, best = self.make_ad("h1"), self.make_ad("h2"), self.make_ad("h3")
        items = [
            self.item(dear, "watch", cost=1009, spend=1009, result_count=1),
            self.item(cheap, "over", cost=634, spend=2536, result_count=4),
            self.item(best, "on_target", cost=300, spend=3000, result_count=10),
        ]
        result = self.candidates(items, can_support=2)  # excess 1
        self.assertEqual(self.ids(result["ads"]), [dear])
        self.assertEqual(self.ids(result["keep"]), [best, cheap])
        closing = result["ads"][0]
        self.assertEqual(
            {k: closing[k] for k in ("rank", "of", "sales", "few", "verdict", "verdict_label",
                                     "flags", "reason_text")},
            {"rank": 3, "of": 3, "sales": 1, "few": True, "verdict": "replace",
             "verdict_label": "換掉", "flags": ["樣本少"],
             "reason_text": "第 3／3 名，每筆 1,009 對上限 450（偏貴）"},
        )
        self.assertEqual(result["keep"][1]["sales"], 4)
        self.assertTrue(result["keep"][1]["few"])

    def test_unsold_closes_before_any_sold_ad(self):
        ads = [self.make_ad(f"a{i}") for i in range(3)]
        items = [
            self.item(ads[0], "over", cost=900, spend=9000),
            self.item(ads[1], "wasted", spend=1400, result_count=0),
            self.item(ads[2], "on_target", cost=50, spend=1400),
        ]
        result = self.candidates(items, can_support=2)  # excess 1: the 沒賣出 fills it
        self.assertEqual(self.ids(result["ads"]), [ads[1]])
        self.assertEqual(result["ads"][0]["reason_text"], "花了 1,400，一筆都沒賣出")

    def test_keep_relative_never_closes(self):
        # Nothing is under the cap: the best and those within 30 % of it stay (留下, relative).
        ads = [self.make_ad(f"a{i}") for i in range(3)]
        items = [
            self.item(ads[0], "over", cost=600, spend=6000),
            self.item(ads[1], "over", cost=700, spend=7000),
            self.item(ads[2], "over", cost=900, spend=9000),
        ]
        result = self.candidates(items, can_support=1)  # excess 2, only one replace row
        self.assertEqual(self.ids(result["ads"]), [ads[2]])
        self.assertEqual(result["short"], 1)
        self.assertEqual([e["verdict"] for e in result["keep"]], ["keep_relative"] * 2)
        self.assertEqual(result["keep"][0]["flags"], ["相對最好，仍高於上限"])

    def test_wasted_counts_toward_the_excess(self):
        ads = [self.make_ad(f"a{i}") for i in range(5)]
        items = [
            self.item(ads[0], "wasted", spend=1540, result_count=0),
            self.item(ads[1], "over", cost=617, spend=4319),
            self.item(ads[2], "watch", cost=520, spend=3640),
            self.item(ads[3], "on_target", cost=50, spend=1400),
            self.item(ads[4], "on_target", cost=48, spend=1344),
        ]
        result = self.candidates(items, can_support=3)  # excess 2: the 沒賣出 + one more
        self.assertEqual(self.ids(result["ads"]), [ads[1], ads[0]])  # rank order
        # keep: the kept rows in rank order (cheapest cost per sale first).
        self.assertEqual(self.ids(result["keep"]), [ads[4], ads[3], ads[2]])

    def test_short_counts_what_stays_over_capacity_and_echoes_the_scale_owner(self):
        ads = [self.make_ad(f"a{i}") for i in range(4)]
        items = [
            self.item(ads[0], "over", cost=700, spend=4900),
            self.item(ads[1], "on_target", cost=50, spend=1400),
            self.item(ads[2], "on_target", cost=60, spend=1200),
            self.item(ads[3], "insufficient", spend=100, result_count=0),  # 剛開始
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

    def test_equal_cost_ties_close_the_fewer_sales_then_the_later_name(self):
        # learning_rank's tie-break: equal cost per sale -> more sales ranks higher, then name.
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        items = [
            self.item(a, "over", cost=600, spend=3000, name="A 廣告"),  # 5 sales
            self.item(b, "over", cost=600, spend=4200, name="B 廣告"),  # 7 sales
            self.item(c, "on_target", cost=50, spend=1400),
        ]
        self.assertEqual(self.ids(self.candidates(items, can_support=2)["ads"]), [a])
        items[0] = self.item(a, "over", cost=600, spend=4200, name="A 廣告")  # 7 sales each
        self.assertEqual(self.ids(self.candidates(items, can_support=2)["ads"]), [b])

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
        # Rank order: 乙 (2nd of 3, sold) before 甲 (3rd, 沒賣出).
        self.assertEqual(result["ads"][1], {
            "entity_id": a, "name": "廣告甲", "thumbnail_url": "https://x/1.jpg",
            "spend_7d": 1540.0, "grade": "wasted", "cost_per_result": None, "spend": 1540,
            "result_count": 0, "daily_spend": 220.0, "rejected_before": None,
            "currency": "TWD", "cap_comparison": None,
            "rank": 3, "of": 3, "sales": 0, "few": False, "verdict": "replace",
            "verdict_label": "換掉", "flags": [], "reason_text": "花了 1,540，一筆都沒賣出",
        })
        self.assertEqual(result["ads"][0]["grade"], "over")
        self.assertEqual(result["ads"][0]["cost_per_result"], 617)
        self.assertEqual(result["ads"][0]["reason_text"], "第 2／3 名，每筆 617 對上限 450（太貴）")
        self.assertEqual(result["keep"][0]["entity_id"], c)
        self.assertEqual(result["keep"][0]["daily_spend"], 200.0)
        self.assertEqual(
            (result["keep"][0]["rank"], result["keep"][0]["verdict_label"],
             result["keep"][0]["reason_text"]),
            (1, "留下", "第 1／3 名，每筆 50 在上限內（划算）"),
        )
        self.assertEqual(result["daily_saving"], 220.0 + 617.0)
        self.assertEqual(result["can_support"], 1)
        self.assertEqual(result["active_ads"], 3)
        self.assertEqual(result["campaign_id"], self.campaign)
        self.assertEqual(result["campaign_name"], "活動一")

    def test_cleanup_keeps_the_graded_units_and_refusal_without_reclassifying(self):
        close, kept = self.make_ad("closed"), self.make_ad("unresolved")
        observed = self.item(close, "wasted", spend=1540, result_count=0)
        observed["cap_comparison"] = {
            "basis": "own", "currency": "TWD", "reason": None, "message": None,
            "source": "user", "unit_basis": "manual_ntd_input",
        }
        for currency, comparison in (
            (None, None),
            (None, {"basis": "own", "currency": "TWD", "reason": "cap_currency_unknown",
                    "message": "Unit not verified"}),
            ("USD", {"basis": "own", "currency": "TWD", "reason": "cap_currency_mismatch",
                     "message": "Different observed currency"}),
        ):
            with self.subTest(currency=currency, comparison=comparison):
                unresolved = self.item(kept, "insufficient", spend=200)
                unresolved["current"]["currency"] = currency
                unresolved["cap_comparison"] = comparison
                result = self.candidates([observed, unresolved], can_support=1)
                self.assertEqual(self.ids(result["ads"]), [close])
                self.assertEqual(self.ids(result["keep"]), [kept])
                self.assertEqual(result["ads"][0]["currency"], "TWD")
                self.assertEqual(result["ads"][0]["cap_comparison"], observed["cap_comparison"])
                row = result["keep"][0]
                self.assertEqual(row["currency"], currency)
                self.assertEqual(row["cap_comparison"], comparison)
                self.assertEqual(row["spend"], 200)
                self.assertEqual(row["grade"], "insufficient")
                self.assertIsNone(row["rank"])
                self.assertIsNone(row["verdict"])

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
        self.assertEqual(self.ids(result["ads"]), [b, a])
        self.assertIsNone(result["ads"][0]["spend_7d"])
        self.assertIsNone(result["ads"][0]["daily_spend"])
        self.assertIsNone(result["daily_saving"])

    # -- open replacement lineage (correction 4) ----------------------------------------------

    def test_new_ad_not_yet_verified_never_closes(self):
        old = self.make_ad("old1")
        new = self.make_ad("new1")
        self.replace_ad(old, new, state="pending")  # not confirmed yet
        other = self.make_ad("other1")
        keeper = self.make_ad("keeper1")
        items = [
            self.item(new, "wasted", spend=1540, result_count=0),
            self.item(other, "over", cost=600, spend=4200),
            self.item(keeper, "on_target", cost=50, spend=1400),
        ]
        result = self.candidates(items, can_support=1)
        self.assertEqual(self.ids(result["ads"]), [other])
        self.assertEqual(self.ids(result["keep"]), [keeper, new])

    def test_old_ad_awaiting_followup_pause_never_closes(self):
        old = self.make_ad("old2")
        new = self.make_ad("new2")
        self.replace_ad(old, new, state="confirmed")  # replacement is live
        other = self.make_ad("other2")
        keeper = self.make_ad("keeper2")
        items = [
            self.item(old, "over", cost=900, spend=6300),  # the most expensive, but pending
            self.item(other, "over", cost=600, spend=4200),
            self.item(keeper, "on_target", cost=50, spend=1400),
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


class RejectionMemoryTest(unittest.TestCase):
    """F29-I01 Contract B counterexamples: the grade remembered at a "no" holds an ad out of the
    cleanup until its current grade ranks worse (on_target < watch < over < wasted). Borrows the
    `CleanupCandidatesTest` fixture helpers without re-running that class's tests."""

    setUp = CleanupCandidatesTest.setUp
    make_ad = CleanupCandidatesTest.make_ad
    obs = CleanupCandidatesTest.obs
    rows_by_entity = CleanupCandidatesTest.rows_by_entity
    candidates = CleanupCandidatesTest.candidates
    item = CleanupCandidatesTest.item
    ids = staticmethod(CleanupCandidatesTest.ids)
    CAP = 100  # the remembered cap below: 划算 <= 100 < 偏貴 <= 120 < 太貴

    def remember(self, entries, *, reason="還想再看看", grades=True):
        """One rejected cleanup set carrying `decision_grades` (`entity_id -> (grade, at)`);
        `grades=False` writes a set from before the column (NULL, no memory)."""
        set_id = db.new_id("acs")
        memory = {
            entity_id: {"grade": grade, "cost_per_result": 150, "cap": 100, "at": at}
            for entity_id, (grade, at) in entries.items()
        } if grades else None
        plan = {"source": "cleanup", "items": [
            {"id": db.new_id("adx"), "kind": "pause", "target_id": entity_id, "before": {},
             "after": {"status": "PAUSED"}, "reason": "x"} for entity_id in entries
        ]}
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,decision_reason,"
            "decision_grades) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "清理：活動一",
             "2026-01", "rejected", db.jsonb(plan), "test", reason,
             db.jsonb(memory) if memory is not None else None),
        )
        self.conn.commit()
        return set_id

    def memory(self):
        labels = {"on_target": "划算", "watch": "偏貴", "over": "太貴", "wasted": "沒賣出"}
        return {
            eid: {**entry, "grade_label": labels[entry["grade"]]}
            for eid, entry in triage_capacity.decision_memory(
                self.conn, self.org, self.brand).items()
        }

    def test_a_set_without_memory_holds_nothing(self):
        a = self.make_ad("a1")
        self.remember({a: ("over", None)}, grades=False)  # a set from before the column
        self.assertEqual(self.memory(), {})
        result = self.candidates([self.item(a, "wasted", spend=400, result_count=0)],
                                 can_support=None, memory=self.memory())
        self.assertEqual(self.ids(result["ads"]), [a])
        self.assertIsNone(result["ads"][0]["rejected_before"])

    def test_same_grade_is_held_and_the_cut_is_not_refilled(self):
        a, b, c = self.make_ad("a1"), self.make_ad("a2"), self.make_ad("a3")
        self.remember({a: ("over", "2026-01-05T10:00:00+00:00")})
        items = [
            self.item(a, "over", cost=150), self.item(b, "watch", cost=110),
            self.item(c, "on_target", cost=50),
        ]
        # can_support 2, three active: one to close -- the held 太貴 ad keeps its place, so the
        # 偏貴 ad is not pulled in instead and no row is raised.
        self.assertIsNone(self.candidates(items, can_support=2, memory=self.memory()))

    def test_worse_grade_returns_with_rejected_before(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        set_id = self.remember({a: ("watch", "2026-01-05T10:00:00+00:00")}, reason="季節性")
        items = [self.item(a, "over", cost=150), self.item(b, "on_target", cost=50)]
        result = self.candidates(items, can_support=1, memory=self.memory())
        self.assertEqual(self.ids(result["ads"]), [a])
        self.assertEqual(result["ads"][0]["rejected_before"], {
            "grade": "watch", "grade_label": "偏貴", "at": "2026-01-05T10:00:00+00:00",
            "reason": "季節性", "change_set_id": set_id,
        })
        self.assertIsNone(result["keep"][0]["rejected_before"])

    def test_the_newest_memory_wins(self):
        a = self.make_ad("a1")
        self.remember({a: ("watch", "2026-01-02T10:00:00+00:00")})
        newest = self.remember({a: ("over", "2026-01-05T10:00:00+00:00")})
        self.remember({a: ("on_target", "2026-01-01T10:00:00+00:00")})  # older, inserted last
        memory = self.memory()
        self.assertEqual((memory[a]["grade"], memory[a]["change_set_id"]), ("over", newest))
        # Remembered at 太貴: 太貴 again is held; 沒賣出 returns.
        held = self.candidates([self.item(a, "over", cost=150)], can_support=None,
                               memory=memory)
        self.assertIsNone(held)
        result = self.candidates([self.item(a, "wasted", spend=400, result_count=0)],
                                 can_support=None, memory=memory)
        self.assertEqual(result["ads"][0]["rejected_before"]["change_set_id"], newest)

    def test_improved_then_worsened_back_to_the_remembered_grade_is_not_reproposed(self):
        a, b = self.make_ad("a1"), self.make_ad("a2")
        self.remember({a: ("over", "2026-01-05T10:00:00+00:00")})
        memory = self.memory()
        # Improved to 偏貴 in between (nothing to propose), now back at 太貴 -- still not worse.
        for grade, cost in (("watch", 110), ("over", 150)):
            with self.subTest(grade=grade):
                items = [self.item(a, grade, cost=cost), self.item(b, "on_target", cost=50)]
                self.assertIsNone(self.candidates(items, can_support=1, memory=memory))

    def test_wasted_that_stays_wasted_is_held(self):
        a = self.make_ad("a1")
        self.remember({a: ("wasted", "2026-01-05T10:00:00+00:00")})
        items = [self.item(a, "wasted", spend=900, result_count=0)]
        self.assertIsNone(self.candidates(items, can_support=None, memory=self.memory()))

    def test_cap_changed_since_compares_the_grade_under_todays_cap(self):
        # Remembered 偏貴 against a cap of 100; the cap was since cut, so today's ruler reads
        # the ad as 太貴 -- worse, so it returns (the remembered cap is shown, never re-applied).
        a, b = self.make_ad("a1"), self.make_ad("a2")
        self.remember({a: ("watch", "2026-01-05T10:00:00+00:00")})
        items = [self.item(a, "over", cost=110), self.item(b, "on_target", cost=40)]
        result = self.candidates(items, can_support=1, memory=self.memory())
        self.assertEqual(self.ids(result["ads"]), [a])
        self.assertEqual(result["ads"][0]["rejected_before"]["grade"], "watch")

    def test_an_ad_closed_since_is_simply_absent(self):
        gone, b = self.make_ad("a1"), self.make_ad("a2")
        self.remember({gone: ("over", "2026-01-05T10:00:00+00:00")})
        # `classify()` never lists a closed ad, so its memory has nothing to hold or release.
        result = self.candidates([self.item(b, "wasted", spend=400, result_count=0)],
                                 can_support=None, memory=self.memory())
        self.assertEqual(self.ids(result["ads"]), [b])

    def test_an_unranked_remembered_grade_holds_nothing(self):
        a = self.make_ad("a1")
        set_id = db.new_id("acs")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
            "request_hash,content_hash,title,month,status,plan_json,created_by,decision_grades) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (set_id, self.org, self.brand, self.campaign, set_id, set_id, set_id, "x",
             "2026-01", "rejected", db.jsonb({"items": []}), "test",
             db.jsonb({a: {"grade": "insufficient", "cost_per_result": None, "cap": 100}})),
        )
        self.conn.commit()
        self.assertEqual(self.memory(), {})


if __name__ == "__main__":
    unittest.main()
