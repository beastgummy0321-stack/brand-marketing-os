"""app/tests/test_ads_publish_simulated.py — F03-I10 falsifiers: publishing through
`app/ads/adapters/simulated.py` binds every row (campaign node included) and moves the campaign
to `live`; publishing a campaign that started 5 days ago leaves 5 days of outcome rows without
any further call; no row is dated after today or outside the campaign's range; a second
`generate_outcomes` does not duplicate rows; the same seed gives the same numbers; nothing in
the module writes to `meta_entity_spend`.
"""

import unittest
from datetime import timedelta

import app.shared.web as web
from app.ads import plan
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
        rows = web.conn.execute(
            "SELECT * FROM ads_outcome_daily WHERE campaign_id = %s ORDER BY entity_kind, day",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _meta_entity_spend_count(self) -> int:
        row = web.conn.execute("SELECT COUNT(*) AS n FROM meta_entity_spend").fetchone()
        return row["n"]


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


class FutureStartHasNoOutcomeTest(SimulatedPublishTestBase):
    def test_campaign_starting_in_the_future_publishes_with_no_outcome_rows(self):
        start = self.today + timedelta(days=3)
        end = self.today + timedelta(days=10)
        detail = self._campaign(start_date=start, end_date=end)

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(self._outcome_rows(detail["id"]), [])
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(reloaded["status"], "live")


class GenerateOutcomesIdempotentTest(SimulatedPublishTestBase):
    def test_second_generate_outcomes_does_not_duplicate_rows(self):
        start = self.today - timedelta(days=2)
        detail = self._campaign(start_date=start, end_date=self.today)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"], seed=1)
        first_rows = self._outcome_rows(detail["id"])
        self.assertGreater(len(first_rows), 0)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"], seed=2)
        second_rows = self._outcome_rows(detail["id"])

        self.assertEqual(first_rows, second_rows)


class GenerateOutcomesDeterministicTest(SimulatedPublishTestBase):
    def test_same_seed_gives_the_same_numbers(self):
        start = self.today - timedelta(days=3)
        detail_a = self._campaign(start_date=start, end_date=self.today, groups=1,
                                   ads_per_group=1)
        detail_b = self._campaign(start_date=start, end_date=self.today, groups=1,
                                   ads_per_group=1)

        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail_a["id"], seed=42)
        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail_b["id"], seed=42)

        rows_a = self._outcome_rows(detail_a["id"])
        rows_b = self._outcome_rows(detail_b["id"])
        self.assertEqual(len(rows_a), len(rows_b))
        _skip = ("id", "campaign_id", "created_at", "entity_id")
        stripped_a = [{k: v for k, v in r.items() if k not in _skip} for r in rows_a]
        stripped_b = [{k: v for k, v in r.items() if k not in _skip} for r in rows_b]
        self.assertEqual(stripped_a, stripped_b)


class NoMetaEntitySpendWriteTest(SimulatedPublishTestBase):
    def test_publish_and_generate_outcomes_never_write_meta_entity_spend(self):
        start = self.today - timedelta(days=2)
        detail = self._campaign(start_date=start, end_date=self.today)
        before = self._meta_entity_spend_count()

        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        simulated.generate_outcomes(web.conn, self.org_id, self.brand_id, detail["id"])

        after = self._meta_entity_spend_count()
        self.assertEqual(before, after)


class BindIsIdempotentNoOpTest(SimulatedPublishTestBase):
    def test_bind_returns_the_auto_matched_message_without_writing_new_actions(self):
        detail = self._campaign(start_date=self.today, end_date=self.today)
        simulated.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        actions_before = self._actions(detail["id"])

        result = simulated.bind(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(result["message"], simulated.BOUND_MESSAGE)
        self.assertEqual(self._actions(detail["id"]), actions_before)


class NoGroupsToPublishTest(SimulatedPublishTestBase):
    def test_publish_with_no_groups_refuses(self):
        campaign = self._campaign(groups=0, ads_per_group=0)

        with self.assertRaises(ValueError) as ctx:
            simulated.publish(web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        self.assertEqual(str(ctx.exception), "no_groups_to_publish")


if __name__ == "__main__":
    unittest.main()
