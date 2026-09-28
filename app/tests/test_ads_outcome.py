"""app/tests/test_ads_outcome.py — the performance tab of an internal campaign reads the one
pipeline (F37 Contract P): platform rows (`ads_external_daily`) of the entities its local nodes
are bound to. Falsifiers: a day with no data returns nothing (never a fabricated 0) and the
totals read as 未追蹤 (`None`) rather than 0; the two ROAS bases; tracked zero vs untracked; a
local node with no platform id and monthly budget rows never reach the numbers; coverage names
the unread days and says never-synced; the sample bucket boundaries (9/10, 49/50, 2 days/3 days)
are exact; the retired manual ingest endpoint is gone; real purchases reach closeout.
"""

import unittest
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import external_repository, outcome, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.llm import providers
from app.tests.fixtures.ads_external import outcome_seed

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


_VALID_PLAN_REPLY = (
    '{"groups": [{"role": "new", "name": "新客組", "ads": '
    '[{"name": "新客-廣告一", "coordinates": '
    '{"audience": "a", "pain": "p", "angle": "an", "hook": "h", "proof": "pr", "offer": "o",'
    ' "format": "f"}}]}]}'
)


class OutcomeTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心成效", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        self._orig_provider = plan.PROVIDER
        web.conn.commit()

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _bound_campaign(self, *, start_date=None, end_date=None,
                         cap=300) -> tuple[dict, str, str]:
        """回傳 (campaign_detail, group_external_id, ad_external_id)，campaign/group/ad 三層
        都已經綁定完成、Campaign 轉 `live`（F31-I08 起用上架回讀同一組 repository 綁定函式），
        平台實體鏈也登記好了（`outcome_seed.bind_platform`）。每個平台實體 id 都是這次呼叫
        自己造的（`uuid`），不同測試、不同 Campaign 之間不會撞名。`cap`（F28-I01 唯一的上限，
        每筆成果成本）預設 300，結案整合測試才覆寫。"""
        start_date = start_date or self.today
        end_date = end_date or self.today
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": f"測試 Campaign {uuid.uuid4().hex[:6]}", "goal_text": "幫產品衝購買",
            "objective": "購買", "target_cost": cap,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": 500, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }, created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = plan.adopt_strategy(web.conn, self.org_id, self.brand_id, campaign["id"],
                                      actor=ACTOR)

        tag = uuid.uuid4().hex[:8]
        campaign_ext, group_ext, ad_ext = f"camp-{tag}", f"as-{tag}", f"ad-{tag}"

        # F31-I08: the name-match bind is gone; bind the three nodes with the same repository
        # helpers launch readback (`handoff_check`) uses, then ready -> live as a full bind did.
        group, ad = detail["groups"][0], detail["groups"][0]["ads"][0]
        ads_repo.bind_campaign(web.conn, self.org_id, self.brand_id, detail["id"],
                               external_id=campaign_ext, external_name=detail["name"],
                               external_status="ACTIVE")
        ads_repo.bind_group(web.conn, self.org_id, self.brand_id, group["id"],
                            external_id=group_ext, external_name=group["name"],
                            external_status="ACTIVE")
        ads_repo.bind_ad(web.conn, self.org_id, self.brand_id, ad["id"], external_id=ad_ext,
                         external_name=ad["name"], external_status="ACTIVE")
        if detail["status"] == "ready":
            ads_repo.set_campaign_status(web.conn, self.org_id, self.brand_id, detail["id"],
                                         "live")
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(reloaded["local_state"], "bound")
        outcome_seed.bind_platform(web.conn, self.org_id, self.brand_id, reloaded)
        web.conn.commit()
        return reloaded, group_ext, ad_ext

    def _insert_row(self, campaign_id: str, entity_id: str, day: date, *, spend: float,
                     purchases: int | None, revenue: float | None,
                     source: str = "test") -> None:
        """One group-grain platform row (`outcome_seed.seed_day`) -- used to build "some rows
        tracked, some not" mixes; the reader (`_bucket`) must handle them."""
        outcome_seed.seed_day(
            web.conn, self.org_id, self.brand_id, campaign_id, "group", entity_id, day,
            spend=spend, impressions=100, clicks=10, purchases=purchases, revenue=revenue,
            source=source,
        )
        web.conn.commit()


class NoDataDayIsUntrackedNotZeroTest(OutcomeTestBase):
    def test_no_outcome_rows_reads_as_untracked_not_zero(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertEqual(result["daily"], [])
        self.assertEqual(result["totals"]["spend"], 0)
        self.assertIsNone(result["totals"]["purchases"])
        self.assertIsNone(result["totals"]["revenue"])
        self.assertIsNone(result["totals"]["cpa"])
        self.assertIsNone(result["totals"]["roas"])
        self.assertIsNone(result["totals"]["roas_conservative"])


class ConservativeAndOptimisticRoasBothPresentTest(OutcomeTestBase):
    def test_conservative_and_optimistic_roas_are_both_present(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=1), end_date=self.today,
        )
        group_id = detail["groups"][0]["id"]
        # 兩天各一個真的購買與它的營收：總營收 1800／總花費 1000。
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=1),
                          spend=400.0, purchases=1, revenue=1200.0)
        self._insert_row(detail["id"], group_id, self.today,
                          spend=600.0, purchases=1, revenue=600.0)

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNotNone(result["totals"]["roas"])
        self.assertIsNotNone(result["totals"]["roas_conservative"])
        # 兩者都是拿 (1200 + 600) = 1800 除，分母都是 1000（全部花費都有追蹤到營收），
        # 這個情境下兩個值理當相等——但都要是數字，不是 None。
        self.assertAlmostEqual(result["totals"]["roas"], 1.8)
        self.assertAlmostEqual(result["totals"]["roas_conservative"], 1.8)


class RoasBasesDivergeWhenPartlyUntrackedTest(OutcomeTestBase):
    """使用者裁決：optimistic（`roas`）／conservative（`roas_conservative`）兩個基準永遠都要
    顯示、不能收斂成一個。一天有追蹤、一天沒有，兩個基準的分母因此不同，數字必須真的不一樣。"""

    def test_optimistic_and_conservative_roas_diverge_when_one_day_is_untracked(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=1), end_date=self.today,
        )
        group_id = detail["groups"][0]["id"]
        # 有追蹤到營收的一天：花費 500、營收 1000。
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=1),
                          spend=500.0, purchases=2, revenue=1000.0)
        # 沒有購買事件的一天：花費 500，營收未追蹤（不是 0）。
        self._insert_row(detail["id"], group_id, self.today,
                          spend=500.0, purchases=None, revenue=None)

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]

        # optimistic：只拿「有追蹤到營收」那一天的花費當分母 —— 1000 / 500 = 2.0。
        # conservative：拿全部花費（含未追蹤那天）當分母 —— 1000 / 1000 = 1.0。
        self.assertAlmostEqual(totals["roas"], 2.0)
        self.assertAlmostEqual(totals["roas_conservative"], 1.0)
        self.assertNotEqual(totals["roas"], totals["roas_conservative"])


class TrackedZeroUntrackedAndRealCountSumOnlyKnownTest(OutcomeTestBase):
    """F16-I01：一個 group 底下三天——一天未追蹤（`NULL`）、一天追蹤到真的零、一天追蹤到真的
    非零——加總只算有追蹤到的那兩天，`5`，不是把未追蹤那天當 0 灌進去（結果會一樣是 5，但如果
    真的把它當 0 算，這裡改成任何非 5 的數字都能抓到迴歸）；未追蹤那天存在，不是完全沒有列。"""

    def test_bucket_sums_only_tracked_days_never_coercing_null_to_zero(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=2), end_date=self.today,
        )
        group_id = detail["groups"][0]["id"]
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=2),
                          spend=100.0, purchases=None, revenue=None)
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=1),
                          spend=100.0, purchases=0, revenue=0.0)
        self._insert_row(detail["id"], group_id, self.today,
                          spend=100.0, purchases=5, revenue=500.0)

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertEqual(result["totals"]["purchases"], 5)
        self.assertEqual(result["totals"]["revenue"], 500.0)
        self.assertEqual(len(result["daily"]), 3)


class OutcomeTotalsReturnsNullNotZeroWhenAllUnknownTest(OutcomeTestBase):
    def test_outcome_totals_purchases_and_revenue_are_none_when_every_row_is_untracked(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        self._insert_row(detail["id"], detail["groups"][0]["id"], self.today, spend=500.0,
                          purchases=None, revenue=None)

        # `campaign_detail`'s `outcome` key is `_outcome_totals`'s return value verbatim for an
        # internal (non-imported) campaign — going through the public read keeps this a
        # black-box check of the same contract `list_campaigns`/`campaign_detail` ship.
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        totals = detail["outcome"]

        self.assertEqual(totals["row_count"], 1)
        self.assertEqual(float(totals["spend"]), 500.0)
        self.assertIsNone(totals["purchases"])
        self.assertIsNone(totals["revenue"])


class OnlyBoundPlatformRowsReachTheNumbersTest(OutcomeTestBase):
    """Contract P: a row reaches the performance numbers only through the binding -- a local
    node with no platform id has no row, and a monthly account-budget row is never a day of
    delivery."""

    def test_rows_of_a_node_without_a_platform_id_are_not_returned(self):
        detail, _group_ext, ad_ext = self._bound_campaign()
        ad = detail["groups"][0]["ads"][0]
        outcome_seed.seed_day(web.conn, self.org_id, self.brand_id, detail["id"], "ad",
                              ad["id"], self.today, spend=120.0, purchases=1, revenue=300.0)
        web.conn.commit()
        self.assertEqual(
            [r["entity_id"] for r in outcome.rows(web.conn, self.org_id, self.brand_id,
                                                  detail["id"], "ad")],
            [ad["id"]],
        )

        # The platform row is still stored; the local ad simply no longer points at it.
        web.conn.execute("UPDATE ads_ad SET external_id = NULL WHERE id = %s", (ad["id"],))
        web.conn.commit()

        self.assertEqual(
            outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "ad"), [],
        )
        stored = web.conn.execute(
            "SELECT COUNT(*) AS n FROM ads_external_daily d JOIN ads_external_entity e"
            " ON e.id = d.entity_id WHERE d.campaign_id = %s AND e.native_id = %s",
            (detail["id"], ad_ext),
        ).fetchone()
        self.assertEqual(stored["n"], 1)
        ads = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["ads"]
        self.assertEqual(ads[0]["spend"], 0)
        self.assertIsNone(ads[0]["purchases"])

    def test_monthly_budget_rows_are_excluded(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        group_id = detail["groups"][0]["id"]
        self._insert_row(detail["id"], group_id, self.today, spend=500.0, purchases=2,
                          revenue=900.0)
        outcome_seed.seed_day(
            web.conn, self.org_id, self.brand_id, detail["id"], "group", group_id, self.today,
            spend=99999.0, attribution_key=external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY,
        )
        web.conn.commit()

        rows = outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "group")
        self.assertEqual([float(r["spend"]) for r in rows], [500.0])
        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]
        self.assertEqual(totals["spend"], 500.0)
        outcome_totals = ads_repo.campaign_detail(
            web.conn, self.org_id, self.brand_id, detail["id"],
        )["outcome"]
        self.assertEqual(float(outcome_totals["spend"]), 500.0)
        self.assertEqual(outcome_totals["row_count"], 1)


class CoverageNamesUnreadDaysTest(OutcomeTestBase):
    """Contract P/Q: the window is `start_date … min(end_date, yesterday)`; days outside the
    recorded read range are named; nothing recorded is `never_synced`, not a wall of dates."""

    def test_never_synced_says_so_without_listing_days(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=4), end_date=self.today,
        )

        coverage = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["coverage"]

        self.assertTrue(coverage["never_synced"])
        self.assertEqual(coverage["missing_days"], [])
        self.assertEqual(coverage["missing"], 0)
        self.assertEqual(coverage["start"], (self.today - timedelta(days=4)).isoformat())
        self.assertEqual(coverage["end"], (self.today - timedelta(days=1)).isoformat())
        self.assertEqual(coverage["expected"], 4)

    def test_days_outside_the_recorded_range_are_named(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=4), end_date=self.today,
        )
        outcome_seed.set_coverage(web.conn, self.org_id, self.brand_id, detail["id"],
                                  self.today - timedelta(days=3), self.today - timedelta(days=2))
        web.conn.commit()

        coverage = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["coverage"]

        self.assertFalse(coverage["never_synced"])
        self.assertEqual(coverage["missing_days"], [
            (self.today - timedelta(days=4)).isoformat(),
            (self.today - timedelta(days=1)).isoformat(),
        ])
        self.assertEqual(coverage["missing"], 2)
        self.assertEqual(coverage["expected"], 4)

    def test_a_campaign_starting_today_has_no_window(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        outcome_seed.set_coverage(web.conn, self.org_id, self.brand_id, detail["id"],
                                  self.today, self.today)
        web.conn.commit()

        coverage = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["coverage"]

        self.assertEqual(coverage, {"start": None, "end": None, "expected": 0, "missing": 0,
                                    "missing_days": [], "never_synced": False})


class SampleBucketBoundaryTest(unittest.TestCase):
    def test_boundaries_are_exact(self):
        self.assertEqual(outcome.sample_bucket(9, 5), "低")
        self.assertEqual(outcome.sample_bucket(10, 5), "中")
        self.assertEqual(outcome.sample_bucket(49, 5), "中")
        self.assertEqual(outcome.sample_bucket(50, 5), "高")
        self.assertEqual(outcome.sample_bucket(100, 2), "低")  # 天數不夠，購買數再高也是低
        self.assertEqual(outcome.sample_bucket(100, 3), "高")


class IngestEndpointRetiredTest(OutcomeTestBase):
    def test_the_manual_ingest_endpoint_is_gone(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()

        resp = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/ingest",
        )

        self.assertIn(resp.status_code, (404, 405))


class RealPurchasesReachCloseoutTest(OutcomeTestBase):
    """A bound campaign with three days of platform rows carrying real purchases passes the
    sample gate (>=10 purchases, >=3 days) and closes as 達成 or 未達成, never 看不出."""

    def _three_days(self, cap):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=2), end_date=self.today, cap=cap,
        )
        # 三天各 4 個真的購買，合計 12、每筆 1200/12=100。
        for i in range(3):
            self._insert_row(detail["id"], detail["groups"][0]["id"],
                              self.today - timedelta(days=i), spend=400.0, purchases=4,
                              revenue=4000.0)
        outcome_seed.set_coverage(web.conn, self.org_id, self.brand_id, detail["id"],
                                  self.today - timedelta(days=2), self.today)
        web.conn.commit()
        return detail

    def test_bound_campaign_with_real_purchases_closes_as_achieved(self):
        from app.ads import closeout

        detail = self._three_days(cap=150)  # 100 <= 150

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["actual"], 100)
        self.assertEqual(closed["verdict_json"]["sample_bucket"], "中")

    def test_bound_campaign_with_real_purchases_below_target_closes_as_missed(self):
        from app.ads import closeout

        detail = self._three_days(cap=80)

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")  # 100 > 80
        self.assertEqual(closed["verdict_json"]["actual"], 100)


if __name__ == "__main__":
    unittest.main()
