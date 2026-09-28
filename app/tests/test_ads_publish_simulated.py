"""app/tests/test_ads_publish_simulated.py — F03-I10 / F37 Contract R falsifiers: publishing
through `app/ads/adapters/simulated.py` registers the campaign → adset → ad chain on the
simulated platform, binds every row (campaign node included) to it and moves the campaign to
`live`; publishing a campaign that started 5 days ago leaves 5 days of platform observations and
a recorded read range without any further call; no row is dated after today or outside the
campaign's range; a second `generate_outcomes` does not duplicate rows; the same seed gives the
same numbers; nothing in the module writes to `meta_entity_spend`.
"""

import random
import unittest
from datetime import timedelta

import app.shared.web as web
from app.ads import outcome, plan
from app.ads import repository as ads_repo
from app.ads.adapters import simulated
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings

ACTOR = "測試員"

_COORDINATES = {
    "audience": "aud", "pain": "pain", "angle": "angle", "hook": "hook", "proof": "proof",
    "offer": "offer", "format": "format",
}


class SimulatedPublishTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：模擬發布", client_name=None, actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.today = coresettings.today_for_org(web.conn, org_id=self.org_id)

    def _campaign(self, *, start_date=None, end_date=None, groups: int = 2,
                  ads_per_group: int = 2) -> dict:
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "測試 Campaign", "goal_text": "測試模擬發布", "objective": "購買",
            "target_cost": 300,
            "start_date": start_date, "end_date": end_date, "status": "draft",
        }, created_by=ACTOR)
        for g in range(groups):
            group = plan.create_group(
                web.conn, self.org_id, self.brand_id, campaign["id"], name=f"投放組{g}",
                role="new", daily_budget=500,
            )
            for a in range(ads_per_group):
                plan.create_ad(
                    web.conn, self.org_id, self.brand_id, campaign["id"], group["id"],
                    name=f"廣告{g}-{a}", coordinates=_COORDINATES,
                )
        row = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign["id"])
        assert row is not None
        return row

    def _actions(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_action WHERE campaign_id = %s ORDER BY created_at", (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _outcome_rows(self, campaign_id: str) -> list:
        """Contract P rows of both grains, tagged with their grain."""
        return [
            {"entity_kind": kind, **row}
            for kind in ("ad", "group")
            for row in outcome.rows(web.conn, self.org_id, self.brand_id, campaign_id, kind)
        ]

    def _daily(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_external_daily WHERE campaign_id = %s ORDER BY day, metric_scope,"
            " entity_id", (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _entities(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_external_entity WHERE campaign_id = %s ORDER BY native_kind,"
            " native_id", (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _coverage(self, campaign_id: str) -> dict | None:
        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        sync = (campaign.get("context_json") or {}).get("external_sync") or {}
        return (sync.get("observations") or {}).get("coverage")

    def _meta_entity_spend_count(self) -> int:
        row = web.conn.execute("SELECT COUNT(*) AS n FROM meta_entity_spend").fetchone()
        return row["n"]

    def _published_later(self, start):
        """A campaign published while it still lay in the future (nothing generated), then moved
        to start at `start` -- so `generate_outcomes(seed=…)` alone decides its numbers."""
        detail = self._campaign(start_date=self.today + timedelta(days=5),
                                end_date=self.today + timedelta(days=9), groups=1,
                                ads_per_group=1)
        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        web.conn.execute(
            "UPDATE ads_campaign SET start_date = %s, end_date = %s WHERE id = %s",
            (start, self.today, detail["id"]),
        )
        return detail


class PublishBindsEveryRowTest(SimulatedPublishTestBase):
    def test_publish_binds_every_row_and_goes_live(self):
        detail = self._campaign(start_date=self.today, end_date=self.today)

        result = simulated.publish(
            web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
        )

        self.assertEqual(result, {"ok": True})
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(reloaded["status"], "live")
        self.assertEqual(reloaded["local_state"], "bound")
        self.assertIsNotNone(reloaded["external_id"])
        for group in reloaded["groups"]:
            self.assertEqual(group["local_state"], "bound")
            self.assertIsNotNone(group["external_id"])
            for ad in group["ads"]:
                self.assertEqual(ad["local_state"], "bound")
                self.assertIsNotNone(ad["external_id"])

        publish_actions = [a for a in self._actions(detail["id"]) if a["kind"] == "publish"]
        # campaign 節點 + 2 個投放組 + 4 支廣告 = 7 列
        self.assertEqual(len(publish_actions), 7)
        self.assertEqual(len({a["target_id"] for a in publish_actions}), 7)
        for action in publish_actions:
            self.assertEqual(action["sync_state"], "auto_synced")
            self.assertIsNotNone(action["platform_ref"])


class PublishRegistersThePlatformChainTest(SimulatedPublishTestBase):
    def test_every_local_node_has_its_simulated_entity_with_the_parent_chain(self):
        detail = self._campaign(start_date=self.today, end_date=self.today)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        entities = {(e["native_kind"], e["native_id"]): e for e in self._entities(detail["id"])}
        self.assertEqual(len(entities), 7)
        for entity in entities.values():
            self.assertEqual(entity["platform"], "simulated")
            self.assertEqual(entity["source_account"], "sim")
            self.assertEqual(entity["native_status"], "ACTIVE")
        campaign_entity = entities[("campaign", reloaded["external_id"])]
        self.assertIsNone(campaign_entity["parent_native_id"])
        self.assertEqual(campaign_entity["name"], reloaded["name"])
        for group in reloaded["groups"]:
            adset = entities[("adset", group["external_id"])]
            self.assertEqual((adset["parent_native_kind"], adset["parent_native_id"]),
                             ("campaign", reloaded["external_id"]))
            self.assertEqual(adset["budget_type"], "daily")
            self.assertEqual(float(adset["budget_amount"]), float(group["daily_budget"]))
            for ad in group["ads"]:
                entity = entities[("ad", ad["external_id"])]
                self.assertEqual((entity["parent_native_kind"], entity["parent_native_id"]),
                                 ("adset", group["external_id"]))


class PublishFillsOutcomeWithoutFurtherCallTest(SimulatedPublishTestBase):
    def test_campaign_started_5_days_ago_leaves_5_days_of_outcome_rows(self):
        start = self.today - timedelta(days=4)
        detail = self._campaign(start_date=start, end_date=self.today)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        rows = self._outcome_rows(detail["id"])
        group_days = {r["day"] for r in rows if r["entity_kind"] == "group"}
        self.assertEqual(len(group_days), 5)
        for day in group_days:
            self.assertGreaterEqual(day, start)
            self.assertLessEqual(day, self.today)
        for row in rows:
            self.assertLessEqual(row["day"], self.today)
            self.assertGreaterEqual(row["day"], start)

    def test_observations_are_platform_rows_with_real_numbers_and_a_recorded_range(self):
        start = self.today - timedelta(days=4)
        detail = self._campaign(start_date=start, end_date=self.today)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        daily = self._daily(detail["id"])
        self.assertTrue(daily)
        self.assertEqual({r["metric_scope"] for r in daily}, {"adset", "ad"})
        for row in daily:
            self.assertEqual(row["attribution_key"], "simulated")
            self.assertEqual(row["source"], "simulated")
            self.assertEqual(row["currency"], "TWD")
            self.assertIsNotNone(row["purchases"])
            self.assertIsNotNone(row["revenue"])
        # 2 groups x 5 days, every group row reaches its local group.
        self.assertEqual(len([r for r in daily if r["metric_scope"] == "adset"]), 10)
        self.assertEqual(
            len([r for r in self._outcome_rows(detail["id"]) if r["entity_kind"] == "group"]), 10,
        )
        self.assertEqual(self._coverage(detail["id"]),
                         {"start": start.isoformat(), "end": self.today.isoformat()})
        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, detail["id"])
        observations = campaign["context_json"]["external_sync"]["observations"]
        self.assertEqual(observations["status"], "success")


class FutureStartHasNoOutcomeTest(SimulatedPublishTestBase):
    def test_campaign_starting_in_the_future_publishes_with_no_outcome_rows(self):
        start = self.today + timedelta(days=3)
        end = self.today + timedelta(days=10)
        detail = self._campaign(start_date=start, end_date=end)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(self._outcome_rows(detail["id"]), [])
        self.assertEqual(self._daily(detail["id"]), [])
        self.assertIsNone(self._coverage(detail["id"]))
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(reloaded["status"], "live")


class GenerateOutcomesIdempotentTest(SimulatedPublishTestBase):
    def test_second_generate_outcomes_does_not_duplicate_rows(self):
        start = self.today - timedelta(days=2)
        detail = self._campaign(start_date=start, end_date=self.today)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        first_rows = self._daily(detail["id"])
        self.assertGreater(len(first_rows), 0)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"], seed=2)
        second_rows = self._daily(detail["id"])

        self.assertEqual(first_rows, second_rows)

    def test_a_new_day_extends_the_recorded_range(self):
        start = self.today - timedelta(days=2)
        detail = self._campaign(start_date=start, end_date=self.today)
        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        web.conn.execute(
            "UPDATE ads_campaign SET start_date = %s WHERE id = %s",
            (start - timedelta(days=1), detail["id"]),
        )

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"], seed=3)

        self.assertEqual(self._coverage(detail["id"]),
                         {"start": (start - timedelta(days=1)).isoformat(),
                          "end": self.today.isoformat()})
        group_days = {r["day"] for r in self._outcome_rows(detail["id"])
                      if r["entity_kind"] == "group"}
        self.assertEqual(len(group_days), 4)


class NoChainIsNeverMarkedReadTest(SimulatedPublishTestBase):
    def test_generate_without_a_simulated_chain_records_no_coverage(self):
        detail = self._campaign(start_date=self.today - timedelta(days=2), end_date=self.today)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"], seed=1)

        self.assertEqual(self._daily(detail["id"]), [])
        self.assertIsNone(self._coverage(detail["id"]))


class GenerateOutcomesDeterministicTest(SimulatedPublishTestBase):
    def test_same_seed_gives_the_same_numbers(self):
        start = self.today - timedelta(days=3)
        detail_a = self._published_later(start)
        detail_b = self._published_later(start)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail_a["id"], seed=42)
        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail_b["id"], seed=42)

        rows_a = self._outcome_rows(detail_a["id"])
        rows_b = self._outcome_rows(detail_b["id"])
        self.assertTrue(rows_a)
        self.assertEqual(len(rows_a), len(rows_b))
        _skip = ("entity_id", "observed_at")
        stripped_a = [{k: v for k, v in r.items() if k not in _skip} for r in rows_a]
        stripped_b = [{k: v for k, v in r.items() if k not in _skip} for r in rows_b]
        self.assertEqual(stripped_a, stripped_b)

    def test_day_rows_is_pure(self):
        detail = self._campaign(start_date=self.today, end_date=self.today)
        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        bound = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])

        first = simulated.day_rows(bound, self.today, random.Random(7))
        second = simulated.day_rows(bound, self.today, random.Random(7))

        self.assertEqual(first, second)
        self.assertEqual(len([r for r in first if r["native_kind"] == "adset"]), 2)
        natives = {g["external_id"] for g in bound["groups"]} | {
            a["external_id"] for g in bound["groups"] for a in g["ads"]
        }
        self.assertTrue({r["native_id"] for r in first} <= natives)


class NoMetaEntitySpendWriteTest(SimulatedPublishTestBase):
    def test_publish_and_generate_outcomes_never_write_meta_entity_spend(self):
        start = self.today - timedelta(days=2)
        detail = self._campaign(start_date=start, end_date=self.today)
        before = self._meta_entity_spend_count()

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"])

        after = self._meta_entity_spend_count()
        self.assertEqual(before, after)


class NoGroupsToPublishTest(SimulatedPublishTestBase):
    def test_publish_with_no_groups_refuses(self):
        campaign = self._campaign(groups=0, ads_per_group=0)

        with self.assertRaises(ValueError) as ctx:
            simulated.publish(web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        self.assertEqual(str(ctx.exception), "no_groups_to_publish")


if __name__ == "__main__":
    unittest.main()
