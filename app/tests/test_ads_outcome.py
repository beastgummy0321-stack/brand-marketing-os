"""app/tests/test_ads_outcome.py — the performance tab of an internal campaign reads the one
pipeline (F37 Contract P): platform rows (`ads_external_daily`) of the entities its local nodes
are bound to. Falsifiers: a day with no data returns nothing (never a fabricated 0) and the
totals read as 未追蹤 (`None`) rather than 0; the two ROAS bases; tracked zero vs untracked; a
local node with no platform id and monthly budget rows never reach the numbers; coverage names
the unread days and says never-synced; the sample bucket boundaries (9/10, 49/50, 2 days/3 days)
are exact; the retired manual ingest endpoint is gone; real purchases reach closeout.
"""

import json
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import channels, external_repository, outcome, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.llm import providers
from app.tests.fixtures.ads_external import outcome_seed
from app.tests.test_ads_strategy_decision import bind_fixture, fixture_provider

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return fixture_provider(rendered_output)


_VALID_PLAN_REPLY = (
    '{"groups": [{"role": "new", "name": "新客組", "ads": '
    '[{"name": "新客-廣告一", "coordinates": '
    '{"audience": "a", "pain": "p", "angle": "an", "hook": "h", "proof": "pr", "offer": "none",'
    ' "format": "f"}, "scene": "上班族午休在辦公室滑手機找點心"}]}]}'
)


class _SeedAccount:
    """The seed's bound account (`outcome_seed.PLATFORM`／`SOURCE_ACCOUNT`) in `zone`."""

    def __init__(self, zone):
        self.zone = zone

    def accounts(self, conn, org, brand):
        return [{"account_id": outcome_seed.SOURCE_ACCOUNT, "timezone_name": self.zone}]


class OutcomeTestBase(unittest.TestCase):
    def setUp(self):
        # F50 Contract K: the seed account is bound in the org's zone, so a bound campaign's last
        # complete day (`coverage.last_complete_day`) is the org's yesterday.
        zone = _SeedAccount(str(coresettings.org_timezone(web.conn, org_id=coredb.DEV_ORG_ID)))
        real = channels.external_reader
        reader = patch.object(
            channels, "external_reader",
            side_effect=lambda p: zone if p == outcome_seed.PLATFORM else real(p),
        )
        reader.start()
        self.addCleanup(reader.stop)
        self.client = TestClient(main.app)
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心成效", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        # Metric fixtures end on a complete bound-account day; today stays distinct for coverage.
        self.complete_day = coresettings.last_complete_day(web.conn, org_id=self.org_id)
        self._orig_provider = plan.PROVIDER
        web.conn.commit()

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _bound_campaign(self, *, start_date=None, end_date=None,
                         cap=300, confirmed_cap=False, cap_source=None, pending_economics=False,
                         name=None) -> tuple[dict, str, str]:
        """回傳 (campaign_detail, group_external_id, ad_external_id)，campaign/group/ad 三層
        都已經綁定完成、Campaign 轉 `live`（F31-I08 起用上架回讀同一組 repository 綁定函式），
        平台實體鏈也登記好了（`outcome_seed.bind_platform`）。每個平台實體 id 都是這次呼叫
        自己造的（`uuid`），不同測試、不同 Campaign 之間不會撞名。`cap`（F28-I01 唯一的上限，
        每筆成果成本）預設 300，結案整合測試才覆寫。"""
        start_date = start_date or self.complete_day
        end_date = end_date or self.complete_day
        context = {}
        if cap_source is not None:
            context["field_sources"] = {"cap": cap_source}
        if confirmed_cap or pending_economics:
            product = bi_repo.create_product(
                web.conn, self.brand_id, name="Confirmed TWD period cap", actor=ACTOR,
            )
            if pending_economics:
                bi_repo.create_pending_product_economics(
                    web.conn, self.brand_id, product["id"], selling_price=620,
                    currency="USD", source_reference_id=None, actor=ACTOR,
                )
            else:
                bi_repo.save_product_economics(
                    web.conn, self.brand_id, product["id"], selling_price=cap + 100,
                    currency="TWD", confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=100,
                )
            context = {**context, "product_ids": [product["id"]]}
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": name or f"測試 Campaign {uuid.uuid4().hex[:6]}", "goal_text": "幫產品衝購買",
            "objective": "購買", "target_cost": None if confirmed_cap else cap or 300,
            "context_json": context,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": 500, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }, created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        revision = bind_fixture(
            web.conn, self.org_id, self.brand_id, campaign["id"], json.loads(_VALID_PLAN_REPLY)
        )
        detail = plan.adopt_strategy(web.conn, self.org_id, self.brand_id, campaign["id"],
                                      actor=ACTOR, expected_revision=revision,
                                      operation_id=f"outcome-{campaign['id']}")
        if cap is None:
            # Imported outcome behavior with an unknown cap is independent of initial adoption.
            web.conn.execute(
                "UPDATE ads_campaign SET target_cost=NULL,target_basis=NULL WHERE id=%s",
                (campaign["id"],),
            )

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
        self.assertIsNone(result["totals"]["spend"])
        self.assertIsNone(result["totals"]["purchases"])
        self.assertIsNone(result["totals"]["revenue"])
        self.assertIsNone(result["totals"]["cpa"])
        self.assertIsNone(result["totals"]["roas_tracked_spend"])
        self.assertIsNone(result["totals"]["roas_all_spend"])


class ConservativeAndOptimisticRoasBothPresentTest(OutcomeTestBase):
    def test_conservative_and_optimistic_roas_are_both_present(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.complete_day - timedelta(days=1), end_date=self.complete_day,
        )
        group_id = detail["groups"][0]["id"]
        # 兩天各一個真的購買與它的營收：總營收 1800／總花費 1000。
        self._insert_row(detail["id"], group_id, self.complete_day - timedelta(days=1),
                          spend=400.0, purchases=1, revenue=1200.0)
        self._insert_row(detail["id"], group_id, self.complete_day,
                          spend=600.0, purchases=1, revenue=600.0)

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNotNone(result["totals"]["roas_tracked_spend"])
        self.assertIsNotNone(result["totals"]["roas_all_spend"])
        # 兩者都是拿 (1200 + 600) = 1800 除，分母都是 1000（全部花費都有追蹤到營收），
        # 這個情境下兩個值理當相等——但都要是數字，不是 None。
        self.assertAlmostEqual(result["totals"]["roas_tracked_spend"], 1.8)
        self.assertAlmostEqual(result["totals"]["roas_all_spend"], 1.8)


class RoasBasesDivergeWhenPartlyUntrackedTest(OutcomeTestBase):
    """使用者裁決：optimistic（`roas_tracked_spend`）／conservative（`roas_all_spend`）兩個基準永遠都要
    顯示、不能收斂成一個。一天有追蹤、一天沒有，兩個基準的分母因此不同，數字必須真的不一樣。"""

    def test_optimistic_and_conservative_roas_diverge_when_one_day_is_untracked(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.complete_day - timedelta(days=1), end_date=self.complete_day,
        )
        group_id = detail["groups"][0]["id"]
        # 有追蹤到營收的一天：花費 500、營收 1000。
        self._insert_row(detail["id"], group_id, self.complete_day - timedelta(days=1),
                          spend=500.0, purchases=2, revenue=1000.0)
        # 沒有購買事件的一天：花費 500，營收未追蹤（不是 0）。
        self._insert_row(detail["id"], group_id, self.complete_day,
                          spend=500.0, purchases=None, revenue=None)

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]

        # optimistic：只拿「有追蹤到營收」那一天的花費當分母 —— 1000 / 500 = 2.0。
        # conservative：拿全部花費（含未追蹤那天）當分母 —— 1000 / 1000 = 1.0。
        self.assertAlmostEqual(totals["roas_tracked_spend"], 2.0)
        self.assertAlmostEqual(totals["roas_all_spend"], 1.0)
        self.assertNotEqual(totals["roas_tracked_spend"], totals["roas_all_spend"])


class TrackedZeroUntrackedAndRealCountSumOnlyKnownTest(OutcomeTestBase):
    """F16-I01：一個 group 底下三天——一天未追蹤（`NULL`）、一天追蹤到真的零、一天追蹤到真的
    非零——加總只算有追蹤到的那兩天，`5`，不是把未追蹤那天當 0 灌進去（結果會一樣是 5，但如果
    真的把它當 0 算，這裡改成任何非 5 的數字都能抓到迴歸）；未追蹤那天存在，不是完全沒有列。"""

    def test_bucket_sums_only_tracked_days_never_coercing_null_to_zero(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.complete_day - timedelta(days=2), end_date=self.complete_day,
        )
        group_id = detail["groups"][0]["id"]
        self._insert_row(detail["id"], group_id, self.complete_day - timedelta(days=2),
                          spend=100.0, purchases=None, revenue=None)
        self._insert_row(detail["id"], group_id, self.complete_day - timedelta(days=1),
                          spend=100.0, purchases=0, revenue=0.0)
        self._insert_row(detail["id"], group_id, self.complete_day,
                          spend=100.0, purchases=5, revenue=500.0)

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertEqual(result["totals"]["purchases"], 5)
        self.assertEqual(result["totals"]["revenue"], 500.0)
        self.assertEqual(len(result["daily"]), 3)


class OutcomeTotalsReturnsNullNotZeroWhenAllUnknownTest(OutcomeTestBase):
    def test_outcome_totals_purchases_and_revenue_are_none_when_every_row_is_untracked(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        self._insert_row(detail["id"], detail["groups"][0]["id"], self.complete_day, spend=500.0,
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
                              ad["id"], self.complete_day, spend=120.0, purchases=1, revenue=300.0)
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
        self.assertIsNone(ads[0]["spend"])
        self.assertIsNone(ads[0]["purchases"])

    def test_monthly_budget_rows_are_excluded(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        group_id = detail["groups"][0]["id"]
        self._insert_row(detail["id"], group_id, self.complete_day, spend=500.0, purchases=2,
                          revenue=900.0)
        outcome_seed.seed_day(
            web.conn, self.org_id, self.brand_id, detail["id"], "group", group_id,
            self.complete_day,
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
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today, end_date=self.today,
        )
        outcome_seed.set_coverage(web.conn, self.org_id, self.brand_id, detail["id"],
                                  self.today, self.today)
        web.conn.commit()

        coverage = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["coverage"]

        self.assertEqual(coverage, {"start": None, "end": None, "expected": 0, "missing": 0,
                                    "missing_days": [], "never_synced": False})


class PeriodGradeTest(OutcomeTestBase):
    """F40-I01: `totals.grade` is the one cap ruler (`triage.grade_window`) over the whole period,
    read from the SAME totals the tab prints -- the 「這期狀態列」's grade comes from here, never a
    frontend copy of the ruler."""

    def _seven_days(self, *, cap, spend_per_day=400.0, purchases_per_day=2):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.complete_day - timedelta(days=6), end_date=self.complete_day, cap=cap,
            cap_source="user" if cap is not None else None,
        )
        for i in range(7):
            self._insert_row(detail["id"], detail["groups"][0]["id"],
                              self.complete_day - timedelta(days=i), spend=spend_per_day,
                              purchases=purchases_per_day, revenue=None)
        return detail

    def test_grade_matches_the_one_ruler_over_the_period(self):
        from app.ads import triage

        detail = self._seven_days(cap=300)  # 2800 / 14 = 200 per result <= 300

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        totals = result["totals"]
        self.assertEqual(totals["grade"], {"grade": "on_target", "label": "划算"})
        view = {"result_count": totals["purchases"], "cost_per_result": totals["cpa"],
                "result_kind": "purchase", "reason": None}
        grade, label, _reason = triage.grade_window(view, totals["spend"], 300, 7)
        self.assertEqual(totals["grade"], {"grade": grade, "label": label})

    def test_over_the_watch_band_is_too_expensive(self):
        detail = self._seven_days(cap=150)  # 200 > 150 * 1.2

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]

        self.assertEqual(totals["grade"], {"grade": "over", "label": "太貴"})

    def test_no_cap_is_no_target(self):
        detail = self._seven_days(cap=None)

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]

        self.assertEqual(totals["grade"], {"grade": "no_target", "label": "未判斷"})

    def test_untracked_or_too_thin_is_insufficient_never_a_zero(self):
        detail, _group_ext, _ad_ext = self._bound_campaign(cap=300)

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]

        self.assertEqual(totals["grade"]["grade"], "insufficient")
        self.assertIsNone(totals["purchases"])


class SampleBucketBoundaryTest(unittest.TestCase):
    """F48-I02: the bucket's thresholds are the ruler's own (`triage.MIN_RESULT_EVENTS` results,
    `triage.WINDOW_STEPS[0]` days), and an untracked count is 「未追蹤」, never 低."""

    def test_boundaries_are_exact(self):
        from app.ads import triage

        days = triage.WINDOW_STEPS[0]
        few = triage.MIN_RESULT_EVENTS
        self.assertEqual(outcome.sample_bucket(few - 1, days), "低")
        self.assertEqual(outcome.sample_bucket(few, days), "中")
        self.assertEqual(outcome.sample_bucket(49, days), "中")
        self.assertEqual(outcome.sample_bucket(50, days), "高")
        self.assertEqual(outcome.sample_bucket(100, days - 1), "低")  # 天數不夠，購買數再高也是低
        self.assertEqual(outcome.sample_bucket(100, days), "高")

    def test_untracked_is_its_own_bucket(self):
        self.assertEqual(outcome.sample_bucket(None, 30), "未追蹤")
        self.assertEqual(outcome.sample_bucket(0, 30), "低")


class IngestEndpointRetiredTest(OutcomeTestBase):
    def test_the_manual_ingest_endpoint_is_gone(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()

        resp = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/ingest",
        )

        self.assertIn(resp.status_code, (404, 405))


class RealPurchasesReachCloseoutTest(OutcomeTestBase):
    """A bound campaign with three days of platform rows carrying real purchases closes as 達成 or
    未達成, never 看不出 (F48-I02: the sample is shown -- three days is 低 -- never a gate)."""

    def _three_days(self, cap):
        detail, _group_ext, _ad_ext = self._bound_campaign(
            start_date=self.complete_day - timedelta(days=2), end_date=self.complete_day, cap=cap,
            cap_source="user",
        )
        # 三天各 4 個真的購買，合計 12、每筆 1200/12=100。
        for i in range(3):
            self._insert_row(detail["id"], detail["groups"][0]["id"],
                              self.complete_day - timedelta(days=i), spend=400.0, purchases=4,
                              revenue=4000.0)
        outcome_seed.set_coverage(web.conn, self.org_id, self.brand_id, detail["id"],
                                  self.complete_day - timedelta(days=2), self.complete_day)
        web.conn.commit()
        return detail

    def test_bound_campaign_with_real_purchases_closes_as_achieved(self):
        from app.ads import closeout

        detail = self._three_days(cap=150)  # 100 <= 150

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["actual"], 100)
        self.assertEqual(closed["verdict_json"]["sample"],
                         {"purchases": 12, "days": 3, "bucket": "低"})

    def test_bound_campaign_with_real_purchases_below_target_closes_as_missed(self):
        from app.ads import closeout

        detail = self._three_days(cap=80)

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")  # 100 > 80
        self.assertEqual(closed["verdict_json"]["actual"], 100)

    def test_public_adopted_close_serves_new_learning(self):
        detail = self._three_days(cap=150)
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/close", json={})
        print("ADOPTED_PUBLIC_CLOSE_RECEIPT", response.status_code, response.text)
        self.assertEqual(response.status_code, 200, response.text)


class PeriodProjectionPublicTest(OutcomeTestBase):
    """Contract P: public period numbers and raw comparison history are distinct."""

    def setUp(self):
        clock = patch.object(coredb, "now_utc", return_value=datetime(2026, 10, 27, 4, tzinfo=UTC))
        clock.start()
        self.addCleanup(clock.stop)
        super().setUp()

    def test_public_budget_pace_uses_completed_days_without_mixing_native_currency(self):
        for currency in ("TWD", "USD"):
            detail, _, _ = self._bound_campaign(
                start_date=date(2026, 10, 24), end_date=date(2026, 10, 30)
            )
            group = detail["groups"][0]
            for day in (24, 25, 26):
                outcome_seed.seed_day(
                    web.conn, self.org_id, self.brand_id, detail["id"], "group", group["id"],
                    date(2026, 10, day), spend=300, purchases=4, revenue=6240, currency=currency,
                )
            web.conn.commit()
            base = f"/api/ads/brands/{self.brand_id}/campaigns"
            listed = self.client.get(base)
            viewed = self.client.get(f"{base}/{detail['id']}")
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertEqual(viewed.status_code, 200, viewed.text)
            row = next(c for c in listed.json()["campaigns"] if c["id"] == detail["id"])
            record = viewed.json()["campaign"]
            print("PUBLIC_BUDGET_PACE_RECEIPT", currency,
                  json.dumps({"list": row, "detail": record}))
            with self.subTest(consumer="pct", currency=currency):
                self.assertIsNotNone(row["budget_progress"]["total"])
                if currency == "USD":
                    self.assertIsNone(row["budget_progress"]["pct"])
                else:
                    self.assertIsNotNone(row["budget_progress"]["pct"])
            for consumer, value in (("list", row), ("detail", record)):
                with self.subTest(consumer=consumer, currency=currency):
                    self.assertEqual(value["outcome"]["scope"]["days"], 3)
                    self.assertIn("第 3／7 天", value["judgment"]["detail"])
                    if currency == "USD":
                        self.assertNotIn("NT$", value["judgment"]["detail"])
                        self.assertNotIn("快", value["judgment"]["text"])
                        self.assertNotIn("慢", value["judgment"]["text"])

    def test_public_recent_grades_do_not_compare_usd_results_with_manual_twd_cap(self):
        for currency in ("TWD", "USD"):
            with self.subTest(currency=currency):
                detail, _, _ = self._bound_campaign(
                    start_date=date(2026, 10, 24), end_date=date(2026, 10, 30),
                )
                base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
                saved = self.client.put(
                    f"{base}/target",
                    json={"basis": "own", "value": 350, "expected_revision": 0},
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                ad = detail["groups"][0]["ads"][0]
                for day in (24, 25, 26):
                    row = outcome_seed.seed_day(
                        web.conn, self.org_id, self.brand_id, detail["id"], "ad", ad["id"],
                        date(2026, 10, day), spend=4000, purchases=10, revenue=5000,
                        currency=currency,
                    )
                    external_repository.upsert_observation(
                        web.conn, self.org_id, self.brand_id, detail["id"],
                        {"entity_id": row["entity_id"], "day": date(2026, 10, day),
                         "metric_scope": "ad", "attribution_key": outcome_seed.ATTRIBUTION_KEY,
                         "currency": currency, "spend": 4000, "purchases": 10, "revenue": 5000,
                         "source": "test"},
                        result_kind="purchase", result_count=10, result_action="omni_purchase",
                        result_attribution="7d_click+1d_view",
                    )
                outcome_seed.set_coverage(
                    web.conn, self.org_id, self.brand_id, detail["id"],
                    date(2026, 10, 24), date(2026, 10, 26),
                )
                web.conn.commit()
                result = self.client.get(f"{base}/triage")
                self.assertEqual(result.status_code, 200, result.text)
                print("PUBLIC_RECENT_CAP_UNIT_RECEIPT", currency, json.dumps(result.json()))
                items = result.json()["triage"]["items"]
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["current"]["cost_per_result"], 400)
                self.assertEqual(items[0]["current"]["result_count"], 30)
                self.assertEqual(items[0]["current"]["currency"], currency)
                with self.subTest(consumer="recent_grade"):
                    self.assertEqual(
                        items[0]["grade"], "watch" if currency == "TWD" else "insufficient",
                    )
                    comparison = items[0]["cap_comparison"]
                    self.assertEqual(comparison["currency"], "TWD")
                    self.assertEqual(comparison["source"], "user")
                    self.assertEqual(
                        comparison["reason"],
                        None if currency == "TWD" else "cap_currency_mismatch",
                    )
                    if currency == "USD":
                        self.assertEqual(items[0]["reason_code"], "cap_currency_mismatch")
                        self.assertIsNone(items[0]["sample"]["spend_multiple"])
                monthly = self.client.get(
                    f"/api/ads/brands/{self.brand_id}/month-summary?month=2026-10",
                )
                self.assertEqual(monthly.status_code, 200, monthly.text)
                print("PUBLIC_EXPLICIT_MONTH_CAP_UNIT_RECEIPT", currency, monthly.text)
                grades = [row for row in monthly.json()["grades"]["rows"]
                          if row["campaign_id"] == detail["id"]]
                self.assertEqual(len(grades), 1)
                with self.subTest(consumer="explicit_month_grade"):
                    self.assertEqual(
                        grades[0]["grade"], "watch" if currency == "TWD" else "insufficient",
                    )
                    self.assertEqual(grades[0]["spend"], 12000)
                    self.assertEqual(grades[0]["cost_per_result"], 400)
                    self.assertEqual(grades[0]["currency"], currency)
                    self.assertEqual(grades[0]["cap_comparison"]["currency"], "TWD")
                    self.assertEqual(
                        grades[0]["cap_comparison"]["reason"],
                        None if currency == "TWD" else "cap_currency_mismatch",
                    )

    def test_public_break_even_unit_is_independent_of_manual_own_unit(self):
        for currency, status in (("TWD", "confirmed"), ("USD", "confirmed"),
                                 ("USD", "pending"), (None, None)):
            confirmed = status == "confirmed"
            with self.subTest(break_even_currency=currency, economics_status=status):
                detail, _, _ = self._bound_campaign(
                    start_date=date(2026, 10, 24), end_date=date(2026, 10, 30),
                    cap=520 if confirmed else 300, confirmed_cap=confirmed,
                    pending_economics=status == "pending",
                )
                base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
                if confirmed:
                    bi_repo.save_product_economics(
                        web.conn, self.brand_id, detail["cap"]["product_id"],
                        selling_price=620, unit_variable_cost=100, currency=currency,
                        confirmed_by=ACTOR, actor=ACTOR,
                    )
                    web.conn.commit()
                saved = self.client.put(
                    f"{base}/target", json={"basis": "own", "value": 450, "expected_revision": 0},
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                ad = detail["groups"][0]["ads"][0]
                for day in (24, 25, 26):
                    row = outcome_seed.seed_day(
                        web.conn, self.org_id, self.brand_id, detail["id"], "ad", ad["id"],
                        date(2026, 10, day), spend=480, purchases=10, revenue=800,
                    )
                    external_repository.upsert_observation(
                        web.conn, self.org_id, self.brand_id, detail["id"],
                        {"entity_id": row["entity_id"], "day": date(2026, 10, day),
                         "metric_scope": "ad", "attribution_key": outcome_seed.ATTRIBUTION_KEY,
                         "currency": "TWD", "spend": 480, "purchases": 10, "revenue": 800,
                         "source": "test"},
                        result_kind="purchase", result_count=10, result_action="omni_purchase",
                        result_attribution="7d_click+1d_view",
                    )
                outcome_seed.set_coverage(
                    web.conn, self.org_id, self.brand_id, detail["id"],
                    date(2026, 10, 24), date(2026, 10, 26),
                )
                web.conn.commit()
                response = self.client.get(f"{base}/triage")
                self.assertEqual(response.status_code, 200, response.text)
                print("PUBLIC_INDEPENDENT_BREAK_EVEN_UNIT", currency, status, response.text)
                item = response.json()["triage"]["items"][0]
                self.assertEqual(item["target"]["basis"], "own")
                self.assertEqual(item["target"]["value"], 450)
                self.assertEqual(item["target"]["break_even"], 520 if confirmed else None)
                self.assertEqual(item["current"]["cost_per_result"], 48)
                self.assertEqual(item["target"]["cap_unit"]["currency"], "TWD")
                self.assertEqual(
                    item["target"]["break_even_unit"]["currency"], currency if confirmed else None,
                )
                self.assertEqual(item["target"]["break_even_unit"]["unit_basis"],
                                 "confirmed_product_economics" if confirmed else None)
                for path in (base, f"{base}/target"):
                    read = self.client.get(path)
                    self.assertEqual(read.status_code, 200, read.text)
                    cap = read.json()["campaign"]["cap"] if path == base else read.json()["target"]
                    self.assertEqual(cap.get("cap_unit", {}).get("currency"), "TWD")
                    self.assertEqual(cap.get("break_even_unit", {}).get("currency"),
                                     currency if confirmed else None)
                    self.assertEqual(cap.get("price_unit", {}).get("currency"),
                                     currency if confirmed else None)

    def test_public_confirmed_price_unit_remains_known_without_cost_or_break_even(self):
        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24), end_date=date(2026, 10, 30),
            cap=520, confirmed_cap=True,
        )
        bi_repo.save_product_economics(
            web.conn, self.brand_id, detail["cap"]["product_id"],
            selling_price=620, unit_variable_cost=None, currency="USD",
            confirmed_by=ACTOR, actor=ACTOR,
        )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
        saved = self.client.put(
            f"{base}/target", json={"basis": "own", "value": 450, "expected_revision": 0},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        for path in (base, f"{base}/target"):
            read = self.client.get(path)
            self.assertEqual(read.status_code, 200, read.text)
            print("PUBLIC_CONFIRMED_PRICE_WITHOUT_COST", path, json.dumps(read.json()))
            cap = read.json()["campaign"]["cap"] if path == base else read.json()["target"]
            self.assertEqual(cap["price"], 620)
            self.assertEqual(cap["value"], 450)
            self.assertEqual(cap["cap_unit"]["currency"], "TWD")
            self.assertEqual(cap["price_unit"]["currency"], "USD")
            self.assertEqual(cap["price_unit"]["unit_basis"], "confirmed_product_economics")
            self.assertIsNone(cap["break_even"])
            self.assertIsNone(cap["break_even_unit"]["currency"])
            if path.endswith("/target"):
                self.assertIsNone(cap["cost"])

    def test_public_manual_target_unit_uses_recorded_input_not_current_account(self):
        for source, value, currency in (
            ("copied", 350, "TWD"), ("copied", 350, "USD"),
            ("copied", 300, "TWD"), ("break_even", 300, "USD"),
        ):
            with self.subTest(source=source, stored_value=value, currency=currency):
                detail, _, _ = self._bound_campaign(
                    start_date=date(2026, 10, 24), end_date=date(2026, 10, 30), cap=value,
                    cap_source=source,
                )
                for day in (24, 25, 26):
                    outcome_seed.seed_day(
                        web.conn, self.org_id, self.brand_id, detail["id"], "group",
                        detail["groups"][0]["id"], date(2026, 10, day),
                        spend=400, purchases=1, revenue=500, currency=currency,
                    )
                outcome_seed.set_coverage(
                    web.conn, self.org_id, self.brand_id, detail["id"],
                    date(2026, 10, 24), date(2026, 10, 26),
                )
                web.conn.commit()
                base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
                saved = self.client.put(
                    f"{base}/target", json={"basis": "own", "value": 350, "expected_revision": 0},
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                result = self.client.get(f"{base}/performance")
                closed = self.client.post(f"{base}/close", json={})
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(closed.status_code, 200, closed.text)
                data, record = result.json(), closed.json()["campaign"]
                print("MANUAL_TARGET_UNIT_RECEIPT",
                      json.dumps({"performance": data, "close": record}))
                self.assertEqual(data["totals"]["cpa"], 400)
                self.assertEqual(record["cap"]["value"], 350)
                self.assertEqual(record["cap"]["basis"], "own")
                comparison = data["cap_comparison"]
                if value == 350:
                    self.assertEqual(comparison["source"], source)
                    self.assertIsNone(comparison["currency"])
                    self.assertEqual(comparison["reason"], "cap_currency_unknown")
                    self.assertEqual(record["verdict"], "看不出")
                    self.assertEqual(data["totals"]["grade"]["grade"], "insufficient")
                else:
                    self.assertEqual(comparison["source"], "user")
                    self.assertEqual(comparison["currency"], "TWD")
                    self.assertEqual(comparison["unit_basis"], "manual_ntd_input")
                    self.assertEqual(
                        comparison["reason"],
                        None if currency == "TWD" else "cap_currency_mismatch",
                    )
                    self.assertEqual(record["verdict"], "未達成" if currency == "TWD" else "看不出")
                    if currency == "TWD":
                        self.assertNotEqual(data["totals"]["grade"]["grade"], "insufficient")
                    else:
                        self.assertEqual(data["totals"]["grade"]["grade"], "insufficient")

    def test_public_all_null_counts_are_unknown_while_observed_zero_stays_zero(self):
        for value in (None, 0):
            with self.subTest(observed=value):
                detail, _, _ = self._bound_campaign(
                    start_date=date(2026, 10, 24), end_date=date(2026, 10, 26)
                )
                group = detail["groups"][0]
                for kind, node in (("group", group), ("ad", group["ads"][0])):
                    outcome_seed.seed_day(
                        web.conn,
                        self.org_id,
                        self.brand_id,
                        detail["id"],
                        kind,
                        node["id"],
                        date(2026, 10, 24),
                        spend=0,
                        purchases=0,
                        revenue=0,
                        impressions=value,
                        clicks=value,
                    )
                web.conn.commit()
                response = self.client.get(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/performance"
                )
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                print("NULL_COUNTS_PUBLIC_RECEIPT", json.dumps(result))
                for consumer, bucket in (
                    ("totals", result["totals"]),
                    ("daily", result["daily"][0]),
                    ("group", result["groups"][0]),
                    ("ad", result["ads"][0]),
                ):
                    with self.subTest(consumer=consumer):
                        self.assertEqual(bucket["spend"], 0)
                        self.assertEqual(bucket["impressions"], value)
                        self.assertEqual(bucket["clicks"], value)

    def test_c15_public_period_uses_completed_campaign_days_preserving_six_raw_rows(self):
        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24),
            end_date=date(2026, 10, 30),
            cap=100,
        )
        group = detail["groups"][0]
        ad = group["ads"][0]
        for day in range(21, 27):
            spend, purchases, revenue = (500, 1, 1560) if day < 24 else (300, 4, 6240)
            for kind, node in (("group", group), ("ad", ad)):
                outcome_seed.seed_day(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    detail["id"],
                    kind,
                    node["id"],
                    date(2026, 10, day),
                    spend=spend,
                    purchases=purchases,
                    revenue=revenue,
                )
        outcome_seed.set_coverage(
            web.conn,
            self.org_id,
            self.brand_id,
            detail["id"],
            date(2026, 10, 21),
            date(2026, 10, 26),
        )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns"
        perf = self.client.get(f"{base}/{detail['id']}/performance")
        listed = self.client.get(base)
        viewed = self.client.get(f"{base}/{detail['id']}")
        for response in (perf, listed, viewed):
            self.assertEqual(response.status_code, 200, response.text)
        raw = outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "group")
        listed_row = next(c for c in listed.json()["campaigns"] if c["id"] == detail["id"])
        print(
            "C15_PUBLIC_RECEIPT",
            json.dumps(
                {
                    "clock": coredb.now_utc(),
                    "raw": raw,
                    "performance": perf.json(),
                    "list": listed_row["outcome"],
                    "detail": viewed.json()["campaign"]["outcome"],
                },
                default=str,
                ensure_ascii=False,
            ),
        )
        self.assertEqual(len(raw), 6)
        for source, totals in (
            ("performance", perf.json()["totals"]),
            ("list", listed_row["outcome"]),
            ("detail", viewed.json()["campaign"]["outcome"]),
        ):
            with self.subTest(source=source):
                self.assertEqual(float(totals["spend"]), 900)
                self.assertEqual(totals["purchases"], 12)
                self.assertEqual(float(totals["revenue"]), 18720)
        self.assertEqual(perf.json()["totals"]["cpa"], 75)
        self.assertEqual(perf.json()["totals"]["roas_all_spend"], 20.8)
        self.assertEqual(
            [row["day"] for row in perf.json()["daily"]], ["2026-10-24", "2026-10-25", "2026-10-26"]
        )

    def test_imported_public_period_excludes_intraday_but_raw_requested_history_keeps_it(self):
        imported = external_repository.create_imported_campaign(
            web.conn,
            self.org_id,
            self.brand_id,
            name="Imported observed range",
            created_by=ACTOR,
        )
        entity = external_repository.upsert_entity(
            web.conn,
            self.org_id,
            self.brand_id,
            imported["id"],
            {
                "platform": outcome_seed.PLATFORM,
                "source_account": outcome_seed.SOURCE_ACCOUNT,
                "native_kind": "campaign",
                "native_id": f"native-{imported['id']}",
            },
        )
        for day, spend in ((26, 300), (27, 999)):
            external_repository.upsert_observation(
                web.conn,
                self.org_id,
                self.brand_id,
                imported["id"],
                {
                    "entity_id": entity["id"],
                    "day": date(2026, 10, day),
                    "metric_scope": "campaign",
                    "attribution_key": "test",
                    "currency": "TWD",
                    "spend": spend,
                    "purchases": 4,
                    "revenue": 6240,
                    "source": "test",
                },
            )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{imported['id']}"
        performance = self.client.get(f"{base}/performance")
        detail = self.client.get(base)
        self.assertEqual(performance.status_code, 200, performance.text)
        self.assertEqual(detail.status_code, 200, detail.text)
        raw = external_repository.external_view(
            web.conn,
            self.org_id,
            self.brand_id,
            imported["id"],
            start=date(2026, 10, 26),
            end=date(2026, 10, 27),
        )
        print(
            "IMPORTED_PUBLIC_RECEIPT",
            json.dumps(
                {
                    "clock": coredb.now_utc(),
                    "raw": raw,
                    "performance": performance.json(),
                    "detail": detail.json(),
                },
                default=str,
            ),
        )
        self.assertEqual(len(raw["observations"]), 2)
        for consumer, view in (
            ("performance", performance.json()["external_view"]),
            ("detail", detail.json()["campaign"]["external_view"]),
        ):
            with self.subTest(consumer=consumer):
                self.assertEqual(view["window"]["end"], "2026-10-26")
                self.assertEqual([row["day"] for row in view["observations"]], ["2026-10-26"])

    def test_imported_period_is_complete_beyond_both_page_cursors(self):
        imported = external_repository.create_imported_campaign(
            web.conn,
            self.org_id,
            self.brand_id,
            name="Native complete pagination",
            created_by=ACTOR,
        )
        for index in range(101):
            entity = external_repository.upsert_entity(
                web.conn,
                self.org_id,
                self.brand_id,
                imported["id"],
                {
                    "platform": outcome_seed.PLATFORM,
                    "source_account": outcome_seed.SOURCE_ACCOUNT,
                    "native_kind": "ad",
                    "native_id": f"native-{index}",
                },
            )
            external_repository.upsert_observation(
                web.conn,
                self.org_id,
                self.brand_id,
                imported["id"],
                {
                    "entity_id": entity["id"],
                    "day": date(2026, 10, 26),
                    "metric_scope": "ad",
                    "attribution_key": "test",
                    "currency": "TWD",
                    "spend": 10,
                    "source": "test",
                },
            )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{imported['id']}"
        for consumer, response in (
            ("performance", self.client.get(f"{base}/performance")),
            ("detail", self.client.get(base)),
        ):
            with self.subTest(consumer=consumer):
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                view = (data if consumer == "performance" else data["campaign"])["external_view"]
                print("NATIVE_PAGE_PUBLIC_RECEIPT", consumer, json.dumps(view))
                self.assertEqual(len(view["entities"]), 101)
                self.assertEqual(len(view["observations"]), 101)
                self.assertIsNone(view["next_entity_cursor"])
                self.assertIsNone(view["next_observation_cursor"])
                self.assertEqual(sum(float(row["spend"]) for row in view["observations"]), 1010)

    def test_ambiguous_currency_or_attribution_never_prints_a_combined_money_value(self):
        for currencies, attributions in (
            (["TWD", "USD"], ["test", "test"]),
            (["TWD", "TWD"], ["test", "old"]),
            ([None, None], ["test", "test"]),
        ):
            with self.subTest(currencies=currencies, attributions=attributions):
                detail, _, _ = self._bound_campaign(
                    start_date=date(2026, 10, 24), end_date=date(2026, 10, 30)
                )
                group = detail["groups"][0]
                for offset, (currency, attribution) in enumerate(
                    zip(currencies, attributions, strict=True)
                ):
                    for kind, node in (("group", group), ("ad", group["ads"][0])):
                        outcome_seed.seed_day(
                            web.conn,
                            self.org_id,
                            self.brand_id,
                            detail["id"],
                            kind,
                            node["id"],
                            date(2026, 10, 24 + offset),
                            spend=300,
                            purchases=4,
                            revenue=6240,
                            currency=currency,
                            attribution_key=attribution,
                        )
                outcome_seed.set_coverage(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    detail["id"],
                    date(2026, 10, 24),
                    date(2026, 10, 26),
                )
                web.conn.commit()
                response = self.client.get(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/performance"
                )
                self.assertEqual(response.status_code, 200, response.text)
                print("AMBIGUOUS_PUBLIC_RECEIPT", json.dumps(response.json()))
                self.assertIsNone(response.json()["totals"]["spend"])
                self.assertIsNone(response.json()["totals"]["cpa"])
                self.assertIsNone(response.json()["totals"]["roas_all_spend"])
                for node in [*response.json()["groups"], *response.json()["ads"]]:
                    self.assertIsNone(node["spend_share"])
                closed = self.client.post(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/close", json={}
                )
                self.assertEqual(closed.status_code, 200, closed.text)
                self.assertEqual(closed.json()["campaign"]["verdict"], "看不出")
                ledger = bi_repo.list_learnings(web.conn, self.brand_id, limit=500)
                current = [row for row in ledger if row["source_cycle_id"] == detail["id"]]
                ranked = [
                    row
                    for row in ledger
                    if (row["source_cycle_id"] or "").startswith(detail["id"] + ":")
                ]
                self.assertEqual(len(current), 1)
                self.assertIn("看不出", current[0]["learning_text"])
                self.assertEqual(ranked, [])

    def test_product_twd_cap_cannot_grade_or_close_usd_period_as_achieved(self):
        product = bi_repo.create_product(web.conn, self.brand_id, name="TWD economics", actor=ACTOR)
        bi_repo.save_product_economics(
            web.conn,
            self.brand_id,
            product["id"],
            selling_price=1000,
            currency="TWD",
            confirmed_by=ACTOR,
            actor=ACTOR,
            unit_variable_cost=450,
            shipping_cost=50,
        )
        campaign = ads_repo.create_campaign(
            web.conn,
            self.org_id,
            self.brand_id,
            {
                "name": "USD observations versus TWD product",
                "goal_text": "Period cost",
                "objective": "購買",
                "target_cost": None,
                "start_date": date(2026, 10, 24),
                "end_date": date(2026, 10, 30),
                "status": "live",
                "context_json": {"product_ids": [product["id"]]},
            },
            created_by=ACTOR,
        )
        group = plan.create_group(
            web.conn,
            self.org_id,
            self.brand_id,
            campaign["id"],
            name="USD group",
            role="new",
            daily_budget=100,
        )
        for day in (24, 25, 26):
            outcome_seed.seed_day(
                web.conn,
                self.org_id,
                self.brand_id,
                campaign["id"],
                "group",
                group["id"],
                date(2026, 10, day),
                spend=100,
                purchases=5,
                revenue=1000,
                currency="USD",
            )
        outcome_seed.set_coverage(
            web.conn,
            self.org_id,
            self.brand_id,
            campaign["id"],
            date(2026, 10, 24),
            date(2026, 10, 26),
        )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}"
        performance = self.client.get(f"{base}/performance")
        closed = self.client.post(f"{base}/close", json={})
        self.assertEqual(performance.status_code, 200, performance.text)
        self.assertEqual(closed.status_code, 200, closed.text)
        print(
            "CAP_CURRENCY_RECEIPT",
            json.dumps({"performance": performance.json(), "closed": closed.json()}),
        )
        with self.subTest(consumer="period_grade"):
            self.assertEqual(performance.json()["totals"]["grade"]["grade"], "insufficient")
        with self.subTest(consumer="closeout"):
            self.assertEqual(closed.json()["campaign"]["verdict"], "看不出")
        with self.subTest(consumer="window"):
            self.assertEqual(
                closed.json()["campaign"]["verdict_json"]["window"],
                {"start": "2026-10-24", "end": "2026-10-26"},
            )
            self.assertEqual(closed.json()["campaign"]["verdict_json"]["sample"]["days"], 3)

    def test_public_own_scalar_cap_keeps_priority_but_unknown_unit_cannot_claim_achieved(self):
        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24),
            end_date=date(2026, 10, 30),
            cap=100,
        )
        group = detail["groups"][0]
        for day in (24, 25, 26):
            outcome_seed.seed_day(
                web.conn,
                self.org_id,
                self.brand_id,
                detail["id"],
                "group",
                group["id"],
                date(2026, 10, day),
                spend=100,
                purchases=5,
                revenue=1000,
                currency="USD",
            )
        outcome_seed.set_coverage(
            web.conn,
            self.org_id,
            self.brand_id,
            detail["id"],
            date(2026, 10, 24),
            date(2026, 10, 26),
        )
        web.conn.commit()
        account = {
            "account_id": outcome_seed.SOURCE_ACCOUNT,
            "timezone_name": "Asia/Taipei",
            "currency": "USD",
        }
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
        with patch.object(_SeedAccount, "accounts", return_value=[account]):
            performance = self.client.get(f"{base}/performance")
            closed = self.client.post(f"{base}/close", json={})
        self.assertEqual(performance.status_code, 200, performance.text)
        self.assertEqual(closed.status_code, 200, closed.text)
        print(
            "OWN_CAP_UNIT_PUBLIC_RECEIPT",
            json.dumps(
                {
                    "performance": performance.json(),
                    "closed": closed.json(),
                }
            ),
        )
        self.assertEqual(closed.json()["campaign"]["cap"]["basis"], "own")
        self.assertEqual(closed.json()["campaign"]["cap"]["value"], 100)
        with self.subTest(consumer="grade"):
            self.assertEqual(performance.json()["totals"]["grade"]["grade"], "insufficient")
        with self.subTest(consumer="close"):
            self.assertEqual(closed.json()["campaign"]["verdict"], "看不出")
        with self.subTest(consumer="basis"):
            self.assertEqual(performance.json()["cap_comparison"]["reason"], "cap_currency_unknown")

    def test_inclusive_period_boundaries_known_zero_today_future_and_missing_dates_are_distinct(
        self,
    ):
        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24), end_date=date(2026, 10, 25)
        )
        group = detail["groups"][0]
        for day in (23, 24, 25, 26, 27, 31):
            outcome_seed.seed_day(
                web.conn,
                self.org_id,
                self.brand_id,
                detail["id"],
                "group",
                group["id"],
                date(2026, 10, day),
                spend=100,
                purchases=0,
                revenue=0,
            )
        web.conn.commit()
        base = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"
        result = self.client.get(f"{base}/performance").json()
        self.assertEqual([row["day"] for row in result["daily"]], ["2026-10-24", "2026-10-25"])
        self.assertEqual(result["totals"]["spend"], 200)
        self.assertEqual(result["totals"]["purchases"], 0)
        self.assertEqual(result["totals"]["revenue"], 0)
        self.assertEqual(result["totals"]["roas_all_spend"], 0)
        self.assertIsNone(result["totals"]["cpa"])
        self.assertEqual(
            len(outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "group")), 6
        )
        for start, end, state in (
            (date(2026, 10, 27), date(2026, 10, 30), "future"),
            (None, None, "missing_dates"),
        ):
            with self.subTest(state=state):
                unknown = ads_repo.create_campaign(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    {
                        "name": state,
                        "goal_text": "Missing completed scope",
                        "objective": "購買",
                        "start_date": start,
                        "end_date": end,
                        "target_cost": 100,
                    },
                    created_by=ACTOR,
                )
                web.conn.commit()
                data = self.client.get(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{unknown['id']}/performance"
                ).json()
                self.assertEqual(data["scope"]["state"], state)
                self.assertIsNone(data["totals"]["spend"])
                self.assertIsNone(data["totals"]["purchases"])
                self.assertEqual(data["daily"], [])

    def test_real_account_reader_failure_uses_existing_conservative_cutoff_and_preserves_history(
        self,
    ):
        from app.ads.adapters.external import SourceReadError

        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24), end_date=date(2026, 10, 30)
        )
        group = detail["groups"][0]
        for day in (24, 25, 26, 27):
            outcome_seed.seed_day(
                web.conn,
                self.org_id,
                self.brand_id,
                detail["id"],
                "group",
                group["id"],
                date(2026, 10, day),
                spend=100,
                purchases=1,
                revenue=200,
            )
        external_repository.record_sync(
            web.conn,
            self.org_id,
            self.brand_id,
            detail["id"],
            section="observations",
            state={"status": "error", "error": "fixture account unreadable"},
        )
        web.conn.commit()
        with patch.object(
            _SeedAccount, "accounts", side_effect=SourceReadError("fixture unreadable")
        ):
            response = self.client.get(
                f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/performance"
            )
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
        self.assertEqual(data["scope"]["end"], "2026-10-25")
        self.assertEqual(data["scope"]["day_basis"], "conservative_org_fallback")
        self.assertIsNone(data["scope"]["account_timezone"])
        self.assertEqual(data["totals"]["spend"], 200)
        self.assertEqual(
            len(outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "group")), 4
        )

    def test_account_day_differs_from_org_day_and_null_spend_is_not_zero(self):
        detail, _, _ = self._bound_campaign(
            start_date=date(2026, 10, 24), end_date=date(2026, 10, 30)
        )
        group = detail["groups"][0]
        for day in (24, 25, 26):
            outcome_seed.seed_day(
                web.conn,
                self.org_id,
                self.brand_id,
                detail["id"],
                "group",
                group["id"],
                date(2026, 10, day),
                spend=None if day == 25 else 100,
                purchases=1,
                revenue=200,
            )
        web.conn.commit()
        account = {
            "account_id": outcome_seed.SOURCE_ACCOUNT,
            "timezone_name": "America/New_York",
            "currency": "TWD",
        }
        with (
            patch.object(coredb, "now_utc", return_value=datetime(2026, 10, 27, 2, tzinfo=UTC)),
            patch.object(_SeedAccount, "accounts", return_value=[account]),
        ):
            response = self.client.get(
                f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/performance"
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["scope"]["end"], "2026-10-25")
        self.assertEqual(data["scope"]["account_timezone"], "America/New_York")
        self.assertEqual(data["scope"]["day_basis"], "account_timezone")
        self.assertEqual(data["scope"]["reason"], "spend_unknown")
        self.assertIsNone(data["totals"]["spend"])
        self.assertEqual(data["daily"][0]["spend"], 100)
        self.assertIsNone(data["daily"][1]["spend"])
        self.assertEqual(
            len(outcome.rows(web.conn, self.org_id, self.brand_id, detail["id"], "group")), 3
        )


def test_owned_metadata_reaches_real_coverage_and_keeps_frozen_last_day(monkeypatch):
    from datetime import UTC, date, datetime
    from types import SimpleNamespace
    from typing import Any, cast
    from zoneinfo import ZoneInfo

    from app.ads import channels, external_sync, outcome
    from app.core import db, settings
    from app.tests.fixtures.ads_external import outcome_seed
    from scripts.drill import first_release_acceptance as runner

    context = {"org_id": "owned-org", "brand_id": "owned-brand"}
    original = object()
    monkeypatch.setattr(
        channels, "external_reader", lambda platform: original if platform == "meta" else None
    )
    monkeypatch.setattr(db, "now_utc", lambda: datetime(2026, 8, 1, 4, tzinfo=UTC))
    monkeypatch.setattr(settings, "org_timezone", lambda *a, **k: ZoneInfo("Asia/Taipei"))

    class Connection:
        def execute(self, query, parameters):
            assert parameters == ("owned-org", "owned-brand", "campaign")
            return SimpleNamespace(fetchone=lambda: {
                "platform": outcome_seed.PLATFORM, "source_account": outcome_seed.SOURCE_ACCOUNT,
            })

    conn = cast(Any, Connection())
    campaign = {"id": "campaign", "start_date": date(2026, 7, 1), "end_date": date(2026, 7, 31)}
    observation = {
        "day": date(2026, 7, 31), "spend": 400, "purchases": 2, "revenue": None,
        "impressions": 1000, "clicks": 30, "currency": "TWD",
        "attribution_key": "fixed-known-fixture",
    }
    before = outcome.period_projection(
        conn, "owned-org", "owned-brand", campaign, [observation], []
    )
    assert before["scope"]["end"] == "2026-07-30"
    assert before["scope"]["day_basis"] == "conservative_org_fallback"
    assert before["scope"]["account_timezone"] is None
    assert before["totals"]["spend"] is None
    runner.install_owned_outcome_reader(context)
    reader, account = external_sync.account_reader(
        conn, "owned-org", "owned-brand", outcome_seed.PLATFORM, outcome_seed.SOURCE_ACCOUNT
    )
    assert account == {"account_id": "test", "currency": "TWD", "timezone_name": "Asia/Taipei"}
    assert not hasattr(reader, "read_observations")
    assert channels.external_reader("meta") is original
    assert channels.external_reader("unknown") is None
    after = outcome.period_projection(conn, "owned-org", "owned-brand", campaign, [observation], [])
    assert after["scope"]["end"] == "2026-07-31"
    assert after["scope"]["day_basis"] == "account_timezone"
    assert after["scope"]["account_timezone"] == "Asia/Taipei"
    assert after["scope"]["account_currency"] == "TWD"
    assert after["totals"]["spend"] == 400
    assert after["totals"]["purchases"] == 2
    assert after["totals"]["cpa"] == 200
    assert observation["day"] == date(2026, 7, 31)


@pytest.mark.parametrize("org,brand,account", [
    ("other-org", "owned-brand", "test"),
    ("owned-org", "other-brand", "test"),
    ("owned-org", "owned-brand", "other-account"),
])
def test_owned_metadata_refuses_foreign_account_binding(monkeypatch, org, brand, account):
    from app.ads import channels, external_sync
    from app.ads.adapters.external import SourceReadError
    from scripts.drill import first_release_acceptance as runner

    monkeypatch.setattr(channels, "external_reader", lambda platform: None)
    runner.install_owned_outcome_reader({"org_id": "owned-org", "brand_id": "owned-brand"})
    with pytest.raises(SourceReadError):
        external_sync.account_reader(None, org, brand, "test", account)


if __name__ == "__main__":
    unittest.main()
