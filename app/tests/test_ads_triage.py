"""app/tests/test_ads_triage.py — F18-I02 falsifiers: every class and reason code the shared
contract defines, plus the named guarantees (non-sales ad never judged on purchases, stop-loss
never fires without a target, a derived zero is what lets stop-loss fire, an unsynced part of a
window never reads as proven anything, one read serves the whole campaign).
"""

import unittest
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.ads import channels, repository, result_kinds, tracked_zero, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db

ACCOUNT_TZ = "Asia/Taipei"


class _Reader:
    """Stand-in source capability (F18-I01/targets test pattern): reports one account carrying a
    known timezone so `triage._account_cutoff` has a real, deterministic cutoff to resolve --
    never `channels.external_reader`'s own platform branching."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": ACCOUNT_TZ}]


class _CountingConn:
    """Wraps a real connection, counting every `.execute()` call and recording the SQL text --
    used to prove `classify()` reads the campaign's daily rows exactly once, never once per ad
    (review fix: N+1)."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append(sql)
        return self._inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class TriageTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="程式分流測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="既有活動",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告一", "parent_native_kind": "campaign",
             "parent_native_id": "c1"},
        )
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()
        # Broad default coverage (well past anything any test's windows touch) so every test
        # below exercises its own class/reason without also having to think about the coverage
        # gate -- the coverage-gate tests explicitly narrow or remove it.
        self.set_coverage(self.cutoff - timedelta(days=90), self.cutoff)
        self.conn.commit()

    def set_coverage(self, start, end):
        """The campaign's recorded read ranges become exactly `[start, end]` (F49 Contract V:
        `record_sync` keeps a union, so the earlier ranges are cleared first)."""
        self.clear_coverage()
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": start.isoformat(), "end": end.isoformat()},
            },
        )
        self.conn.commit()

    def clear_coverage(self):
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json "
            "#- '{external_sync,observations,coverage}' "
            "#- '{external_sync,observations,ranges}' WHERE id=%s",
            (self.campaign,),
        )
        self.conn.commit()

    def drop_day(self, day):
        """Remove every row of `day` -- a day neither read by a range nor proven by a row."""
        self.conn.execute(
            "DELETE FROM ads_external_daily WHERE campaign_id=%s AND day=%s", (self.campaign, day),
        )
        self.conn.commit()

    def set_target(self, value, result_kind=None):
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign,
            result_kind=result_kind, basis="own", value=value, expected_revision=0,
            actor="測試員",
        )
        self.conn.commit()

    def obs(self, day, *, spend=100, impressions=1000, result_kind="purchase", result_count=None,
            result_action="omni_purchase", result_attribution="7d_click+1d_view",
            attribution_key=None, purchases=None, ad_id=None):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {
                "entity_id": ad_id or self.ad["id"], "day": day, "metric_scope": "ad",
                "attribution_key": attribution_key or str(day), "currency": "TWD",
                "source": "meta", "spend": spend, "impressions": impressions,
                "purchases": purchases,
            },
            result_kind=result_kind, result_count=result_count,
            result_action=result_action, result_attribution=result_attribution,
        )
        self.conn.commit()

    def classify_one(self):
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["window_days"], triage.WINDOW_STEPS[-1])
        item = result["items"][0]
        # F19-I07: every item carries the campaign's own name (GET .../triage returns this shape
        # unwrapped -- `triage_routes.py::get_campaign_triage` calls `classify()` directly).
        self.assertEqual(item["campaign_name"], "既有活動")
        # F27-I09 Done #7: every item also carries `campaign_objective` -- this fixture's root
        # entity (setUp) never sets its own `objective`, so it reads "other" (never a guess).
        self.assertEqual(item["campaign_objective"], "other")
        return item

    # -- no_target ------------------------------------------------------------------------------

    def test_no_target_when_value_unresolved(self):
        item = self.classify_one()
        self.assertEqual(item["class"], "no_target")
        self.assertEqual(item["reason_code"], "target_unresolved")
        self.assertEqual(item["label"], "尚未設定目標")
        self.assertIsNone(item["target"]["value"])
        self.assertTrue(item["target"]["missing"])
        self.assertEqual((item["grade"], item["grade_label"]), ("no_target", "未判斷"))

    def test_no_target_result_kind_unknown_even_with_a_resolved_value(self):
        self.set_target(1000, result_kind=None)  # own value resolved, but no result_kind either
        item = self.classify_one()
        self.assertEqual(item["class"], "no_target")
        self.assertEqual(item["reason_code"], "result_kind_unknown")
        self.assertEqual((item["grade"], item["grade_label"]), ("no_target", "未判斷"))

    def test_stop_loss_does_not_fire_without_a_target(self):
        # Exact same spend/known-zero shape that fires stop-loss in
        # `test_stop_loss_fires_on_a_derived_zero` below, minus a resolved target -- must
        # classify no_target, never stop_loss, no matter how far over any implied threshold.
        self.obs(
            self.cutoff - timedelta(days=10), spend=50, result_count=5, attribution_key="demo",
        )
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=500, result_count=None,
                      attribution_key=f"unset{offset}")
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        item = self.classify_one()
        self.assertEqual(item["class"], "no_target")
        self.assertEqual(item["reason_code"], "target_unresolved")

    # -- stop_loss --------------------------------------------------------------------------------

    def test_stop_loss_fires_on_a_derived_zero(self):
        self.set_target(100, result_kind="purchase")  # threshold = 3 * 100 = 300
        # Demonstrate a real purchase outside the classify window but inside the 28-day
        # derivation lookback, then let 7 days of known spend with no reported result derive to
        # a known zero (F18-I01).
        self.obs(
            self.cutoff - timedelta(days=10), spend=50, result_count=5, attribution_key="demo",
        )
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=50, result_count=None,
                      attribution_key=f"target{offset}")
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        item = self.classify_one()
        self.assertEqual(item["class"], "stop_loss")
        self.assertEqual(item["reason_code"], "spend_over_target_no_result")
        self.assertEqual((item["grade"], item["grade_label"]), ("wasted", "沒賣出"))
        self.assertEqual(item["current"]["result_count"], 0)
        self.assertGreater(item["current"]["derived_zero_days"], 0)
        self.assertEqual(item["window"]["days"], 7)

    def test_unknown_result_never_reads_as_stop_loss(self):
        self.set_target(100, result_kind="purchase")
        # Same overspend, but result never derived or reported -- stays unknown.
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=500, result_count=None,
                      attribution_key=f"unk{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "result_unknown_days")
        # Unknown cost: 資料不足, never a grade and never 剛開始.
        self.assertEqual((item["grade"], item["grade_label"]), ("insufficient", "資料不足"))

    # -- coverage gate (review blocker) ----------------------------------------------------------

    def test_no_coverage_is_needs_resync_never_stop_loss(self):
        self.clear_coverage()
        self.set_target(100, result_kind="purchase")
        # Same known-zero, over-threshold shape that fires stop-loss when covered.
        self.obs(
            self.cutoff - timedelta(days=10), spend=50, result_count=5, attribution_key="demo",
        )
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=50, result_count=None,
                      attribution_key=f"target{offset}")
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        # F49 Contract V: a row proves its day, so with no recorded range the window is unread
        # only where a day has no row either.
        self.drop_day(self.cutoff - timedelta(days=3))
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "needs_resync")
        self.assertEqual(item["window"]["days"], 7)
        self.assertIsNone(item["window"]["extended_from"])
        self.assertEqual((item["grade"], item["grade_label"]), ("insufficient", "資料不足"))

    def test_partially_covered_window_never_yields_stop_loss_or_comparison(self):
        # Coverage only reaches 3 days back and days 4-6 back have no row either -- the smallest
        # (7-day) window is not fully read, even though the data shape would fire stop-loss.
        self.set_coverage(self.cutoff - timedelta(days=3), self.cutoff)
        self.set_target(100, result_kind="purchase")
        self.obs(
            self.cutoff - timedelta(days=10), spend=50, result_count=5, attribution_key="demo",
        )
        for offset in range(4):
            self.obs(self.cutoff - timedelta(days=offset), spend=100, result_count=None,
                      attribution_key=f"target{offset}")
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign,
            self.cutoff - timedelta(days=6), self.cutoff, self.cutoff,
        )
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "needs_resync")
        self.assertNotIn(item["class"], {"stop_loss", "worse", "better", "flat"})

    def test_previous_window_not_covered_is_no_previous_window(self):
        # Current window fully covered and fully known; previous window falls outside coverage.
        self.set_coverage(self.cutoff - timedelta(days=6), self.cutoff)
        self.set_target(1, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=10, result_count=2,
                      attribution_key=f"cur{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "no_previous_window")
        # F28-I02: an uncovered previous window never blocks the grade (cost 5 > 1.2 x 1).
        self.assertEqual((item["grade"], item["grade_label"]), ("over", "太貴"))

    # -- insufficient: too_new (剛開始) -----------------------------------------------------------

    def test_too_new_extends_to_28_days_then_gives_up(self):
        self.set_target(1000, result_kind="purchase")  # 3x = 3000, never reached
        for offset in range(28):
            self.obs(self.cutoff - timedelta(days=offset), spend=1, result_count=0,
                      attribution_key=f"small{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "too_new")
        self.assertEqual(item["window"]["days"], 28)
        self.assertEqual(item["window"]["extended_from"], 14)
        # Known zero results but below 3 x cap: 剛開始, never 沒賣出.
        self.assertEqual(item["current"]["result_count"], 0)
        self.assertEqual(
            (item["grade"], item["grade_label"]), ("insufficient", "剛開始、數字還不夠"),
        )

    # -- insufficient: mixed_result_definition / needs_resync / no_previous_window --------------

    def test_mixed_result_definition_is_insufficient(self):
        self.set_target(1, result_kind="purchase")  # trivial spend gate
        self.obs(self.cutoff, spend=10, result_count=5, result_kind="purchase",
                 attribution_key="a")
        self.obs(self.cutoff - timedelta(days=1), spend=10, result_count=3,
                 result_kind="engagement", result_action="post_engagement",
                 result_attribution="1d_click", attribution_key="b")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "mixed_result_definition")
        self.assertEqual((item["grade"], item["grade_label"]), ("insufficient", "資料不足"))

    def test_needs_resync_from_legacy_rows_is_insufficient(self):
        self.set_target(1, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=10, result_kind=None,
                      result_count=None, result_action=None, result_attribution=None,
                      attribution_key=f"old{offset}")
        self.conn.execute(
            "UPDATE ads_external_daily SET availability=availability-'result_count' "
            "WHERE campaign_id=%s AND entity_id=%s",
            (self.campaign, self.ad["id"]),
        )
        self.conn.commit()
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "needs_resync")

    def test_no_previous_window_when_never_synced_before(self):
        self.set_target(1, result_kind="purchase")  # trivial spend gate passes gate immediately
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=10, result_count=2,
                      attribution_key=f"cur{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "no_previous_window")

    def test_previous_known_zero_result_is_no_previous_window(self):
        # Previous window fully covered and fully known, but its own cost_per_result is None
        # (known zero results) -- never a divisor, `no_previous_window`, not a crash.
        self.set_target(1, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=10, result_count=0,
                      attribution_key=f"prevzero{offset}")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=10, result_count=2,
                      attribution_key=f"cur{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "no_previous_window")
        self.assertIsNone(item["previous"]["cost_per_result"])

    # -- worse / better / flat -------------------------------------------------------------------

    def test_flat_exact_no_change_is_flat(self):
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=5, result_count=5,
                      attribution_key=f"prevsame{offset}")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=5, result_count=5,
                      attribution_key=f"cursame{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "flat")
        self.assertEqual(item["reason_code"], "cost_per_result_flat")
        self.assertEqual(item["change_pct"], 0.0)

    def test_flat_within_band_keeps_change_pct_none_reasoning_off(self):
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=100, result_count=10,
                      attribution_key=f"prevflat{offset}")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=105, result_count=10,
                      attribution_key=f"curflat{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "flat")
        self.assertEqual(item["reason_code"], "cost_per_result_flat")
        self.assertAlmostEqual(item["change_pct"], (105 - 100) / 100)

    def test_better_when_cost_per_result_drops_past_the_flat_band(self):
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=100, result_count=10,
                      attribution_key=f"prevbetter{offset}")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=60, result_count=10,
                      attribution_key=f"curbetter{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "better")
        self.assertEqual(item["reason_code"], "cost_per_result_down")

    def test_worse_when_cost_per_result_rises_past_the_flat_band(self):
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=100, result_count=10,
                      attribution_key=f"prevworse{offset}")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=150, result_count=10,
                      attribution_key=f"curworse{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "worse")
        self.assertEqual(item["reason_code"], "cost_per_result_up")

    # -- non-sales ad never judged on purchases --------------------------------------------------

    def test_non_sales_ad_with_incidental_purchase_is_never_judged_on_purchases(self):
        self.set_target(1000, result_kind="lead")
        for offset in range(7):
            # `purchases` (the generic METRICS column) is set on one row -- never read by
            # triage, which only ever uses `result_views` keyed by this ad's own `result_kind`.
            self.obs(
                self.cutoff - timedelta(days=7 + offset), spend=50, result_count=10,
                result_kind="lead", result_action="lead_form", result_attribution="7d_click",
                purchases=(3 if offset == 0 else None), attribution_key=f"prevlead{offset}",
            )
        for offset in range(7):
            self.obs(
                self.cutoff - timedelta(days=offset), spend=50, result_count=10,
                result_kind="lead", result_action="lead_form", result_attribution="7d_click",
                purchases=(1 if offset == 0 else None), attribution_key=f"curlead{offset}",
            )
        item = self.classify_one()
        self.assertEqual(item["current"]["result_kind"], "lead")
        # F19-I06: `target`/`current` each carry the Chinese label alongside the raw kind.
        self.assertEqual(item["current"]["result_label"], result_kinds.label("lead"))
        self.assertEqual(item["target"]["result_label"], result_kinds.label("lead"))
        self.assertIn(item["class"], {"worse", "better", "flat"})
        self.assertIsNone(item["current"]["reason"])

    # -- _account_cutoff fail-closed fallback ------------------------------------------------------

    def test_unknown_account_timezone_falls_back_two_days_not_one(self):
        empty_campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="沒有任何實體",
        )["id"]
        self.conn.commit()
        from app.core import settings as coresettings

        today = coresettings.today_for_org(self.conn, org_id=self.org)
        cutoff = triage._account_cutoff(self.conn, self.org, self.brand, empty_campaign)
        self.assertEqual(cutoff, today - timedelta(days=2))

    # -- _thumbnail_url ---------------------------------------------------------------------------

    def test_thumbnail_url_prefers_thumbnail_over_image(self):
        entity = {"creative": {"fields": {
            "thumbnail_url": "https://example.com/thumb.jpg",
            "image_url": "https://example.com/full.jpg",
        }}}
        self.assertEqual(triage._thumbnail_url(entity), "https://example.com/thumb.jpg")

    def test_thumbnail_url_falls_back_to_image_url(self):
        entity = {"creative": {"fields": {"image_url": "https://example.com/full.jpg"}}}
        self.assertEqual(triage._thumbnail_url(entity), "https://example.com/full.jpg")

    def test_thumbnail_url_none_when_neither_present(self):
        self.assertIsNone(triage._thumbnail_url({"creative": {"fields": {}}}))
        self.assertIsNone(triage._thumbnail_url({"creative": {}}))
        self.assertIsNone(triage._thumbnail_url({}))

    def test_classify_item_carries_the_ad_own_thumbnail(self):
        # End-to-end: `creative` as actually stored by `external.upsert_entity` on a real ad row
        # flows through `_classify_ad` into the item the API returns (issue Done #1).
        self.ad2 = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": "ad_thumb", "name": "有縮圖的廣告",
             "parent_native_kind": "campaign", "parent_native_id": "c1",
             "creative": {"fields": {"thumbnail_url": "https://example.com/thumb.jpg"}}},
        )
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        items_by_entity = {item["entity_id"]: item for item in result["items"]}
        self.assertEqual(
            items_by_entity[self.ad2["id"]]["thumbnail_url"], "https://example.com/thumb.jpg",
        )
        self.assertIsNone(items_by_entity[self.ad["id"]]["thumbnail_url"])

    # -- _compare guard ---------------------------------------------------------------------------

    def test_compare_guards_a_falsy_current_cost_per_result(self):
        self.assertEqual(
            triage._compare(0, 10), ("insufficient", "too_new", None),
        )
        self.assertEqual(
            triage._compare(None, 10), ("insufficient", "too_new", None),
        )
        self.assertEqual(triage._compare(10, 10), ("flat", "cost_per_result_flat", 0.0))

    # -- N+1 -----------------------------------------------------------------------------------

    def test_query_count_does_not_grow_with_ad_count(self):
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=100, result_count=10,
                      attribution_key=f"prevx{offset}")
            self.obs(self.cutoff - timedelta(days=offset), spend=100, result_count=10,
                      attribution_key=f"curx{offset}")

        def count_daily_reads():
            counting = _CountingConn(self.conn)
            triage.classify(counting, self.org, self.brand, self.campaign)
            rows = sum(1 for sql in counting.calls if "SELECT * FROM ads_external_daily" in sql)
            # F49 Contract V: one read of the campaign's row days (`coverage.load`), not per ad.
            days = sum(1 for sql in counting.calls
                       if "SELECT DISTINCT day FROM ads_external_daily" in sql)
            self.assertEqual(days, 1)
            return rows

        one_ad_reads = count_daily_reads()

        for i in range(4):
            ad = external.upsert_entity(
                self.conn, self.org, self.brand, self.campaign,
                {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
                 "native_id": f"ad_extra_{i}", "name": f"廣告{i}",
                 "parent_native_kind": "campaign", "parent_native_id": "c1"},
            )
            for offset in range(7):
                self.obs(self.cutoff - timedelta(days=offset), spend=100, result_count=10,
                          attribution_key=f"extra{i}_{offset}", ad_id=ad["id"])

        five_ad_reads = count_daily_reads()
        self.assertEqual(one_ad_reads, 1)
        self.assertEqual(one_ad_reads, five_ad_reads)


# ---------------------------------------------------------------------------
# F24-I01: the read-only `data` enrichment on `classify()`'s own result -- `sync.state`
# priority order (never/disconnected/failed/syncing/ok), `error`/`last_success_at` semantics,
# and `coverage`/`missing_days` against the SAME window `classify()` judges every ad with.
# A fresh campaign per test (no `ad`-kind entity needed -- `data` doesn't depend on `items`).
# ---------------------------------------------------------------------------


class TriageBoundAdIdTest(TriageTest):
    """F40-I01: every item names the local `ads_ad` bound to its platform ad (`bound_ad_id`) --
    the one field the detail page needs to tell a platform ad with no bound local ad from a
    local ad never built -- read in one query for the whole campaign, joined by `native_id`."""

    def bind_local_ad(self, external_id, *, local_state="bound"):
        group, ad = db.new_id("adg"), db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture','組',100,'new')",
            (group, self.org, self.brand, self.campaign),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name,external_id,"
            "local_state) VALUES(%s,%s,%s,%s,%s,'本地廣告',%s,%s)",
            (ad, self.org, self.brand, self.campaign, group, external_id, local_state),
        )
        self.conn.commit()
        return ad

    def test_item_names_the_local_ad_bound_to_its_native_id(self):
        local_ad = self.bind_local_ad("ad1")
        item = self.classify_one()
        self.assertEqual(item["bound_ad_id"], local_ad)

    def test_item_with_no_local_ad_reads_none(self):
        item = self.classify_one()
        self.assertIsNone(item["bound_ad_id"])

    def test_a_detached_local_ad_does_not_count_as_bound(self):
        self.bind_local_ad("ad1", local_state="detached")
        item = self.classify_one()
        self.assertIsNone(item["bound_ad_id"])

    def test_bound_ad_id_is_one_query_for_the_campaign_never_per_item(self):
        self.bind_local_ad("ad1")
        for i in range(3):
            external.upsert_entity(
                self.conn, self.org, self.brand, self.campaign,
                {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
                 "native_id": f"ad_extra_{i}", "name": f"廣告{i}",
                 "parent_native_kind": "campaign", "parent_native_id": "c1"},
            )
        self.conn.commit()
        counting = _CountingConn(self.conn)
        result = triage.classify(counting, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["items"]), 4)
        self.assertEqual(sum(1 for sql in counting.calls if "FROM ads_ad " in sql), 1)


class TriageDataViewTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F24 data 測試", actor="test", client_name=None,
        )["id"]
        self.reader = _Reader()
        patcher = patch.object(
            channels, "external_reader", side_effect=lambda platform: self.reader,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="資料同步測試",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.conn.commit()
        self.cutoff = (
            db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)
        ).date()

    def data(self):
        return triage.classify(self.conn, self.org, self.brand, self.campaign)["data"]

    def set_section(self, section, **state):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section=section, state=state,
        )
        self.conn.commit()

    def test_never_synced(self):
        # F49 Contract V: every day of the judged window is served with its state -- all
        # `missing` here, while `missing_days` stays [] (never read is its own answer).
        days = [
            {"day": (self.cutoff - timedelta(days=offset)).isoformat(), "state": "missing"}
            for offset in range(triage.WINDOW_STEPS[-1] - 1, -1, -1)
        ]
        self.assertEqual(
            self.data(), {"sync": {"state": "never", "error": None, "last_success_at": None},
                          "coverage": None, "missing_days": [], "days": days,
                          "capacity": {"daily_budget": None, "currency": None, "target": None,
                                       "can_support": None, "active_ads": 0},
                          "status": {"state": "never", "label": "還沒讀過平台資料。",
                                     "missing_days": [], "last_success_at": None}},
        )

    def test_ok(self):
        self.set_section(
            "observations", status="success", last_success_at=db.now_utc().isoformat(),
            coverage={"start": (self.cutoff - timedelta(days=90)).isoformat(),
                      "end": self.cutoff.isoformat()},
        )
        sync = self.data()["sync"]
        self.assertEqual(sync["state"], "ok")
        self.assertIsNone(sync["error"])
        self.assertIsNotNone(sync["last_success_at"])

    def test_syncing(self):
        self.set_section("observations", status="syncing", last_attempt_at=db.now_utc().isoformat())
        self.assertEqual(self.data()["sync"]["state"], "syncing")

    def test_failed_with_error(self):
        self.set_section(
            "observations", status="error", error="讀取失敗",
            last_attempt_at=db.now_utc().isoformat(),
        )
        sync = self.data()["sync"]
        self.assertEqual(sync["state"], "failed")
        self.assertEqual(sync["error"], "讀取失敗")

    def test_auth_expired_from_permission_denied_error_code(self):
        # F27-I09 Contract I / correction 2: the STORED error code (`app/meta/repository.py`'s own
        # collapse of every permission-shaped Graph error), never a raw provider number.
        self.set_section(
            "observations", status="error", error="沒有讀取權限", error_code="permission_denied",
            last_attempt_at=db.now_utc().isoformat(),
        )
        sync = self.data()["sync"]
        self.assertEqual(sync["state"], "auth_expired")
        self.assertEqual(sync["error"], "沒有讀取權限")

    def test_other_error_code_still_reads_as_failed(self):
        self.set_section(
            "observations", status="error", error="暫時失敗", error_code="source_error",
            last_attempt_at=db.now_utc().isoformat(),
        )
        self.assertEqual(self.data()["sync"]["state"], "failed")

    def test_failed_with_null_error_keeps_old_last_success_at(self):
        old_success = db.now_utc().isoformat()
        self.set_section(
            "observations", status="success", last_success_at=old_success,
            coverage={"start": (self.cutoff - timedelta(days=10)).isoformat(),
                      "end": self.cutoff.isoformat()},
        )
        self.set_section(
            "observations", status="error", error=None, last_attempt_at=db.now_utc().isoformat(),
        )
        sync = self.data()["sync"]
        self.assertEqual(sync["state"], "failed")
        self.assertIsNone(sync["error"])
        self.assertEqual(sync["last_success_at"], old_success)

    def test_partial_counts_as_failed(self):
        self.set_section("observations", status="partial", error="部分頁面失敗")
        self.assertEqual(self.data()["sync"]["state"], "failed")

    def test_disconnected(self):
        # act_1 is no longer among the bound accounts this reader reports -- `state` reads
        # `disconnected` even though the section itself synced cleanly (priority order: never /
        # disconnected / failed / syncing / ok).
        self.reader.accounts = lambda conn, org, brand: []
        self.set_section(
            "observations", status="success", last_success_at=db.now_utc().isoformat(),
            coverage={"start": (self.cutoff - timedelta(days=10)).isoformat(),
                      "end": self.cutoff.isoformat()},
        )
        self.assertEqual(self.data()["sync"]["state"], "disconnected")

    def test_coverage_null_gives_empty_missing_days(self):
        data = self.data()
        self.assertIsNone(data["coverage"])
        self.assertEqual(data["missing_days"], [])

    def test_window_partly_outside_coverage_lists_exact_missing_dates(self):
        coverage_start = self.cutoff - timedelta(days=10)
        self.set_section(
            "observations", status="success", last_success_at=db.now_utc().isoformat(),
            coverage={"start": coverage_start.isoformat(), "end": self.cutoff.isoformat()},
        )
        data = self.data()
        window_start = self.cutoff - timedelta(days=triage.WINDOW_STEPS[-1] - 1)
        missing = data["missing_days"]
        self.assertEqual(len(missing), (coverage_start - window_start).days)
        self.assertEqual(missing[0], window_start.isoformat())
        self.assertEqual(missing[-1], (coverage_start - timedelta(days=1)).isoformat())
        self.assertNotIn(self.cutoff.isoformat(), missing)
        self.assertNotIn(coverage_start.isoformat(), missing)
        self.assertEqual(
            data["coverage"], {"start": coverage_start.isoformat(), "end": self.cutoff.isoformat()},
        )


# ---------------------------------------------------------------------------
# F26-I01, F49 Contract L: `classify()`'s own `closed` block -- judgement reads running ads and
# unknown ones (`lifecycle.judged`); ads not delivering or off are kept and reported, never judged.
# The status table itself is tested in `test_ads_lifecycle.py`.
# ---------------------------------------------------------------------------


class TriageClosedAdsTest(unittest.TestCase):
    """Ground truth (issue Blocked-if evidence): a campaign of 5 active + 11 paused + 4 archived
    ads judges 5, reports `closed.total == 15` with the paused/archived split, and never a second
    query against `ads_external_daily` (the closed items' own numbers reuse the one read
    `classify()` already makes for its active ads)."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F26 已關閉廣告測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="投放中活動",
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.conn.commit()

    def make_ad(self, native_id, *, native_status=None, name=None):
        return external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": name or native_id, "native_status": native_status,
             "parent_native_kind": "campaign", "parent_native_id": "c1"},
        )

    def test_five_active_eleven_paused_four_archived(self):
        for i in range(5):
            self.make_ad(f"active_{i}", native_status="ACTIVE")
        for i in range(11):
            self.make_ad(f"paused_{i}", native_status="PAUSED")
        for i in range(4):
            self.make_ad(f"archived_{i}", native_status="ARCHIVED")
        self.conn.commit()

        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(result["closed"], {
            "groups": [
                {"state": "off", "label": "已封存", "count": 4},
                {"state": "off", "label": "已暫停", "count": 11},
            ],
            "paused": 11, "archived": 4, "other": 0, "total": 15,
            "items": result["closed"]["items"], "truncated": False,
        })
        self.assertEqual(len(result["closed"]["items"]), 15)

    def test_disapproved_ad_is_not_judged_and_listed_closed(self):
        """F49 Contract L: an ad on the platform but not delivering (被拒登) holds no capacity and
        gets no grade -- it is listed in the closed block with its served delivery label."""
        self.make_ad("live", native_status="ACTIVE")
        self.make_ad("refused", native_status="DISAPPROVED", name="被拒的廣告")
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual([i["name"] for i in result["items"]], ["live"])
        self.assertEqual(result["items"][0]["delivery"], {"state": "running", "label": "投放中"})
        self.assertEqual(result["closed"]["groups"],
                         [{"state": "not_running", "label": "被拒登", "count": 1}])
        self.assertEqual(result["closed"]["other"], 1)
        item = result["closed"]["items"][0]
        self.assertEqual(item["name"], "被拒的廣告")
        self.assertEqual(item["delivery"], {"state": "not_running", "label": "被拒登"})
        self.assertEqual(item["delivery_label"], "被拒登")

    def test_null_status_is_active_never_closed(self):
        self.make_ad("no_status", native_status=None)
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["delivery"],
                         {"state": "unknown", "label": "平台狀態不明"})
        self.assertEqual(result["closed"]["total"], 0)

    def test_other_bucket_covers_deleted_and_the_two_cascade_pauses(self):
        self.make_ad("d1", native_status="DELETED")
        self.make_ad("d2", native_status="ADSET_PAUSED")
        self.make_ad("d3", native_status="CAMPAIGN_PAUSED")
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(result["closed"], {
            "groups": [
                {"state": "off", "label": "已刪除", "count": 1},
                {"state": "off", "label": "所屬廣告組已暫停", "count": 1},
                {"state": "off", "label": "所屬活動已暫停", "count": 1},
            ],
            "paused": 0, "archived": 0, "other": 3, "total": 3,
            "items": result["closed"]["items"], "truncated": False,
        })

    def test_closed_item_shape_carries_its_own_last_window_numbers(self):
        ad = self.make_ad("paused_1", native_status="PAUSED", name="停了的廣告")
        self.set_coverage_for(self.cutoff() - timedelta(days=90), self.cutoff())
        for offset in range(7):
            self.obs(ad["id"], self.cutoff() - timedelta(days=offset), spend=10, result_count=2)
        self.conn.commit()

        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        item = result["closed"]["items"][0]
        self.assertEqual(item["entity_id"], ad["id"])
        self.assertEqual(item["name"], "停了的廣告")
        self.assertEqual(item["native_status"], "PAUSED")
        self.assertIsNone(item["thumbnail_url"])
        self.assertEqual(item["spend"], 70)
        self.assertIsNotNone(item["cost_per_result"])
        self.assertEqual(item["result_label"], result_kinds.label("purchase"))

    def test_no_data_closed_item_reads_null_never_crashes(self):
        ad = self.make_ad("paused_no_data", native_status="PAUSED")
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        item = result["closed"]["items"][0]
        self.assertEqual(item["entity_id"], ad["id"])
        self.assertIsNone(item["spend"])
        self.assertIsNone(item["cost_per_result"])
        self.assertEqual(item["result_label"], result_kinds.label(None))
        self.assertIsNone(item["bound_ad_id"])

    def test_closed_item_names_its_bound_local_ad(self):
        # F40-I01: the closed block carries `bound_ad_id` too (a paused platform ad the user
        # built here is still "built", never counted as an unmatched platform ad).
        self.make_ad("paused_bound", native_status="PAUSED")
        group, local_ad = db.new_id("adg"), db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture','組',100,'new')",
            (group, self.org, self.brand, self.campaign),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name,external_id,"
            "local_state) VALUES(%s,%s,%s,%s,%s,'本地廣告','paused_bound','bound')",
            (local_ad, self.org, self.brand, self.campaign, group),
        )
        self.conn.commit()
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(result["closed"]["items"][0]["bound_ad_id"], local_ad)

    def test_closed_items_capped_with_truncated_flag(self):
        for i in range(3):
            self.make_ad(f"paused_{i}", native_status="PAUSED")
        self.conn.commit()
        with patch.object(triage, "_CLOSED_ITEMS_CAP", 2):
            result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["closed"]["items"]), 2)
        self.assertEqual(result["closed"]["total"], 3)
        self.assertTrue(result["closed"]["truncated"])

    def cutoff(self):
        return (db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)).date()

    def set_coverage_for(self, start, end):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": start.isoformat(), "end": end.isoformat()},
            },
        )
        self.conn.commit()

    def obs(self, ad_id, day, *, spend, result_count):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": ad_id, "day": day, "metric_scope": "ad",
             "attribution_key": f"{ad_id}-{day.isoformat()}", "currency": "TWD", "source": "meta",
             "spend": spend, "impressions": 1000, "purchases": None},
            result_kind="purchase", result_count=result_count, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()


class CampaignObjectiveFamilyClassifyTest(TriageTest):
    """F27-I09 Done #7: `classify()`'s own items carry `campaign_objective`, routed through the
    Meta adapter's own raw-objective mapping for an imported campaign's own root entity -- reuses
    `TriageTest.setUp`'s fixture (an imported campaign whose root entity carries no `objective` by
    default, already falsified as `"other"` by `classify_one()` above)."""

    def _set_root_objective(self, objective):
        self.conn.execute(
            "UPDATE ads_external_entity SET objective=%s WHERE org_id=%s AND brand_id=%s AND "
            "campaign_id=%s AND native_kind='campaign' AND parent_native_id IS NULL",
            (objective, self.org, self.brand, self.campaign),
        )
        self.conn.commit()

    def test_meta_sales_objective_maps_to_sales_family(self):
        self._set_root_objective("OUTCOME_SALES")
        item = self.classify_one_without_default_assertion()
        self.assertEqual(item["campaign_objective"], "sales")

    def test_meta_engagement_objective_maps_to_engagement_family(self):
        self._set_root_objective("POST_ENGAGEMENT")
        item = self.classify_one_without_default_assertion()
        self.assertEqual(item["campaign_objective"], "engagement")

    def test_meta_leads_objective_has_no_named_family_and_reads_other(self):
        self._set_root_objective("OUTCOME_LEADS")
        item = self.classify_one_without_default_assertion()
        self.assertEqual(item["campaign_objective"], "other")

    def classify_one_without_default_assertion(self):
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(len(result["items"]), 1)
        return result["items"][0]


class TriageGradeTest(TriageTest):
    """F28-I02 (ads.md §6.32): every active ad is graded against the one cap T -- 划算 <= T,
    偏貴 <= 1.2T, 太貴 > 1.2T, 沒賣出 = a known zero over 3T, a known zero under it 剛開始. Reuses
    `TriageTest`'s fixture (one campaign, one ad, broad coverage, account timezone)."""

    def extra_ad(self, native_id):
        ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": native_id, "parent_native_kind": "campaign",
             "parent_native_id": "c1"},
        )
        self.conn.commit()
        return ad["id"]

    def week(self, ad_id, *, spend, result_count, tag):
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=spend,
                     result_count=result_count, attribution_key=f"{tag}{offset}", ad_id=ad_id)

    def items_by_entity(self):
        result = triage.classify(self.conn, self.org, self.brand, self.campaign)
        return {item["entity_id"]: item for item in result["items"]}

    def test_boundaries_at_the_cap_and_at_one_point_two_times_it(self):
        self.set_target(100, result_kind="purchase")
        at_cap, at_band, over_band = (
            self.extra_ad("at_cap"), self.extra_ad("at_band"), self.extra_ad("over_band"),
        )
        # 7 days x 1 purchase a day; spend 700+ >= 3 x 100 passes the gate on the first window.
        self.week(at_cap, spend=100, result_count=1, tag="cap")
        self.week(at_band, spend=120, result_count=1, tag="band")
        self.week(over_band, spend=121, result_count=1, tag="over")
        items = self.items_by_entity()
        self.assertEqual(items[at_cap]["grade"], "on_target")
        self.assertEqual(items[at_cap]["grade_label"], "划算")
        self.assertEqual(items[at_band]["grade"], "watch")
        self.assertEqual(items[at_band]["grade_label"], "偏貴")
        self.assertEqual(items[over_band]["grade"], "over")
        self.assertEqual(items[over_band]["grade_label"], "太貴")
        for entity_id in (at_cap, at_band, over_band):
            # Timezone cutoff unchanged: the graded window still ends on the account's own
            # yesterday.
            self.assertEqual(items[entity_id]["window"]["end"], self.cutoff)
            self.assertEqual(items[entity_id]["window"]["days"], 7)

    def test_on_target_graded_with_no_previous_window_and_trend_stays_a_note(self):
        self.set_target(100, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=50, result_count=2,
                     attribution_key=f"cur{offset}")
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]), ("on_target", "划算"))
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "no_previous_window")
        self.assertIsNone(item["change_pct"])

    def test_grade_and_trend_are_independent(self):
        # Worse than last week, yet still inside the cap: 划算 with a `worse` trend note.
        self.set_target(1000, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=100, result_count=10,
                     attribution_key=f"prev{offset}")
            self.obs(self.cutoff - timedelta(days=offset), spend=150, result_count=10,
                     attribution_key=f"cur{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "worse")
        self.assertEqual(item["grade"], "on_target")

    def test_break_even_is_the_provisional_cap_when_no_own_cap(self):
        product_id = brands.create_product(
            self.conn, self.brand, name="測試商品", actor="測試員",
        )["id"]
        brands.save_product_economics(
            self.conn, self.brand, product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign, result_kind="purchase",
            product_id=product_id, expected_revision=0, actor="測試員",
        )
        self.conn.commit()
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=350, result_count=1,
                     attribution_key=f"be{offset}")
        item = self.classify_one()
        self.assertEqual(item["target"]["basis"], "break_even")
        self.assertEqual(item["target"]["value"], 300)  # 500 - 150 - 50
        # 350 <= 1.2 x 300 -- graded against the provisional break-even cap.
        self.assertEqual((item["grade"], item["grade_label"]), ("watch", "偏貴"))

    def test_no_cap_and_no_product_cost_is_not_judged(self):
        product_id = brands.create_product(
            self.conn, self.brand, name="沒成本商品", actor="測試員",
        )["id"]
        brands.save_product_economics(
            self.conn, self.brand, product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=None, shipping_cost=50,
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign, result_kind="purchase",
            product_id=product_id, expected_revision=0, actor="測試員",
        )
        self.conn.commit()
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=5000, result_count=0,
                     attribution_key=f"nocost{offset}")
        item = self.classify_one()
        self.assertIsNone(item["target"]["value"])
        self.assertEqual(item["target"]["missing"], ["product_cost"])
        # A huge spend with zero purchases is still never 沒賣出 without a cap to measure it by.
        self.assertEqual((item["grade"], item["grade_label"]), ("no_target", "未判斷"))
        self.assertIsNone(item["previous_grade"])
        self.assertIsNone(item["grade_move"])

    # -- F29-I01 Contract A: previous_grade / grade_move -------------------------------------------

    def two_weeks(self, *, previous_spend, current_spend, previous_results=1, current_results=1):
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=7 + offset), spend=previous_spend,
                     result_count=previous_results, attribution_key=f"prev{offset}")
            self.obs(self.cutoff - timedelta(days=offset), spend=current_spend,
                     result_count=current_results, attribution_key=f"cur{offset}")

    def test_grade_move_from_on_target_to_over(self):
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=80, current_spend=150)
        item = self.classify_one()
        self.assertEqual((item["previous_grade"], item["grade"]), ("on_target", "over"))
        self.assertEqual(item["grade_move"], {"from": "on_target", "to": "over"})

    def test_same_grade_is_no_move_even_when_the_trend_is_worse(self):
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=50, current_spend=90)  # +80 %, both 划算
        item = self.classify_one()
        self.assertEqual(item["class"], "worse")
        self.assertEqual(item["previous_grade"], "on_target")
        self.assertIsNone(item["grade_move"])

    def test_previous_window_with_few_sales_is_graded_too(self):
        # F48 Contract R: 140 spent for 7 sales is a known cost -- graded, no sample gate.
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=20, current_spend=150)
        item = self.classify_one()
        self.assertEqual((item["previous_grade"], item["grade"]), ("on_target", "over"))
        self.assertEqual(item["grade_move"], {"from": "on_target", "to": "over"})

    def test_previous_window_too_new_has_no_grade_and_no_move(self):
        # Previous: 140 spent, a known zero under 3 x cap = 剛開始 -- not graded, so no move.
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=20, current_spend=150, previous_results=0)
        item = self.classify_one()
        self.assertEqual(item["grade"], "over")
        self.assertIsNone(item["previous_grade"])
        self.assertIsNone(item["grade_move"])

    def test_previous_window_not_synced_has_no_grade(self):
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=80, current_spend=150)
        self.set_coverage(self.cutoff - timedelta(days=6), self.cutoff)
        # One previous day with no row and outside the read range (F49 Contract V).
        self.drop_day(self.cutoff - timedelta(days=10))
        item = self.classify_one()
        self.assertEqual(item["grade"], "over")
        self.assertIsNone(item["previous_grade"])
        self.assertIsNone(item["grade_move"])

    def test_thin_sold_ad_is_graded_with_its_sample_shown(self):
        # F48 Contract R: 3 sales over 3 days is a known cost -- graded on the first window,
        # with 「樣本少」 and 「還太新」 shown beside it, never a hidden gate.
        self.set_target(100, result_kind="purchase")
        # A well-graded month before the 28-day window, then almost nothing inside it.
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=30 + offset), spend=80, result_count=1,
                     attribution_key=f"old{offset}")
        for offset in range(3):
            self.obs(self.cutoff - timedelta(days=offset), spend=10, result_count=1,
                     attribution_key=f"thin{offset}")
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]), ("on_target", "划算"))
        self.assertEqual(item["window"]["days"], 7)
        self.assertIsNone(item["window"]["extended_from"])
        self.assertEqual(
            {k: item["sample"][k] for k in ("sales", "few", "too_new")},
            {"sales": 3, "few": True, "too_new": True},
        )
        self.assertIsNone(item["previous_grade"])
        self.assertIsNone(item["grade_move"])

    # -- F48 Contract R: the four ruler cases ------------------------------------------------------

    def test_one_sale_under_cap_is_on_target_and_few(self):
        self.set_target(100, result_kind="purchase")
        self.obs(self.cutoff, spend=60, result_count=1, attribution_key="one")
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]), ("on_target", "划算"))
        self.assertEqual(item["sample"]["sales"], 1)
        self.assertTrue(item["sample"]["few"])

    def test_zero_sales_at_two_caps_is_too_new(self):
        self.set_target(100, result_kind="purchase")
        self.week(self.ad["id"], spend=29, result_count=0, tag="z")  # 203, about 2 x cap
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]),
                         ("insufficient", "剛開始、數字還不夠"))
        self.assertEqual(item["reason_code"], "too_new")
        self.assertEqual(item["sample"]["sales"], 0)
        self.assertFalse(item["sample"]["few"])

    def test_zero_sales_at_three_caps_is_wasted(self):
        self.set_target(100, result_kind="purchase")
        self.week(self.ad["id"], spend=43, result_count=0, tag="w")  # 301 >= 3 x cap
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]), ("wasted", "沒賣出"))
        self.assertEqual(item["reason_code"], "spend_over_target_no_result")

    def test_a_move_out_of_wasted_is_reported_with_its_own_from(self):
        self.set_target(100, result_kind="purchase")
        self.two_weeks(previous_spend=50, current_spend=150, previous_results=0)
        item = self.classify_one()
        self.assertEqual(item["grade_move"], {"from": "wasted", "to": "over"})

    def test_two_currencies_in_one_window_read_no_data(self):
        self.set_target(100, result_kind="purchase")
        for offset in range(7):
            self.obs(self.cutoff - timedelta(days=offset), spend=150, result_count=1,
                     attribution_key=f"cur{offset}")
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": self.ad["id"], "day": self.cutoff, "metric_scope": "ad",
             "attribution_key": "usd", "currency": "USD", "source": "meta", "spend": 5,
             "impressions": 10, "purchases": None},
            result_kind="purchase", result_count=1, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()
        item = self.classify_one()
        self.assertEqual((item["grade"], item["grade_label"]), ("insufficient", "資料不足"))
        self.assertEqual(item["reason_code"], "mixed_currency")
        self.assertIsNone(item["current"]["spend"])
        self.assertIsNone(item["grade_move"])


class SyncStatesRaisingInsufficientTest(unittest.TestCase):
    """F27-I09 correction 2: `auth_expired` must raise the same 「資料不足」 queue row a `failed`/
    `disconnected` sync already does -- a campaign stuck needing re-authorization is exactly as
    un-judgeable as one whose sync is outright failing."""

    def test_auth_expired_is_in_the_raising_set(self):
        self.assertIn("auth_expired", triage._SYNC_STATES_RAISING_INSUFFICIENT)
        self.assertEqual(
            triage._SYNC_STATES_RAISING_INSUFFICIENT, {"failed", "disconnected", "auth_expired"},
        )


if __name__ == "__main__":
    unittest.main()
