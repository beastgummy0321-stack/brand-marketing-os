"""app/tests/test_ads_strategy.py — F03-I05 falsifiers: with a fake provider returning
percentages, the persisted allocation amounts sum exactly to the chosen scenario total (proves the
model never does arithmetic); a learning's text reaches both the prompt sent to the provider and
`basis.learnings`; no learnings produces an empty `basis.learnings` with no fabricated sentence; a
stale price is marked stale in `basis`; a provider failure returns a readable error and leaves the
campaign in `draft` with no half-written strategy.
"""

import json
import unittest

import app.shared.web as web
from app.ads import repository as ads_repo
from app.ads import strategy
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


_VALID_REPLY = json.dumps({
    "allocation": [
        {"role": "new", "label": "新客", "pct": 50, "rationale": "打平 CPA 還沒驗證過新客"},
        {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": "有過去購買資料"},
        {"role": "explore", "label": "探索", "pct": 20, "rationale": "測試新素材角度"},
    ],
    "why": ["依品牌事實與過去學習分配"],
    "unknowns": ["新受眾的實際轉換率"],
    "alternatives": [],
}, ensure_ascii=False)


class StrategyTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心策略", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        self.economics = bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product["id"], actor=ACTOR,
            selling_price=1000, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=300, shipping_cost=100,
        )
        self._orig_provider = strategy.PROVIDER

    def tearDown(self):
        strategy.PROVIDER = self._orig_provider

    def _create_campaign(self, **overrides) -> dict:
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫夜跑背心衝購買",
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-10", "status": "draft",
            "context_json": {"product_ids": [self.product["id"]]},
        }
        campaign.update(overrides)
        return ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, campaign, created_by=ACTOR,
        )

    def _generate(self):
        return strategy.generate(
            web.conn, self.org_id, self.brand_id, self.campaign["id"], actor=ACTOR,
        )


class AmountsSumToScenarioTotalTest(StrategyTestBase):
    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

    def test_generated_allocation_amounts_sum_to_recommended_scenario_total(self):
        detail = self._generate()
        strategy_payload = detail["budget_basis_json"]["strategy"]
        scenarios = detail["budget_basis_json"]["scenarios"]
        recommended = next(
            row for row in scenarios["scenarios"] if row["key"] == scenarios["recommended"]
        )
        total = sum(item["amount"] for item in strategy_payload["allocation"])
        self.assertEqual(total, recommended["total"])
        # 模型只回百分比，不回金額——回覆裡沒有 amount 這個鍵
        self.assertNotIn("amount", json.loads(_VALID_REPLY)["allocation"][0])

    def test_selecting_a_different_scenario_resplits_to_its_own_total(self):
        self._generate()
        detail = strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key="aggressive", actor=ACTOR,
        )
        strategy_payload = detail["budget_basis_json"]["strategy"]
        scenarios = detail["budget_basis_json"]["scenarios"]
        aggressive = next(row for row in scenarios["scenarios"] if row["key"] == "aggressive")
        total = sum(item["amount"] for item in strategy_payload["allocation"])
        self.assertEqual(total, aggressive["total"])
        self.assertEqual(detail["budget_planned"], aggressive["total"])
        self.assertEqual(detail["budget_scenario"], "aggressive")

    def test_custom_total_resplits_to_the_hand_typed_amount(self):
        self._generate()
        detail = strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key="custom", custom_total=12345, actor=ACTOR,
        )
        strategy_payload = detail["budget_basis_json"]["strategy"]
        total = sum(item["amount"] for item in strategy_payload["allocation"])
        self.assertEqual(total, 12345)
        self.assertEqual(detail["budget_planned"], 12345)


class LearningInPromptAndBasisTest(StrategyTestBase):
    def test_a_learning_reaches_both_the_prompt_and_the_basis(self):
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="再行銷受眾對折扣文案反應特別好", applicability_scope="brand",
            confidence="likely", sample_size="2 個活動",
        )
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        detail = self._generate()

        sent_prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("再行銷受眾對折扣文案反應特別好", sent_prompt)
        learnings = detail["budget_basis_json"]["basis"]["learnings"]
        self.assertEqual(len(learnings), 1)
        self.assertEqual(learnings[0]["text"], "再行銷受眾對折扣文案反應特別好")

    def test_no_learnings_yields_empty_basis_and_no_fabricated_sentence(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

        detail = self._generate()

        self.assertEqual(detail["budget_basis_json"]["basis"]["learnings"], [])


class StalePriceTest(StrategyTestBase):
    def test_a_stale_price_is_marked_stale_in_the_basis(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product["id"], actor=ACTOR,
            selling_price=800, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=250, shipping_cost=50,
            effective_from="2020-01-01", effective_to="2020-12-31",
        )
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

        detail = self._generate()

        prices = detail["budget_basis_json"]["basis"]["prices"]
        self.assertEqual(len(prices), 1)
        self.assertTrue(prices[0]["stale"])


_BAD_SUM_REPLY = json.dumps({
    "allocation": [
        {"role": "new", "label": "新客", "pct": 10, "rationale": "x"},
        {"role": "retarget", "label": "再行銷", "pct": 10, "rationale": "x"},
        {"role": "explore", "label": "探索", "pct": 10, "rationale": "x"},
    ],
    "why": [], "unknowns": [], "alternatives": [],
}, ensure_ascii=False)


class BadPctSumTest(StrategyTestBase):
    def test_pcts_summing_far_from_100_raises_strategy_failed(self):
        """`split()` 的餘數規則會把整個落差塞進佔比最大的一項——10/10/10 悄悄變成某一項
        拿到 80% 的錢，畫面卻還印著模型回的 10%（Re-cut item 1）。"""
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_BAD_SUM_REPLY)

        with self.assertRaises(ValueError) as ctx:
            self._generate()
        self.assertEqual(str(ctx.exception), "strategy_failed")


class AlreadyAdoptedTest(StrategyTestBase):
    def test_regenerating_after_budget_planned_is_set_is_refused(self):
        """再產生一次會照*推薦*情境重新 split，讓存的分配金額悄悄跟已採用的
        `budget_planned` 對不上（F03-I06 已經照 `budget_planned` 建過投放組，Re-cut item 2）。"""
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()
        strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key="recommended", actor=ACTOR,
        )

        with self.assertRaises(ValueError) as ctx:
            self._generate()
        self.assertEqual(str(ctx.exception), "strategy_already_adopted")


class CustomTotalInvalidTest(StrategyTestBase):
    def test_non_positive_custom_total_is_refused(self):
        """Re-cut item 3：`custom_total` 是 F03-I06 拿去除以 `days` 寫進
        `ads_delivery_group.daily_budget` 的數字，那欄沒有 CHECK，程式自己要擋住 <= 0。"""
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()

        with self.assertRaises(ValueError) as ctx:
            strategy.select_scenario(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                scenario_key="custom", custom_total=0, actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "custom_total_invalid")

        with self.assertRaises(ValueError) as ctx:
            strategy.select_scenario(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                scenario_key="custom", custom_total=-5, actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "custom_total_invalid")


class BudgetHistoryTest(StrategyTestBase):
    """Re-cut item 5：`budget_history` 的第一個 SQL 沒有花費資料時每個策略測試都提早 `None`
    回傳了，其餘三個查詢從沒被跑過——用一個結案過的 Campaign 直接組資料驗。"""

    def test_fresh_brand_has_no_history(self):
        self.assertIsNone(ads_repo.budget_history(web.conn, self.org_id, self.brand_id))

    def test_history_branch_computes_median_cpa_and_last_daily_budget(self):
        closed = self._create_campaign(status="closed")
        group = web.conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key,"
            " name, role, daily_budget) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            ("adg_test1", self.org_id, self.brand_id, closed["id"], "meta", "新客組", "new", 400),
        ).fetchone()
        web.conn.execute(
            "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name,"
            " local_state) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("ada_test1", self.org_id, self.brand_id, closed["id"], group["id"], "測試廣告",
             "bound"),
        )
        for day, spend, purchases in (("2026-10-01", 400, 2), ("2026-10-02", 600, 2)):
            web.conn.execute(
                "INSERT INTO ads_outcome_daily (id, org_id, brand_id, campaign_id, entity_kind,"
                " entity_id, day, spend, purchases, source) VALUES"
                " (%s, %s, %s, %s, 'group', %s, %s, %s, %s, 'simulated')",
                (f"ado_{day}", self.org_id, self.brand_id, closed["id"], group["id"], day,
                 spend, purchases),
            )
        web.conn.commit()

        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)
        self.assertIsNotNone(history)
        self.assertEqual(history["cpa"], 250)  # median(200, 300)
        self.assertEqual(history["last_daily_budget"], 400)
        self.assertEqual(history["sample_days"], 2)
        self.assertEqual(history["sample_ads"], 1)


class ProviderFailureTest(StrategyTestBase):
    def test_provider_failure_raises_and_leaves_campaign_without_a_strategy(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = providers.FakeProvider(
            exception=providers.ProviderTimeoutError("AI 服務逾時未回應，請再試一次。"),
        )

        with self.assertRaises(ValueError) as ctx:
            self._generate()
        self.assertEqual(str(ctx.exception), "strategy_failed")

        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["budget_basis_json"], {})


if __name__ == "__main__":
    unittest.main()
