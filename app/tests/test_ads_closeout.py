"""app/tests/test_ads_closeout.py — F03-I12 falsifiers, re-cut by F28-I01 (one cap): a campaign
whose cost per result is at or under its cap closes as 達成 with the compared numbers; one over it
closes as 未達成; one with two purchases still closes on the cap (F48-I02: the small sample is
shown, never a verdict switch) and writes a learning at `observed`; no cap closes as 看不出 naming
the missing cap; without
an own cap the cap is break-even from product economics; a second campaign with the same result
kind in the same direction makes the next learning `likely` (another result kind does not count);
closing twice does not write a second learning; an ended campaign at end+7d or end+6d stays open —
there is no unattended auto-close path, close-out is always a person's or an explicit job's call
(`ExpiredActivityRemainsOpenTest`); a learning is never written into `brand_fact` or `rule`
(ruling 15/16).
"""

import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

import app.main as main
from app.ads import closeout, external_repository, jobs, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import interrupts
from app.core import settings as coresettings
from app.shared import web
from app.tests.fixtures.ads_external import outcome_seed

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

    def _campaign(self, *, cap, start_date, end_date, status="live", context=None,
                  covered=True) -> dict:
        """`covered` records a successful platform read over the whole window (F37 Contract Q:
        closeout refuses an unread window, so every verdict case starts honestly covered)."""
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": f"測試 Campaign {cap}", "goal_text": "衝一波", "objective": "購買",
            "target_cost": cap, "context_json": context or {},
            "start_date": start_date, "end_date": end_date, "status": status,
        }, created_by=ACTOR)
        if covered:
            outcome_seed.set_coverage(
                self.conn, self.org_id, self.brand_id, campaign["id"], start_date, end_date,
            )
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
        outcome_seed.seed_day(
            self.conn, self.org_id, self.brand_id, campaign_id, "group", group_id, day,
            spend=spend, impressions=100, clicks=10, purchases=purchases, revenue=revenue,
            source=source,
        )
        self.conn.commit()

    def _three_days(self, campaign: dict, *, spend: float, purchases: int | None,
                    revenue: float | None, source: str = "simulated") -> None:
        start = self.today - timedelta(days=2)
        group = self._group(campaign["id"])
        for offset in range(3):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=spend, purchases=purchases, revenue=revenue, source=source,
            )

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
    def test_cost_per_result_under_the_cap_closes_as_achieved(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["metric"], "cpa")
        self.assertEqual(closed["verdict_json"]["target"], 300)
        self.assertEqual(closed["verdict_json"]["basis"], "own")
        self.assertAlmostEqual(closed["verdict_json"]["actual"], 200.0)  # 3000/15
        self.assertIsNotNone(closed["closed_at"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["confidence"], "observed")
        self.assertIn("每筆成本上限 300", learnings[0]["learning_text"])
        self._facts_and_rules_untouched()

    def test_campaign_read_serves_the_ledger_sentence_after_closeout_only(self):
        """F51 Contract F: `learning_sentence` is the closeout sentence the ledger stored (the
        browser never rebuilds it); null before closeout."""
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)
        client = TestClient(main.app)
        url = f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}"

        before = client.get(url)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertIsNone(before.json()["campaign"]["learning_sentence"])

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        ledger = bi_repo.list_learnings(self.conn, self.brand_id, source_track="ads")

        after = client.get(url).json()["campaign"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(after["learning_sentence"], ledger[0]["learning_text"])


class CloseResolvesTheQueueRowsTest(CloseoutTestBase):
    def test_closing_resolves_every_queue_row_of_the_campaign(self):
        """F49 Contract Q: the closeout row and any row raised before the end leave the inbox
        with the close; another campaign's row stays."""
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        other = self._campaign(cap=200, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)
        day = start.isoformat()
        rows = {
            key: interrupts.enqueue(
                self.conn, org_id=self.org_id, brand_id=self.brand_id, category=category,
                dedupe_key=key, message="待處理",
            )
            for key, category in (
                (f"ads-triage:closeout:{campaign['id']}:{day}", "ads_triage_closeout"),
                (f"ads-triage:cleanup:{campaign['id']}:{day}", "ads_triage_cleanup"),
                (f"ads-triage:cleanup:{other['id']}:{day}", "ads_triage_cleanup"),
            )
        }
        self.conn.commit()

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        still_open = {
            row["dedupe_key"]
            for row in interrupts.list_open(self.conn, org_id=self.org_id, brand_id=self.brand_id,
                                            archive_stale=False)
        }
        self.assertEqual(still_open & set(rows), {f"ads-triage:cleanup:{other['id']}:{day}"})


class MissedTargetClosesUnachievedTest(CloseoutTestBase):
    def test_over_the_cap_closes_as_unachieved(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=2000.0, purchases=5, revenue=1000.0)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")
        self.assertAlmostEqual(closed["verdict_json"]["actual"], 400.0)  # 6000/15


class LowSampleIsShownNeverAVerdictSwitchTest(CloseoutTestBase):
    """F48-I02 (Contract R, decision 1): a small sample is printed beside the verdict, never turned
    into 看不出; it only keeps the learning's confidence at `observed`."""

    def _week(self, *, cap, purchases_per_day):
        start = self.today - timedelta(days=6)
        campaign = self._campaign(cap=cap, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset, purchases in enumerate(purchases_per_day):
            self._outcome_row(campaign["id"], group["id"], start + timedelta(days=offset),
                              spend=300.0, purchases=purchases, revenue=600.0)
        return campaign

    def test_two_purchases_closes_on_the_cap_and_still_writes_a_learning(self):
        campaign = self._campaign(cap=300, start_date=self.today, end_date=self.today)
        group = self._group(campaign["id"])
        self._outcome_row(campaign["id"], group["id"], self.today, spend=200.0, purchases=2,
                           revenue=400.0)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "達成")  # 100 a sale against a cap of 300
        self.assertEqual(closed["verdict_json"]["sample"],
                         {"purchases": 2, "days": 1, "bucket": "低"})
        self.assertEqual(closed["verdict_json"]["sample_bucket"], "低")
        self.assertNotIn("missing", closed["verdict_json"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["confidence"], "observed")
        self.assertIn("結果達成（樣本低）", learnings[0]["learning_text"])
        self.assertEqual(learnings[0]["sample_size"], "低")

    def test_a_seven_day_campaign_with_nine_purchases_closes_met_or_missed(self):
        nine = [2, 1, 1, 1, 2, 1, 1]  # 9 purchases over 7 days, 2,100 spent: 233 a sale
        met = self._week(cap=300, purchases_per_day=nine)
        closed = closeout.close(self.conn, self.org_id, self.brand_id, met["id"], actor=ACTOR)
        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["sample"],
                         {"purchases": 9, "days": 7, "bucket": "低"})

        missed = self._week(cap=200, purchases_per_day=nine)
        closed = closeout.close(self.conn, self.org_id, self.brand_id, missed["id"], actor=ACTOR)
        self.assertEqual(closed["verdict"], "未達成")
        self.assertEqual(closed["verdict_json"]["sample"]["bucket"], "低")

    def test_confidence_stays_observed_below_min_result_events(self):
        # Two campaigns in the same direction, each with 9 purchases: neither counts toward
        # `likely` (the one place sample size moves a level).
        nine = [2, 1, 1, 1, 2, 1, 1]
        for _ in range(2):
            campaign = self._week(cap=300, purchases_per_day=nine)
            closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        confidences = [row["confidence"] for row in bi_repo.list_learnings(
            self.conn, self.brand_id)]
        self.assertEqual(confidences, ["observed", "observed"])
        # A third with 10 purchases is itself enough, but the two thin ones still do not count.
        ten = self._week(cap=300, purchases_per_day=[2, 2, 1, 1, 2, 1, 1])
        closeout.close(self.conn, self.org_id, self.brand_id, ten["id"], actor=ACTOR)
        by_cycle = {row["source_cycle_id"]: row for row in bi_repo.list_learnings(
            self.conn, self.brand_id)}
        self.assertEqual(by_cycle[ten["id"]]["confidence"], "observed")
        again = self._week(cap=300, purchases_per_day=[2, 2, 1, 1, 2, 1, 1])
        closeout.close(self.conn, self.org_id, self.brand_id, again["id"], actor=ACTOR)
        by_cycle = {row["source_cycle_id"]: row for row in bi_repo.list_learnings(
            self.conn, self.brand_id)}
        self.assertEqual(by_cycle[again["id"]]["confidence"], "likely")


class MetaUntrackedPurchasesCloseInconclusiveNamingUntrackedTest(CloseoutTestBase):
    def test_meta_sourced_campaign_closes_inconclusive_naming_untracked_not_low_sample(self):
        start = self.today - timedelta(days=6)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
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
    """F05-I12, re-cut by F28-I01: a `conversion_goal='lead'` brand never prints a hard-coded
    「購買」. The learning sentence names the one metric (每筆成本上限); an untracked metric still
    speaks the brand's own vocabulary (「每筆名單成本」)."""

    def _lead_brand(self):
        bi_repo.set_brand_switches(
            self.conn, self.brand_id, market_region=None, conversion_goal="lead", actor=ACTOR,
        )

    def test_lead_brand_missed_cap_never_prints_purchase(self):
        self._lead_brand()
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=2000.0, purchases=5, revenue=1000.0)

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertIn("每筆成本上限", learnings[0]["learning_text"])
        self.assertNotIn("購買", learnings[0]["learning_text"])

    def test_lead_brand_untracked_metric_names_lead_cost_untracked(self):
        self._lead_brand()
        start = self.today - timedelta(days=6)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        group = self._group(campaign["id"])
        for offset in range(7):
            self._outcome_row(
                campaign["id"], group["id"], start + timedelta(days=offset),
                spend=5000.0, purchases=None, revenue=None, source="meta",
            )

        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "看不出")
        self.assertIn("每筆名單成本未追蹤", closed["verdict_json"]["missing"])


class PurchaseGoalKeepsExistingStringsTest(CloseoutTestBase):
    """品牌沒設 `conversion_goal`（`None`）：學習句印唯一的指標（每筆成本上限）與實際數字。"""

    def test_default_brand_prints_the_cap_sentence(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=2000.0, purchases=5, revenue=1000.0)

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertIn("每筆成本上限 300，實際 400", learnings[0]["learning_text"])


class SecondCampaignSameDirectionUpgradesLearningTest(CloseoutTestBase):
    def _achieved_campaign(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)
        return campaign

    def test_second_campaign_in_the_same_direction_makes_the_next_learning_likely(self):
        first = self._achieved_campaign()
        closeout.close(self.conn, self.org_id, self.brand_id, first["id"], actor=ACTOR)
        second = self._achieved_campaign()
        closeout.close(self.conn, self.org_id, self.brand_id, second["id"], actor=ACTOR)

        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 2)
        by_cycle = {row["source_cycle_id"]: row for row in learnings}
        self.assertEqual(by_cycle[first["id"]]["confidence"], "observed")
        self.assertEqual(by_cycle[second["id"]]["confidence"], "likely")

    def test_same_verdict_with_another_result_kind_is_another_cohort(self):
        # F28-I01: the cohort is same brand + same result kind + same verdict.
        first = self._achieved_campaign()
        ads_repo.save_campaign_target(
            self.conn, self.org_id, self.brand_id, first["id"],
            result_kind="lead", expected_revision=0, actor=ACTOR,
        )
        closeout.close(self.conn, self.org_id, self.brand_id, first["id"], actor=ACTOR)
        second = self._achieved_campaign()
        closeout.close(self.conn, self.org_id, self.brand_id, second["id"], actor=ACTOR)

        by_cycle = {
            row["source_cycle_id"]: row
            for row in bi_repo.list_learnings(self.conn, self.brand_id)
        }
        self.assertEqual(by_cycle[second["id"]]["confidence"], "observed")


class ClosingTwiceDoesNotDuplicateLearningTest(CloseoutTestBase):
    def test_closing_twice_writes_only_one_learning(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)

        first = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        second = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(first["verdict"], second["verdict"])
        self.assertEqual(first["closed_at"], second["closed_at"])
        learnings = bi_repo.list_learnings(self.conn, self.brand_id)
        self.assertEqual(len(learnings), 1)


class CloseResolvesRuntimeAlertsTest(CloseoutTestBase):
    """F49 Contract N: a closed campaign is no longer monitored -- closing it leaves none of its
    runtime alerts open (old dated keys included); another campaign's stay."""

    def _open_runtime_keys(self) -> set[str]:
        return {
            row["dedupe_key"] for row in interrupts.list_open(
                self.conn, org_id=self.org_id, brand_id=self.brand_id,
                category="ads_runtime_attention",
                archive_stale=False,
            )
        }

    def test_close_resolves_the_campaigns_open_runtime_rows(self):
        start = self.today - timedelta(days=2)
        campaign = self._campaign(cap=300, start_date=start, end_date=self.today)
        other = self._campaign(cap=300, start_date=start, end_date=self.today)
        self._three_days(campaign, spend=1000.0, purchases=5, revenue=2500.0)
        keys = [
            f"ads-runtime:{campaign['id']}:budget_unknown",
            f"ads-runtime:{campaign['id']}:{self.today}:plan_date_passed",
            f"ads-runtime:{other['id']}:budget_unknown",
        ]
        for key in keys:
            interrupts.enqueue(
                self.conn, org_id=self.org_id, brand_id=self.brand_id,
                category="ads_runtime_attention", dedupe_key=key,
                message="廣告追蹤有待確認項目，請檢視",
            )
        self.conn.commit()

        closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

        self.assertEqual(self._open_runtime_keys(), {keys[2]})


class CapResolutionTest(CloseoutTestBase):
    """F28-I01: close-out reads the one resolved cap (`targets.resolve`) -- the own cap wherever
    it was set, else break-even from product economics, else 看不出."""

    def _close(self, campaign):
        self._three_days(campaign, spend=2000.0, purchases=5, revenue=1000.0)  # 400 each
        return closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)

    def test_no_own_cap_judges_against_break_even(self):
        product_id = bi_repo.create_product(
            self.conn, self.brand_id, name="測試商品", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            self.conn, self.brand_id, product_id, selling_price=1000, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=450, shipping_cost=50,
        )
        self.conn.commit()
        campaign = self._campaign(
            cap=None, start_date=self.today - timedelta(days=2), end_date=self.today,
            context={"product_ids": [product_id]},
        )
        closed = self._close(campaign)
        self.assertEqual(closed["verdict_json"]["basis"], "break_even")
        self.assertEqual(closed["verdict_json"]["target"], 500)  # 1000 - 450 - 50
        self.assertEqual(closed["verdict"], "達成")  # 400 <= 500
        # F48 Contract W: the period verdict is stored with the campaign's sell-way.
        verdicts = [row for row in bi_repo.list_learnings(self.conn, self.brand_id)
                    if row["source_cycle_id"] == campaign["id"]]
        self.assertEqual([row["product_id"] for row in verdicts], [product_id])

    def test_cap_set_on_the_target_route_is_the_one_judged(self):
        campaign = self._campaign(
            cap=None, start_date=self.today - timedelta(days=2), end_date=self.today,
        )
        ads_repo.save_campaign_target(
            self.conn, self.org_id, self.brand_id, campaign["id"],
            basis="own", value=350, expected_revision=0, actor=ACTOR,
        )
        closed = self._close(campaign)
        self.assertEqual(closed["verdict_json"]["target"], 350)
        self.assertEqual(closed["verdict"], "未達成")  # 400 > 350

    def test_no_cap_at_all_is_inconclusive_naming_the_cap(self):
        campaign = self._campaign(
            cap=None, start_date=self.today - timedelta(days=2), end_date=self.today,
        )
        closed = self._close(campaign)
        self.assertEqual(closed["verdict"], "看不出")
        self.assertIsNone(closed["verdict_json"]["target"])
        self.assertIn("上限沒有設定", closed["verdict_json"]["missing"])


class CoverageGateTest(CloseoutTestBase):
    """F37 Contract Q (ruling 3): closeout refuses a window the platform read does not cover and
    names the days; the skip opens only after the last read ended `error` (or for an isolated
    simulation recovery, whose only read is the user typing days in) and then closes 看不出."""

    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)

    def _gapped(self) -> dict:
        """Five-day window (today-5 … today-1, all complete) read only for its last three days,
        which carry 30 purchases at 100 each -- 達成 against 300 if the gap were ignored."""
        start = self.today - timedelta(days=5)
        campaign = self._campaign(
            cap=300, start_date=start, end_date=self.today - timedelta(days=1), covered=False,
        )
        outcome_seed.set_coverage(
            self.conn, self.org_id, self.brand_id, campaign["id"],
            start + timedelta(days=2), self.today - timedelta(days=1),
        )
        group = self._group(campaign["id"])
        for offset in range(2, 5):
            self._outcome_row(campaign["id"], group["id"], start + timedelta(days=offset),
                              spend=1000.0, purchases=10, revenue=5000.0)
        self.conn.commit()
        return campaign

    def _read_failed(self, campaign_id: str) -> None:
        external_repository.record_sync(
            self.conn, self.org_id, self.brand_id, campaign_id, section="observations",
            state={"status": "error", "error": "平台逾時"},
        )
        self.conn.commit()

    def _close_route(self, campaign_id: str, **body):
        return self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/close", json=body,
        )

    def _learning_count(self) -> int:
        return len(bi_repo.list_learnings(self.conn, self.brand_id))

    def _unread(self) -> list[str]:
        start = self.today - timedelta(days=5)
        return [start.isoformat(), (start + timedelta(days=1)).isoformat()]

    def test_gap_without_a_failed_read_is_409_naming_the_days_and_writes_nothing(self):
        campaign = self._gapped()
        resp = self._close_route(campaign["id"])
        self.assertEqual(resp.status_code, 409, resp.text)
        error = resp.json()["error"]
        self.assertEqual(error["code"], "coverage_missing")
        self.assertIn("有 2 天還沒讀到平台資料", error["message"])
        self.assertEqual(error["details"], {
            "missing_days": self._unread(), "never_synced": False, "can_skip": False,
        })
        # An explicit skip without a failed read is refused the same way.
        resp = self._close_route(campaign["id"], skip_missing=True)
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertFalse(resp.json()["error"]["details"]["can_skip"])
        row = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(row["status"], "live")
        self.assertEqual(self._learning_count(), 0)

    def test_never_synced_is_refused_as_never_read_not_a_wall_of_dates(self):
        campaign = self._campaign(
            cap=300, start_date=self.today - timedelta(days=5),
            end_date=self.today - timedelta(days=1), covered=False,
        )
        resp = self._close_route(campaign["id"])
        self.assertEqual(resp.status_code, 409, resp.text)
        error = resp.json()["error"]
        self.assertIn("還沒讀過平台資料", error["message"])
        self.assertEqual(error["details"],
                         {"missing_days": [], "never_synced": True, "can_skip": False})
        self.assertEqual(self._learning_count(), 0)

    def test_after_a_failed_read_the_explicit_skip_closes_inconclusive_with_the_days(self):
        campaign = self._gapped()
        self._read_failed(campaign["id"])
        resp = self._close_route(campaign["id"])
        self.assertEqual(resp.status_code, 409, resp.text)  # never a default skip
        self.assertTrue(resp.json()["error"]["details"]["can_skip"])

        resp = self._close_route(campaign["id"], skip_missing=True)
        self.assertEqual(resp.status_code, 200, resp.text)
        closed = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["verdict"], "看不出")
        days = self._unread()
        self.assertEqual(closed["verdict_json"]["missing_days"], days)
        listed = "、".join(
            f"{day[5:7]}/{day[8:10]}" for day in days
        )
        self.assertEqual(closed["verdict_json"]["missing"], f"有 2 天沒讀到平台資料：{listed}")
        self.assertEqual(self._learning_count(), 1)

    def test_fully_covered_window_judges_as_before(self):
        campaign = self._gapped()
        outcome_seed.set_coverage(
            self.conn, self.org_id, self.brand_id, campaign["id"],
            self.today - timedelta(days=5), self.today - timedelta(days=1),
        )
        self.conn.commit()
        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        self.assertEqual(closed["verdict"], "達成")
        self.assertNotIn("missing_days", closed["verdict_json"])

    def test_recovery_campaign_with_no_saved_day_may_skip_and_keeps_the_receipts_rule(self):
        """Lead decision 2026-09-29: a recovery campaign has no platform to re-read, so its skip
        is open whenever the gap is non-empty; the receipts rule still makes it 看不出."""
        campaign = self._campaign(
            cap=300, start_date=self.today - timedelta(days=3),
            end_date=self.today - timedelta(days=1), covered=False,
            context={"simulation_recovery": {"days": {}}},
        )
        with self.assertRaises(closeout.CoverageMissing) as caught:
            closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        self.assertEqual(caught.exception.payload,
                         {"missing_days": [], "never_synced": True, "can_skip": True})
        closed = closeout.close(self.conn, self.org_id, self.brand_id, campaign["id"],
                                actor=ACTOR, skip_missing=True)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["verdict"], "看不出")
        self.assertEqual(closed["verdict_json"]["missing"],
                         "模擬回收尚有缺日或缺廣告，不把缺資料視為零。")
        self.assertEqual(closed["verdict_json"]["missing_days"], [])


class ExpiredActivityRemainsOpenTest(CloseoutTestBase):
    def test_expiry_never_closes_activity_at_seven_or_six_days(self):
        expired = self._campaign(
            cap=None, start_date=self.today - timedelta(days=14),
            end_date=self.today - timedelta(days=7), status="live",
        )
        not_yet = self._campaign(
            cap=None, start_date=self.today - timedelta(days=13),
            end_date=self.today - timedelta(days=6), status="live",
        )

        jobs.close_expired_campaigns(self.org_id)

        closed = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, expired["id"])
        still_live = ads_repo.get_campaign(self.conn, self.org_id, self.brand_id, not_yet["id"])
        self.assertEqual(closed["status"], "live")
        self.assertEqual(still_live["status"], "live")


if __name__ == "__main__":
    unittest.main()
