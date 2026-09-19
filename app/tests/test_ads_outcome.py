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
from pathlib import Path
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

    def _bound_campaign(self, *, start_date=None, end_date=None, success_metric="cpa",
                         success_target=300) -> tuple[dict, str, str]:
        """回傳 (campaign_detail, group_external_id, ad_external_id)，campaign/group/ad 三層
        都已經精準名稱比對綁定完成（跟 `test_ads_publish_manual.py::FullMatchTest` 同一套）。
        每個平台實體 id 都是這次呼叫自己造的（`uuid`），不同測試、不同 Campaign 之間不會撞名。
        `success_metric`／`success_target` 預設跟原本一樣，F16-I05 的結案整合測試需要判
        `purchases` 才覆寫。"""
        start_date = start_date or self.today
        end_date = end_date or self.today
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": f"測試 Campaign {uuid.uuid4().hex[:6]}", "goal_text": "幫產品衝購買",
            "objective": "購買", "success_metric": success_metric,
            "success_target": success_target,
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
                   ad_id: str | None = None, purchases: int | None = None,
                   revenue: float | None = None, action_type: str = "omni_purchase") -> dict:
        """F16-I05：`purchases` 給定時才長出 `actions`／`action_values`——真實形狀（`action_type`
        跟它配對的 `value`），不是憑空塞一個數字進 `ads_outcome_daily`。預設 `None` 保留舊有
        呼叫端「這一列沒有購買同義字」的行為不變。"""
        actions = (
            None if purchases is None
            else [{"action_type": action_type, "value": str(purchases)}]
        )
        action_values = (
            None if purchases is None or revenue is None
            else [{"action_type": action_type, "value": str(revenue)}]
        )
        return {
            "level": level, "entity_id": entity_id, "entity_name": entity_id,
            "campaign_id": campaign_ext, "adset_id": adset_id, "ad_id": ad_id,
            "spend_date": day, "spend": spend, "impressions": 1000, "clicks": 20, "roas": roas,
            "actions": actions, "action_values": action_values,
            "attribution_window": "7d_click,1d_view",
        }

    def _outcome_rows(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_outcome_daily WHERE campaign_id = %s ORDER BY entity_kind, day",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _insert_row(self, campaign_id: str, entity_id: str, day: date, *, spend: float,
                     purchases: int | None, revenue: float | None,
                     source: str = "simulated") -> None:
        """F16-I01：直接灌一列進 `ads_outcome_daily`——用來組「一部分列有追蹤、一部分沒有」
        的情境，`ingest_meta`／模擬 adapter 目前都不會產生這種混合，但欄位本身允許（nullable），
        讀者（`_bucket`）要能正確處理。"""
        web.conn.execute(
            "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
            " entity_id, day, spend, impressions, clicks, purchases, revenue, source)"
            " VALUES (%s, %s, %s, %s, 'group', %s, %s, %s, 100, 10, %s, %s, %s)",
            (coredb.new_id("ado"), self.org_id, self.brand_id, campaign_id, entity_id, day,
             spend, purchases, revenue, source),
        )
        web.conn.commit()


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
        # F16-I05：revenue 只認 action_values，不再從 roas 反推——這一列只給了 roas，沒有任何
        # 購買同義字，revenue／purchases 都該是未追蹤（None），不是拿 roas(2.0) x spend(500) 造
        # 出一個看起來有根據、其實沒被 Meta 標記為購買事件的數字。
        self.assertIsNone(group_rows[0]["purchases"])
        self.assertIsNone(group_rows[0]["revenue"])


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
        # F16-I05：revenue 現在只認 action_values，不是 roas——兩天各給一個真的購買同義字
        # 跟它的 value，總營收 1800／總花費 1000，跟原本靠 roas 反推的假設值保持一致，只是
        # 換成真的來源。
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today - timedelta(days=1), spend=400.0, roas=3.0,
                             adset_id=group_ext, purchases=1, revenue=1200.0),
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=600.0, roas=1.0, adset_id=group_ext,
                             purchases=1, revenue=600.0),
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


class MetaIngestWritesUntrackedNotZeroTest(OutcomeTestBase):
    """F16-I01/F16-I05：這一列的 `actions` 裡沒有任何購買同義字（`roas=None` 也沒有一個對得上
    `graph._ROAS_ACTION_PRIORITY` 的 action_type），`ingest_meta` 寫的是 `NULL`（未追蹤），
    不是看起來像數字的 `0`。"""

    def test_meta_row_purchases_is_null_and_revenue_null_without_a_purchase_action(self):
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=500.0, roas=None, adset_id=group_ext),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        rows = self._outcome_rows(detail["id"])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["purchases"])
        self.assertIsNone(rows[0]["revenue"])

    def test_meta_row_with_a_tracked_zero_purchase_action_stores_zero_not_none(self):
        """一個 purchase 同義字真的回報了、值是 0——追蹤到的真零，不是「沒有這個 key」。"""
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=500.0, roas=None, adset_id=group_ext,
                             purchases=0, revenue=0.0),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        rows = self._outcome_rows(detail["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["purchases"], 0)
        self.assertEqual(float(rows[0]["revenue"]), 0.0)

    def test_meta_row_with_a_real_purchase_action_stores_the_real_count_and_revenue(self):
        """真實形狀（`omni_purchase`＋它的 `value`）——不是拿 roas 反推。"""
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=500.0, roas=None, adset_id=group_ext,
                             purchases=6, revenue=6000.0),
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        rows = self._outcome_rows(detail["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["purchases"], 6)
        self.assertAlmostEqual(float(rows[0]["revenue"]), 6000.0, places=2)


class TrackedZeroUntrackedAndRealCountSumOnlyKnownTest(OutcomeTestBase):
    """F16-I01：一個 group 底下三天——一天未追蹤（`NULL`）、一天追蹤到真的零、一天追蹤到真的
    非零——加總只算有追蹤到的那兩天，`5`，不是把未追蹤那天當 0 灌進去（結果會一樣是 5，但如果
    真的把它當 0 算，這裡改成任何非 5 的數字都能抓到迴歸）；未追蹤那天存在，不是完全沒有列。"""

    def test_bucket_sums_only_tracked_days_never_coercing_null_to_zero(self):
        detail, group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=2), end_date=self.today,
        )
        group_id = detail["groups"][0]["id"]
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=2),
                          spend=100.0, purchases=None, revenue=None, source="meta")
        self._insert_row(detail["id"], group_id, self.today - timedelta(days=1),
                          spend=100.0, purchases=0, revenue=0.0, source="simulated")
        self._insert_row(detail["id"], group_id, self.today,
                          spend=100.0, purchases=5, revenue=500.0, source="simulated")

        result = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertEqual(result["totals"]["purchases"], 5)
        self.assertEqual(result["totals"]["revenue"], 500.0)
        self.assertEqual(len(result["daily"]), 3)


class OutcomeTotalsReturnsNullNotZeroWhenAllUnknownTest(OutcomeTestBase):
    def test_outcome_totals_purchases_and_revenue_are_none_when_every_row_is_meta_untracked(self):
        detail, group_ext, _ad_ext = self._bound_campaign()
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today, spend=500.0, roas=None, adset_id=group_ext),
        ])
        web.conn.commit()
        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today, end=self.today + timedelta(days=1))

        # `campaign_detail`'s `outcome` key is `_outcome_totals`'s return value verbatim for an
        # internal (non-imported) campaign — going through the public read keeps this a
        # black-box check of the same contract `list_campaigns`/`campaign_detail` ship.
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        totals = detail["outcome"]

        self.assertEqual(totals["row_count"], 1)
        self.assertEqual(float(totals["spend"]), 500.0)
        self.assertIsNone(totals["purchases"])
        self.assertIsNone(totals["revenue"])


class LegacyMetaZeroNormalisedReadsAsUnknownTest(OutcomeTestBase):
    """F16-I01 repair: pre-F16 `ingest_meta` wrote `purchases=0`/`revenue=0` unconditionally
    for every Meta-sourced row — those literals never recorded an observation. Migration
    `20260920000002_ads_outcome_legacy_meta_unknown.sql` normalises that legacy shape to
    `NULL`; this proves a row normalised that way reads as unknown (`None`), never as a real
    counted zero, in both `_outcome_totals` (via `outcome.summary`) and campaign detail — the
    exact contradiction the repair fixes now that `_bucket` keys on `IS NOT NULL` instead of
    `source != 'meta'`. Runs the actual migration file (not a re-derived statement) so a change
    to its SQL is what this test is checking."""

    def test_legacy_meta_zero_row_normalised_by_migration_reads_as_unknown(self):
        detail, _group_ext, _ad_ext = self._bound_campaign()
        group_id = detail["groups"][0]["id"]
        # 灌一列跟舊版 `ingest_meta` 一樣的形狀：Meta 來源、purchases/revenue 都是字面 0，
        # 從來沒有代表過一次真的觀測。
        self._insert_row(detail["id"], group_id, self.today, spend=500.0,
                          purchases=0, revenue=0.0, source="meta")

        migration_path = (
            Path(__file__).resolve().parents[2] / "supabase" / "migrations"
            / "20260920000002_ads_outcome_legacy_meta_unknown.sql"
        )
        sql_lines = (
            line for line in migration_path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("--")
        )
        for statement in "\n".join(sql_lines).split(";"):
            statement = statement.strip()
            if not statement:
                continue
            web.conn.execute(statement)
        web.conn.commit()

        totals = outcome.summary(web.conn, self.org_id, self.brand_id, detail["id"])["totals"]
        self.assertIsNone(totals["purchases"])
        self.assertIsNone(totals["revenue"])

        campaign_detail = ads_repo.campaign_detail(
            web.conn, self.org_id, self.brand_id, detail["id"],
        )
        self.assertIsNone(campaign_detail["outcome"]["purchases"])
        self.assertIsNone(campaign_detail["outcome"]["revenue"])


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


class RealMetaPurchasesReachCloseoutTest(OutcomeTestBase):
    """F16-I05: a real, bound Meta campaign — three days of `meta_entity_spend` rows built from
    the real jsonb shape (`omni_purchase` synonym, matching `action_values`) — passes the sample
    gate (>=10 purchases, >=3 days) and closes as 達成 or 未達成, never 看不出. Before this
    issue, `daily_entity_spend` never returned a purchase count, so `ingest_meta` always wrote
    `NULL` and every Meta-sourced campaign closed as 看不出 regardless of real performance."""

    def test_bound_campaign_with_real_purchase_actions_closes_as_achieved(self):
        from app.ads import closeout

        detail, group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=2), end_date=self.today,
            success_metric="purchases", success_target=8,
        )
        account_id = self._account_row_id
        # 三天各 4 個真的購買（omni_purchase，跟真實資料同一組同義字），合計 12 >= target(8)、
        # 也 >= 樣本門檻(10)，天數 3 天 >= 3——樣本門檻通過，不是「看不出」。
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today - timedelta(days=i), spend=400.0, roas=None,
                             adset_id=group_ext, purchases=4, revenue=4000.0)
            for i in range(3)
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today - timedelta(days=2),
                             end=self.today + timedelta(days=1))

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["actual"], 12)
        self.assertEqual(closed["verdict_json"]["sample_bucket"], "中")

    def test_bound_campaign_with_real_purchase_actions_below_target_closes_as_missed(self):
        from app.ads import closeout

        detail, group_ext, _ad_ext = self._bound_campaign(
            start_date=self.today - timedelta(days=2), end_date=self.today,
            success_metric="purchases", success_target=20,
        )
        account_id = self._account_row_id
        meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [
            self._spend_row(level="adset", entity_id=group_ext, campaign_ext="camp-1",
                             day=self.today - timedelta(days=i), spend=400.0, roas=None,
                             adset_id=group_ext, purchases=4, revenue=4000.0)
            for i in range(3)
        ])
        web.conn.commit()

        outcome.ingest_meta(web.conn, self.org_id, self.brand_id, detail["id"],
                             start=self.today - timedelta(days=2),
                             end=self.today + timedelta(days=1))

        closed = closeout.close(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)

        self.assertEqual(closed["verdict"], "未達成")
        self.assertEqual(closed["verdict_json"]["actual"], 12)


if __name__ == "__main__":
    unittest.main()
