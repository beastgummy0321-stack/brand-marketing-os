"""app/tests/test_ads_closeout.py — F03-I12 falsifiers: a campaign that beat its ROAS target
closes as 達成 with the compared numbers; one that missed it closes as 未達成; one with two
purchases closes as 看不出 and still writes a learning (at `observed`, text names the small
sample); a second campaign in the same direction makes the next learning `likely`; closing
twice does not write a second learning; an ended campaign at end+7d or end+6d stays open — there is
no unattended auto-close path, close-out is always a person's or an explicit job's call
(`ExpiredActivityRemainsOpenTest`); a learning is never written into `brand_fact` or `rule`
(ruling 15/16).
"""

import unittest
from datetime import timedelta

from app.ads import closeout, jobs, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.shared import web

ACTOR = "測試員"


class CloseoutTestBase(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：投放中心結案", client_name=None,
            actor=ACTOR,
        )["id"]
        self.today = coresettings.today_for_org(self.conn, org_id=self.org_id)
        self.conn.commit()

    def _campaign(self, *, metric: str, target, start_date, end_date, status="live") -> dict:
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": f"測試 Campaign {metric}-{target}", "goal_text": "衝一波", "objective": "購買",
            "success_metric": metric, "success_target": target,
            "start_date": start_date, "end_date": end_date, "status": status,
        }, created_by=ACTOR)
        self.conn.commit()
        return campaign

    def _group(self, campaign_id: str) -> dict:
        return plan.create_group(
            self.conn, self.org_id, self.brand_id, campaign_id, name="投放組", role="new",
            daily_budget=500,
        )

    def _outcome_row(self, campaign_id: str, group_id: str, day, *, spend: float,
                      purchases: int | None, revenue: float | None,
                      source: str = "simulated") -> None:
        self.conn.execute(
            "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
            " entity_id, day, spend, impressions, clicks, purchases, revenue, source)"
            " VALUES (%s, %s, %s, %s, 'group', %s, %s, %s, 100, 10, %s, %s, %s)",
            (coredb.new_id("ado"), self.org_id, self.brand_id, campaign_id, group_id, day,
             spend, purchases, revenue, source),
        )
        self.conn.commit()

    def _facts_and_rules_untouched(self) -> None:
        facts = self.conn.execute(
            "SELECT COUNT(*) AS n FROM brand_fact WHERE brand_id = %s", (self.brand_id,),
        ).fetchone()
        rules = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule WHERE brand_id = %s", (self.brand_id,),
        ).fetchone()
        self.assertEqual(facts["n"], 0)
        self.assertEqual(rules["n"], 0)


class BeatTargetClosesAchievedTest(CloseoutTestBase):
    def test_beats_roas_target_closes_as_achieved(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(metric="roas", target=2.0, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=1000.0, purchases=5, revenue=2500.0,
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["metric"], "roas")
        self.assertEqual(closed["verdict_json"]["target"], 2.0)
        self.assertAlmostEqual(closed["verdict_json"]["actual"], 2.5)
        self.assertIsNotNone(closed["closed_at"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["confidence"], "observed")
        self._facts_and_rules_untouched()


class MissedTargetClosesUnachievedTest(CloseoutTestBase):
    def test_missed_cpa_target_closes_as_unachieved(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(metric="cpa", target=300, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=2000.0, purchases=5, revenue=1000.0,
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")
        self.assertAlmostEqual(closed["verdict_json"]["actual"], 400.0)  # 6000/15


class LowSampleClosesInconclusiveButStillLearnsTest(CloseoutTestBase):
    def test_two_purchases_closes_as_inconclusive_and_still_writes_a_learning(self):
        campaign = self._campaign(
            metric="cpa", target=300, start_date=self.today, end_date=self.today,
        )
        group = self._group(campaign["id"])
        self._outcome_row(campaign["id"], group["id"], self.today, spend=200.0, purchases=2,
                           revenue=400.0)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "看不出")
        self.assertEqual(closed["verdict_json"]["sample_bucket"], "低")
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["confidence"], "observed")
        self.assertIn("樣本太小", learnings[0]["learning_text"])


class MetaUntrackedPurchasesCloseInconclusiveNamingUntrackedTest(CloseoutTestBase):
    def test_meta_sourced_campaign_closes_inconclusive_naming_untracked_not_low_sample(self):
        start = self.today - timedelta(days=6)
        campaign = self._campaign(
            metric="purchases", target=50, start_date=start, end_date=self.today,
        )
        group = self._group(campaign["id"])
        for offset in range(7):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=5000.0, purchases=None, revenue=None, source="meta",
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "看不出")
        self.assertIsNone(closed["verdict_json"]["actual"])
        self.assertIn("未追蹤", closed["verdict_json"]["missing"])
        self.assertNotIn("樣本太小", closed["verdict_json"]["missing"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)
        self.assertIn("未追蹤", learnings[0]["learning_text"])
        self.assertNotIn("樣本太小", learnings[0]["learning_text"])


class LeadGoalPrintsLeadLabelsTest(CloseoutTestBase):
    """F05-I12：`conversion_goal='lead'` 的品牌結案要印「每筆名單成本」／「名單數」，不是
    寫死的「購買」——換的只是 label，`_judge` 的算式一個字沒動。"""

    def test_lead_brand_missed_cpa_target_prints_lead_labels(self):
        bi_repo.set_brand_switches(
            self.conn, self.brand_id, market_region=None, conversion_goal="lead", actor=ACTOR,
        )
        start = self.today - timedelta(days=2)
        campaign = self._campaign(metric="cpa", target=300, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=2000.0, purchases=5, revenue=1000.0,
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertIn("每筆名單成本", learnings[0]["learning_text"])
        self.assertNotIn("購買", learnings[0]["learning_text"])

    def test_lead_brand_untracked_metric_names_lead_count_untracked(self):
        bi_repo.set_brand_switches(
            self.conn, self.brand_id, market_region=None, conversion_goal="lead", actor=ACTOR,
        )
        start = self.today - timedelta(days=6)
        campaign = self._campaign(
            metric="purchases", target=50, start_date=start, end_date=self.today,
        )
        group = self._group(campaign["id"])
        for offset in range(7):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=5000.0, purchases=None, revenue=None, source="meta",
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "看不出")
        self.assertIn("名單數未追蹤", closed["verdict_json"]["missing"])


class PurchaseGoalKeepsExistingStringsTest(CloseoutTestBase):
    """既有斷言不准改壞（Done 5）：品牌沒設 `conversion_goal`（`None`）維持原本的購買字串。"""

    def test_default_brand_still_prints_purchase_labels(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(metric="cpa", target=300, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=2000.0, purchases=5, revenue=1000.0,
            )

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertIn("每次購買成本", learnings[0]["learning_text"])


class SecondCampaignSameDirectionUpgradesLearningTest(CloseoutTestBase):
    def test_second_campaign_in_the_same_direction_makes_the_next_learning_likely(self):
        def _achieved_campaign():
            start = self.today - timedelta(days=2)
            campaign = self._campaign(
                metric="roas", target=1.5, start_date=start, end_date=self.today,
            )
            group = self._group(campaign["id"])
            for offset in range(3):
                self._outcome_row(
                    campaign["id"], group["id"], start + timedelta(days=offset),
                    spend=1000.0, purchases=5, revenue=2500.0,
                )
            return campaign

        first = _achieved_campaign()
        closeout.close(self.conn, self.org_id, self.brand_id, first["id"], actor=ACTOR)
        second = _achieved_campaign()
        closeout.close(self.conn, self.org_id, self.brand_id, second["id"], actor=ACTOR)

        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 2)
        by_cycle = {row["source_cycle_id"]: row for row in learnings}
        self.assertEqual(by_cycle[first["id"]]["confidence"], "observed")
        self.assertEqual(by_cycle[second["id"]]["confidence"], "likely")


class ClosingTwiceDoesNotDuplicateLearningTest(CloseoutTestBase):
    def test_closing_twice_writes_only_one_learning(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(metric="roas", target=2.0, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=1000.0, purchases=5, revenue=2500.0,
            )

        first = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        second = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(first["verdict"], second["verdict"])
        self.assertEqual(first["closed_at"], second["closed_at"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)


class TargetPutDoesNotChangeCloseoutVerdictTest(CloseoutTestBase):
    """F16-I04 repair regression: `PUT .../target` writes only `target_cost`/`target_basis`/
    `result_kind`/`target_revision` -- never `success_metric`/`success_target`/`success_basis`,
    the three fields `_judge()` actually reads. A campaign that gets a `PUT` between its outcome
    landing and its close-out must reach the exact same verdict as an identical campaign that
    never got one."""

    def test_put_target_before_close_gives_the_same_verdict(self):
        start = self.today - timedelta(days=2)

        def _cpa_campaign_with_outcome():
            campaign = self._campaign(metric="cpa", target=300, start_date=start,
                                       end_date=self.today)
            group = self._group(campaign["id"])
            for offset in range(3):
                self._outcome_row(
                    campaign["id"], group["id"], start + timedelta(days=offset),
                    spend=2000.0, purchases=5, revenue=1000.0,
                )
            return campaign

        untouched = _cpa_campaign_with_outcome()
        put_first = _cpa_campaign_with_outcome()
        ads_repo.save_campaign_target(
            self.conn, self.org_id, self.brand_id, put_first["id"],
            basis="own", value=999, expected_revision=0, actor=ACTOR,
        )

        closed_untouched = closeout.close(
            self.conn, self.org_id, self.brand_id, untouched["id"], actor=ACTOR,
        )
        closed_put = closeout.close(
            self.conn, self.org_id, self.brand_id, put_first["id"], actor=ACTOR,
        )

        self.assertEqual(closed_untouched["verdict"], closed_put["verdict"])
        self.assertEqual(
            closed_untouched["verdict_json"]["actual"], closed_put["verdict_json"]["actual"],
        )
        self.assertEqual(closed_untouched["verdict_json"]["target"], 300)
        self.assertEqual(closed_put["verdict_json"]["target"], 300)  # 未被 own 覆寫值 999 動到


class ExpiredActivityRemainsOpenTest(CloseoutTestBase):
    def test_expiry_never_closes_activity_at_seven_or_six_days(self):
        expired = self._campaign(
            metric="purchases", target=None, start_date=self.today - timedelta(days=14),
            end_date=self.today - timedelta(days=7), status="live",
        )
        not_yet = self._campaign(
            metric="purchases", target=None, start_date=self.today - timedelta(days=13),
            end_date=self.today - timedelta(days=6), status="live",
        )

        jobs.close_expired_campaigns(self.org_id)

        closed = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, expired["id"])
        still_live = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, not_yet["id"])
        self.assertEqual(closed["status"], "live")
        self.assertEqual(still_live["status"], "live")


if __name__ == "__main__":
    unittest.main()
