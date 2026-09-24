"""app/tests/test_ads_model.py — F03-I01: the Campaign object exists as rows and can be read
(ARCHITECTURE.md §0/§6). Falsifiers for the shared contract: a campaign with groups and ads
round-trips through `campaign_detail`, brand isolation never leaks a campaign across brands,
`ads_outcome_daily`'s unique key rejects a duplicate (entity, day), an ad has no budget column,
and `budget_total` is derived from group daily budgets while `budget_planned` never changes
underneath it.

Groups/ads/outcomes are written directly by SQL here (no repository write function exists yet
for them in this issue — publish/bind/outcome ingest are later issues); `create_campaign` is the
one write this issue owns.
"""

import unittest

import psycopg

import app.shared.web as web
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core.db import new_id

ACTOR = "測試員"


def _campaign_payload(**overrides) -> dict:
    payload = {
        "name": "測試 Campaign",
        "goal_text": "想在雙十一前把新品衝出去",
        "objective": "衝購買",
        "target_cost": 350,
        "start_date": "2026-11-01",
        "end_date": "2026-11-10",
    }
    payload.update(overrides)
    return payload


class _AdsModelTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]

    def _insert_group(self, campaign_id: str, *, daily_budget: float,
                       channel_key: str = "meta", role: str = "new") -> str:
        group_id = new_id("adg")
        web.conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key,"
            " name, role, daily_budget) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (group_id, self.org_id, self.brand_id, campaign_id, channel_key,
             f"{channel_key} 投放組", role, daily_budget),
        )
        return group_id

    def _insert_ad(self, campaign_id: str, group_id: str, *, name: str = "廣告一號") -> str:
        ad_id = new_id("ada")
        web.conn.execute(
            "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name,"
            " audience_key, format_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (ad_id, self.org_id, self.brand_id, campaign_id, group_id, name,
             "existing_customer", "reels"),
        )
        return ad_id


class CampaignRoundTripTest(_AdsModelTestBase):
    def test_campaign_with_groups_and_ads_round_trips(self):
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        group_id = self._insert_group(campaign["id"], daily_budget=500)
        ad_id = self._insert_ad(campaign["id"], group_id)
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(detail["id"], campaign["id"])
        self.assertEqual(detail["goal_text"], campaign["goal_text"])
        self.assertEqual(len(detail["groups"]), 1)
        self.assertEqual(detail["groups"][0]["id"], group_id)
        self.assertEqual(len(detail["groups"][0]["ads"]), 1)
        self.assertEqual(detail["groups"][0]["ads"][0]["id"], ad_id)
        # 10 天 x 500/日 = 5000
        self.assertEqual(detail["budget_total"], 5000)
        self.assertIsNone(detail["budget_planned"])

    def test_null_cap_round_trips(self):
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id,
            _campaign_payload(target_cost=None), created_by=ACTOR,
        )
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertIsNone(detail["cap"]["own_value"])

    def test_cap_round_trips_as_the_own_cap(self):
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(detail["cap"]["value"], 350)
        self.assertEqual(detail["cap"]["basis"], "own")

    def test_non_numeric_cap_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            ads_repo.create_campaign(
                web.conn, self.org_id, self.brand_id,
                _campaign_payload(target_cost="便宜一點"), created_by=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "target_value_unknown")


class BrandIsolationTest(_AdsModelTestBase):
    def test_campaign_never_crosses_brand(self):
        other_brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌 B：投放中心隔離", client_name=None,
            actor=ACTOR,
        )
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        web.conn.commit()

        own_list = ads_repo.list_campaigns(web.conn, self.org_id, self.brand_id)
        self.assertEqual([c["id"] for c in own_list], [campaign["id"]])

        other_list = ads_repo.list_campaigns(web.conn, self.org_id, other_brand["id"])
        self.assertEqual(other_list, [])

        self.assertIsNone(
            ads_repo.get_campaign(web.conn, self.org_id, other_brand["id"], campaign["id"])
        )


class OutcomeDailyUniqueTest(_AdsModelTestBase):
    def test_duplicate_entity_day_rejected(self):
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        group_id = self._insert_group(campaign["id"], daily_budget=200)
        web.conn.commit()

        def _insert_outcome():
            web.conn.execute(
                "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
                " entity_id, day, spend, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id("ado"), self.org_id, self.brand_id, campaign["id"], "group",
                 group_id, "2026-11-01", 100, "simulated"),
            )

        _insert_outcome()
        web.conn.commit()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            _insert_outcome()
        web.conn.rollback()


class AdHasNoBudgetColumnTest(_AdsModelTestBase):
    def test_ad_table_has_no_budget_column(self):
        row = web.conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = current_schema() AND table_name = 'ads_ad'"
            " AND column_name LIKE %s",
            ("%budget%",),
        ).fetchone()
        self.assertIsNone(row)


class BudgetDerivationTest(_AdsModelTestBase):
    def test_changing_group_daily_budget_changes_derived_total_not_planned(self):
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id,
            _campaign_payload(budget_planned=4000, budget_scenario="recommended"),
            created_by=ACTOR,
        )
        group_id = self._insert_group(campaign["id"], daily_budget=300)
        web.conn.commit()

        first = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(first["budget_total"], 3000)  # 10 天 x 300
        self.assertEqual(first["budget_planned"], 4000)

        web.conn.execute(
            "UPDATE ads_delivery_group SET daily_budget = 600 WHERE id = %s", (group_id,)
        )
        web.conn.commit()

        second = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(second["budget_total"], 6000)  # 10 天 x 600
        # budget_planned is the adopted scenario amount, never recomputed.
        self.assertEqual(second["budget_planned"], 4000)


class NoGroupsMeansNoTotalTest(_AdsModelTestBase):
    def test_no_groups_means_no_total_not_zero(self):
        """A draft Campaign with a start/end date but no adopted delivery group has nothing
        to derive a budget total from — `budget_total` must be `None`, not `0.0` (F04-I21)."""
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertIsNone(detail["budget_total"])

        entries = ads_repo.list_campaigns(web.conn, self.org_id, self.brand_id)
        entry = next(e for e in entries if e["id"] == campaign["id"])
        self.assertIsNone(entry["budget_progress"]["total"])
        self.assertIsNone(entry["budget_progress"]["pct"])


class OutcomeTotalsGroupOnlyTest(_AdsModelTestBase):
    def test_campaign_total_sums_group_rows_only_not_ad_rows(self):
        """`entity_kind = 'ad'` rows exist for per-ad 花費占比 and must never be summed into
        the campaign total — summing both levels double-counts (review fix 1)."""
        campaign = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, _campaign_payload(), created_by=ACTOR,
        )
        group_id = self._insert_group(campaign["id"], daily_budget=200)
        ad_id = self._insert_ad(campaign["id"], group_id)
        web.conn.execute(
            "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
            " entity_id, day, spend, purchases, revenue, source)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("ado"), self.org_id, self.brand_id, campaign["id"], "group",
             group_id, "2026-11-01", 100, 2, 1000, "simulated"),
        )
        web.conn.execute(
            "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
            " entity_id, day, spend, purchases, revenue, source)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("ado"), self.org_id, self.brand_id, campaign["id"], "ad",
             ad_id, "2026-11-01", 40, 1, 400, "simulated"),
        )
        web.conn.commit()

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(detail["outcome"]["spend"], 100)
        self.assertEqual(detail["outcome"]["purchases"], 2)
        self.assertEqual(detail["outcome"]["revenue"], 1000)


if __name__ == "__main__":
    unittest.main()
