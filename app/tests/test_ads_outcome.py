"""app/tests/test_ads_outcome.py — F03-I11 falsifiers: spend on a bound entity lands on the
right campaign day; spend on an unbound/unmatched entity lands nowhere; two campaigns bound to
the same external id makes the ingest refuse and names both; a day with no data returns nothing
(never a fabricated 0) and the summary's totals read as 未追蹤 (`None`) rather than 0; the sample
bucket boundaries (9/10, 49/50, 2 days/3 days) are exact; the ingest endpoint on a simulated
campaign adds the missing days and on a bound (Meta) campaign does not call the simulator.
"""

import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import outcome, plan
from app.ads import repository as ads_repo
from app.ads.adapters import manual as manual_adapter
from app.ads.adapters import simulated
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo

ACTOR = "測試員"

_COORDINATES = {
    "audience": "aud", "pain": "pain", "angle": "angle", "hook": "hook", "proof": "proof",
    "offer": "offer", "format": "format",
}


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

    # -- 手動配對到 Meta 的一支已綁定 Campaign（一個投放組、一支廣告） -------------------------

    def _connect_account(self) -> str:
        """跟 `test_ads_publish_manual.py::PublishTestBase._connect_account` 同一套，但每次
        呼叫都造一個新的假帳號——`meta_entity_spend` 是照 `org_id + ad_account_id` 存的，不是
        照品牌，用固定字串會讓不同測試互相看到對方的花費列。"""
        meta_repo.save_token(web.conn, self.org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": external_id, "name": "測試廣告帳號", "currency": "TWD"},
        ])
        row = next(a for a in meta_repo.list_accounts(web.conn, self.org_id)
                   if a["account_id"] == external_id)
        meta_repo.bind(web.conn, self.org_id, self.brand_id, row["id"])
        web.conn.commit()
        self._account_ext = external_id
        self._account_row_id = row["id"]
        return row["id"]  # ad_account_id（`daily_entity_spend` 要的是這個內部 id）

    def _bound_campaign(self, *, start_date=None, end_date=None) -> tuple[dict, str, str]:
        """回傳 (campaign_detail, group_external_id, ad_external_id)，campaign/group/ad 三層
        都已經精準名稱比對綁定完成（跟 `test_ads_publish_manual.py::FullMatchTest` 同一套）。
        每個平台實體 id 都是這次呼叫自己造的（`uuid`），不同測試、不同 Campaign 之間不會撞名。
        """
        start_date = start_date or self.today
        end_date = end_date or self.today
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": f"測試 Campaign {uuid.uuid4().hex[:6]}", "goal_text": "幫產品衝購買",
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": 500, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }, created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = plan.adopt_strategy(web.conn, self.org_id, self.brand_id, campaign["id"],
                                      actor=ACTOR)

        account_ext = getattr(self, "_account_ext", None)
        if account_ext is None:
            self._connect_account()
            account_ext = self._account_ext
        tag = uuid.uuid4().hex[:8]
        campaign_ext, group_ext, ad_ext = f"camp-{tag}", f"as-{tag}", f"ad-{tag}"

        def fake_list_campaigns(_token, account_id):
            return [{"campaign_id": campaign_ext, "name": detail["name"],
                      "effective_status": "ACTIVE"}] if account_id == account_ext else []

        def fake_list_ad_sets(_token, campaign_id):
            group_name = detail["groups"][0]["name"]
            return [{"adset_id": group_ext, "name": group_name,
                      "external_status": "ACTIVE"}] if campaign_id == campaign_ext else []

        def fake_list_ads(_token, adset_id):
            ad_name = detail["groups"][0]["ads"][0]["name"]
            return [{"ad_id": ad_ext, "name": ad_name,
                      "external_status": "ACTIVE"}] if adset_id == group_ext else []

        with mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns), \
                mock.patch.object(meta_graph, "list_ad_sets", fake_list_ad_sets), \
                mock.patch.object(meta_graph, "list_ads", fake_list_ads):
            result = manual_adapter.bind(
                web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
            )
        self.assertIsNone(result["message"])
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(reloaded["local_state"], "bound")
        return reloaded, group_ext, ad_ext

    def _spend_row(self, *, level: str, entity_id: str, campaign_ext: str, day: date,
                   spend: float, roas: float | None, adset_id: str | None = None,
                   ad_id: str | None = None) -> dict:
        return {
            "level": level, "entity_id": entity_id, "entity_name": entity_id,
            "campaign_id": campaign_ext, "adset_id": adset_id, "ad_id": ad_id,
            "spend_date": day, "spend": spend, "impressions": 1000, "clicks": 20, "roas": roas,
            "actions": None, "action_values": None, "attribution_window": "7d_click,1d_view",
        }

    def _outcome_rows(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_outcome_daily WHERE campaign_id = %s ORDER BY entity_kind, day",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class SpendLandsOnTheRightCampaignTest(OutcomeTestBase):
    def test_spend_on_a_bound_entity_lands_on_its_campaign_day(self):
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id  # `_bound_campaign` 裡已經接過了

        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=500.0, roas=2.0, adset_id=group_ext),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        rows = self._outcome_rows(detail["id"])
        group_rows = [r for r in rows if r["entity_kind"] == "group"]
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(group_rows[0]["day"], self.today)
        self.assertEqual(float(group_rows[0]["spend"]), 500.0)
        self.assertEqual(group_rows[0]["source"], "meta")
        self.assertEqual(float(group_rows[0]["revenue"]), 1000.0)  # roas(2.0) x spend(500)


class UnboundSpendLandsNowhereTest(OutcomeTestBase):
    def test_spend_on_an_unmatched_entity_is_not_invented_into_the_campaign(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id

        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id="as-someone-elses", campaign_ext="camp-1",
                             day=self.today, spend=999.0, roas=1.5, adset_id="as-someone-elses"),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        self.assertEqual(self._outcome_rows(detail["id"]), [])


class ConflictingBindingRefusesTest(OutcomeTestBase):
    def test_two_campaigns_bound_to_the_same_external_id_refuses_naming_both(self):
        detail_a, group_ext, _ad_ext = self._bound_campaign()
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign_b = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "第二個 Campaign", "goal_text": "另一個活動", "objective": "購買",
            "success_metric": "cpa", "success_target": 300, "start_date": self.today,
            "end_date": self.today, "status": "draft", "budget_planned": 500,
            "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }, created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail_b = plan.adopt_strategy(web.conn, self.org_id, self.brand_id, campaign_b["id"],
                                        actor=ACTOR)
        # 直接把 B 的投放組綁到跟 A 同一個平台實體——模擬綁定資料本身壞掉，不是走真的比對。
        ads_repo.bind_group(
            web.conn, self.org_id, self.brand_id, detail_b["groups"][0]["id"],
            external_id=group_ext, external_name="撞名", external_status="ACTIVE",
        )
        web.conn.commit()

        with self.assertRaises(ValueError) as ctx:
            outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail_a["id"],
                                 start=self.today, end=self.today + timedelta(days=1))
        message = str(ctx.exception)
        self.assertIn(detail_a["name"], message)
        self.assertIn("第二個 Campaign", message)


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
        detail, group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=1), end_date=self.today,
        )
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today - timedelta(days=1), spend=400.0, roas=3.0,
                             adset_id=group_ext),
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=600.0, roas=1.0, adset_id=group_ext),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today - timedelta(days=1),
                             end=self.today + timedelta(days=1))
        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNotNone(result["totals"]["roas"])
        self.assertIsNotNone(result["totals"]["roas_conservative"])
        # 兩者都是拿 (400x3 + 600x1) = 1800 除，分母都是 1000（全部花費都有追蹤到 roas），
        # 這個情境下兩個值理當相等——但都要是數字，不是 None。
        self.assertAlmostEqual(result["totals"]["roas"], 1.8)
        self.assertAlmostEqual(result["totals"]["roas_conservative"], 1.8)


class SampleBucketBoundaryTest(unittest.TestCase):
    def test_boundaries_are_exact(self):
        self.assertEqual(outcome.sample_bucket(9, 5), "低")
        self.assertEqual(outcome.sample_bucket(10, 5), "中")
        self.assertEqual(outcome.sample_bucket(49, 5), "中")
        self.assertEqual(outcome.sample_bucket(50, 5), "高")
        self.assertEqual(outcome.sample_bucket(100, 2), "低")  # 天數不夠，購買數再高也是低
        self.assertEqual(outcome.sample_bucket(100, 3), "高")


class IngestEndpointDispatchTest(OutcomeTestBase):
    def test_simulated_campaign_ingest_adds_the_missing_day_without_touching_meta(self):
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "模擬 Campaign", "goal_text": "測試模擬 ingest", "objective": "購買",
            "success_metric": "cpa", "success_target": 300,
            "start_date": self.today - timedelta(days=1), "end_date": self.today,
            "status": "draft",
        }, created_by=ACTOR)
        group = plan.create_group(
            web.conn, self.org_id, self.brand_id, campaign["id"], name="投放組",
            role="new", daily_budget=500,
        )
        plan.create_ad(
            web.conn, self.org_id, self.brand_id, campaign["id"], group["id"], name="廣告",
            coordinates=_COORDINATES,
        )
        simulated.publish(web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR)
        web.conn.execute(
            "DELETE FROM ads_outcome_daily WHERE campaign_id = %s AND day = %s",
            (campaign["id"], self.today),
        )
        web.conn.commit()
        self.assertEqual(
            [r for r in self._outcome_rows(campaign["id"])
             if r["entity_kind"] == "group" and r["day"] == self.today],
            [],
        )

        with mock.patch.object(meta_repo, "daily_entity_spend") as fake_pull:
            resp = self.client.post(
                f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/ingest",
            )
            self.assertEqual(resp.status_code, 200)
            fake_pull.assert_not_called()

        self.assertTrue(any(
            r["entity_kind"] == "group" and r["day"] == self.today
            for r in self._outcome_rows(campaign["id"])
        ))

    def test_bound_meta_campaign_ingest_does_not_call_the_simulator(self):
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=250.0, roas=2.0, adset_id=group_ext),
        ])
        web.conn.commit()

        with mock.patch.object(simulated, "generate_outcomes") as fake_generate:
            resp = self.client.post(
                f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}/ingest",
            )
            self.assertEqual(resp.status_code, 200)
            fake_generate.assert_not_called()

        rows = [r for r in self._outcome_rows(detail["id"]) if r["source"] == "meta"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["spend"]), 250.0)


if __name__ == "__main__":
    unittest.main()
