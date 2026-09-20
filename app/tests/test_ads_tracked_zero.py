"""app/tests/test_ads_tracked_zero.py — F18-I01 falsifiers: `tracked_zero.apply()` never guesses
a result definition, and every one of the three ruled conditions independently blocks derivation.
"""

import unittest
from datetime import timedelta

from app.ads import external_repository as external
from app.ads import tracked_zero
from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY
from app.brand_intelligence import repository as brands
from app.core import db, settings


class TrackedZeroTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="推定0測試", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="既有活動",
        )["id"]
        self.entity = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {
                "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
                "native_id": "c1",
            },
        )
        self.end = settings.today_for_org(self.conn, org_id=self.org) - timedelta(days=1)
        self.conn.commit()

    def obs(
        self, day, *, attribution_key="k", spend=100, impressions=1000, result_kind=None,
        result_count=None, result_action=None, result_attribution=None,
    ):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {
                "entity_id": self.entity["id"], "day": day, "metric_scope": "campaign",
                "attribution_key": attribution_key, "currency": "TWD", "source": "meta",
                "spend": spend, "impressions": impressions,
            },
            result_kind=result_kind, result_count=result_count,
            result_action=result_action, result_attribution=result_attribution,
        )
        self.conn.commit()

    def row(self, day, attribution_key="k"):
        return self.conn.execute(
            "SELECT * FROM ads_external_daily WHERE campaign_id=%s AND day=%s "
            "AND attribution_key=%s",
            (self.campaign, day, attribution_key),
        ).fetchone()

    def demonstrate(self, day, **overrides):
        self.obs(
            day, attribution_key="demo", result_kind="purchase", result_count=5,
            result_action="omni_purchase", result_attribution="7d_click+1d_view", **overrides,
        )

    # -- no or ambiguous demonstrated definition: writes nothing -------------------------------

    def test_no_demonstrated_definition_writes_nothing(self):
        self.obs(self.end, result_kind=None, result_count=None)
        result = tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign, self.end, self.end
        )
        self.assertEqual(result, {"derived": 0, "reason": "no_demonstrated_definition"})
        self.assertIsNone(self.row(self.end)["result_count"])

    def test_mixed_result_definition_writes_nothing(self):
        day0, day1 = self.end - timedelta(days=1), self.end
        self.obs(
            day0, attribution_key="a", result_kind="purchase", result_count=5,
            result_action="omni_purchase", result_attribution="7d_click+1d_view",
        )
        self.obs(
            day1, attribution_key="b", result_kind="purchase", result_count=3,
            result_action="omni_purchase", result_attribution="1d_click",
        )
        result = tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, day0, day1)
        self.assertEqual(result, {"derived": 0, "reason": "mixed_result_definition"})

    # -- happy path + idempotent re-sync --------------------------------------------------------

    def test_derives_zero_when_all_conditions_hold_and_resync_is_idempotent(self):
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(
            target_day, attribution_key="target", result_kind="purchase", result_count=None,
            spend=50, impressions=None,
        )
        result = tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign, demo_day, target_day
        )
        self.assertEqual(result, {"derived": 1, "reason": None})
        row = self.row(target_day, "target")
        self.assertEqual(row["result_count"], 0)
        self.assertEqual(row["result_action"], "omni_purchase")
        self.assertEqual(row["result_attribution"], "7d_click+1d_view")
        self.assertEqual(row["availability"]["result_count"], "derived_zero")
        self.assertEqual(row["spend"], 50)
        self.assertEqual(row["attribution_key"], "target")

        again = tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign, demo_day, target_day
        )
        self.assertEqual(again, {"derived": 0, "reason": None})
        self.assertEqual(dict(self.row(target_day, "target")), dict(row))

    # -- each condition independently blocks derivation -----------------------------------------

    def test_result_kind_mismatch_never_derives(self):
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(target_day, attribution_key="target", result_kind="engagement", result_count=None)
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, target_day)
        self.assertIsNone(self.row(target_day, "target")["result_count"])

    def test_missing_availability_key_never_derives(self):
        # Same shape `_predates_result_columns` (§6.15) keys off -- a row a mapping never touched.
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(target_day, attribution_key="target", result_kind="purchase", result_count=None)
        self.conn.execute(
            "UPDATE ads_external_daily SET availability=availability-'result_count' "
            "WHERE campaign_id=%s AND attribution_key='target'",
            (self.campaign,),
        )
        self.conn.commit()
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, target_day)
        self.assertIsNone(self.row(target_day, "target")["result_count"])

    def test_unknown_spend_never_derives(self):
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(
            target_day, attribution_key="target", result_kind="purchase", result_count=None,
            spend=None, impressions=None,
        )
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, target_day)
        self.assertIsNone(self.row(target_day, "target")["result_count"])

    def test_no_real_activity_never_derives(self):
        # Known spend, but it's zero and there were no impressions either -- nothing actually ran.
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(
            target_day, attribution_key="target", result_kind="purchase", result_count=None,
            spend=0, impressions=0,
        )
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, target_day)
        self.assertIsNone(self.row(target_day, "target")["result_count"])

    def test_todays_incomplete_day_never_derives(self):
        today = settings.today_for_org(self.conn, org_id=self.org)
        demo_day = today - timedelta(days=2)
        self.demonstrate(demo_day)
        self.obs(today, attribution_key="target", result_kind="purchase", result_count=None)
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, today)
        self.assertIsNone(self.row(today, "target")["result_count"])

    def test_day_outside_the_synced_covered_window_never_derives(self):
        demo_day = self.end - timedelta(days=3)
        outside_day = self.end - timedelta(days=2)
        covered_start = self.end - timedelta(days=1)
        self.demonstrate(demo_day)
        self.obs(outside_day, attribution_key="target", result_kind="purchase", result_count=None)
        tracked_zero.apply(
            self.conn, self.org, self.brand, self.campaign, covered_start, self.end
        )
        self.assertIsNone(self.row(outside_day, "target")["result_count"])

    def test_monthly_budget_row_never_derives_even_if_shaped_to_qualify(self):
        demo_day, target_day = self.end - timedelta(days=1), self.end
        self.demonstrate(demo_day)
        self.obs(target_day, attribution_key=MONTHLY_BUDGET_ATTRIBUTION_KEY, spend=50)
        # A real monthly row never carries a result_kind (F16-I06) -- force this shape directly to
        # isolate the attribution_key guard from every other condition, which are all otherwise met.
        self.conn.execute(
            "UPDATE ads_external_daily SET result_kind='purchase' "
            "WHERE campaign_id=%s AND attribution_key=%s",
            (self.campaign, MONTHLY_BUDGET_ATTRIBUTION_KEY),
        )
        self.conn.commit()
        tracked_zero.apply(self.conn, self.org, self.brand, self.campaign, demo_day, target_day)
        self.assertIsNone(self.row(target_day, MONTHLY_BUDGET_ATTRIBUTION_KEY)["result_count"])


if __name__ == "__main__":
    unittest.main()
