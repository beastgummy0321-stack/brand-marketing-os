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
            "#- '{external_sync,observations,coverage}' WHERE id=%s",
            (self.campaign,),
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
        return result["items"][0]

    # -- no_target ------------------------------------------------------------------------------

    def test_no_target_when_value_unresolved(self):
        item = self.classify_one()
        self.assertEqual(item["class"], "no_target")
        self.assertEqual(item["reason_code"], "target_unresolved")
        self.assertEqual(item["label"], "尚未設定目標")
        self.assertIsNone(item["target"]["value"])
        self.assertTrue(item["target"]["missing"])

    def test_no_target_result_kind_unknown_even_with_a_resolved_value(self):
        self.set_target(1000, result_kind=None)  # own value resolved, but no result_kind either
        item = self.classify_one()
        self.assertEqual(item["class"], "no_target")
        self.assertEqual(item["reason_code"], "result_kind_unknown")

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
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "needs_resync")
        self.assertEqual(item["window"]["days"], 7)
        self.assertIsNone(item["window"]["extended_from"])

    def test_partially_covered_window_never_yields_stop_loss_or_comparison(self):
        # Coverage only reaches 3 days back -- the smallest (7-day) window is not fully covered,
        # even though the underlying data shape would otherwise fire stop-loss.
        self.set_coverage(self.cutoff - timedelta(days=3), self.cutoff)
        self.set_target(100, result_kind="purchase")
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

    # -- insufficient: below_sample_gate ---------------------------------------------------------

    def test_below_sample_gate_extends_to_28_days_then_gives_up(self):
        self.set_target(1000, result_kind="purchase")  # 3x = 3000, never reached
        for offset in range(28):
            self.obs(self.cutoff - timedelta(days=offset), spend=1, result_count=0,
                      attribution_key=f"small{offset}")
        item = self.classify_one()
        self.assertEqual(item["class"], "insufficient")
        self.assertEqual(item["reason_code"], "below_sample_gate")
        self.assertEqual(item["window"]["days"], 28)
        self.assertEqual(item["window"]["extended_from"], 14)

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

    # -- _compare guard ---------------------------------------------------------------------------

    def test_compare_guards_a_falsy_current_cost_per_result(self):
        self.assertEqual(
            triage._compare(0, 10), ("insufficient", "below_sample_gate", None),
        )
        self.assertEqual(
            triage._compare(None, 10), ("insufficient", "below_sample_gate", None),
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
            return sum(1 for sql in counting.calls if "ads_external_daily" in sql)

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


if __name__ == "__main__":
    unittest.main()
