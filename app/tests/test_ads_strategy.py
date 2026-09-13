"""app/tests/test_ads_strategy.py — F03-I05 falsifiers: with a fake provider returning
percentages, the persisted allocation amounts sum exactly to the chosen scenario total (proves the
model never does arithmetic); a learning's text reaches both the prompt sent to the provider and
`basis.learnings`; no learnings produces an empty `basis.learnings` with no fabricated sentence; a
stale price is marked stale in `basis`; a provider failure returns a readable error and leaves the
campaign in `draft` with no half-written strategy.
"""

import json
import unittest
from datetime import timedelta
from uuid import uuid4

import app.shared.web as web
from app.ads import budget, plan, strategy
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.llm import providers
from app.meta import repository as meta_repo

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": f"offer_{tag}",
        "format": f"format_{tag}",
    }


_VALID_PLAN_REPLY = json.dumps({
    "groups": [
        {"role": "new", "name": "新客組", "ads": [
            {"name": "新客-廣告一", "coordinates": _coordinates("new1")},
        ]},
        {"role": "retarget", "name": "再行銷組", "ads": [
            {"name": "再行銷-廣告一", "coordinates": _coordinates("rt1")},
        ]},
        {"role": "explore", "name": "探索組", "ads": [
            {"name": "探索-廣告一", "coordinates": _coordinates("ex1")},
        ]},
    ],
}, ensure_ascii=False)


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


class ScenarioAmountUnknownTest(StrategyTestBase):
    """F04-I25: `scenario_unknown`（情境鍵不存在）跟 `scenario_amount_unknown`
    （情境存在但算不出金額）是兩件事，不准共用同一個錯誤碼。"""

    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)
        detail = self._generate()
        budget_basis_json = dict(detail["budget_basis_json"])
        scenarios = dict(budget_basis_json["scenarios"])
        scenarios["scenarios"] = [
            {**row, "daily": None, "total": None} for row in scenarios["scenarios"]
        ]
        budget_basis_json["scenarios"] = scenarios
        ads_repo.save_strategy(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            budget_basis_json=budget_basis_json,
        )

    def test_scenario_with_null_amount_raises_scenario_amount_unknown(self):
        with self.assertRaises(ValueError) as ctx:
            strategy.select_scenario(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                scenario_key="recommended", actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "scenario_amount_unknown")

    def test_unknown_scenario_key_still_raises_scenario_unknown(self):
        with self.assertRaises(ValueError) as ctx:
            strategy.select_scenario(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                scenario_key="nope", actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "scenario_unknown")

    def test_custom_total_still_works_when_scenario_amounts_are_unknown(self):
        detail = strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key="custom", custom_total=28000, actor=ACTOR,
        )
        self.assertEqual(detail["budget_planned"], 28000)


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


_DUPLICATE_ROLE_REPLY = json.dumps({
    "allocation": [
        {"role": "new", "label": "新客 A", "pct": 40, "rationale": "x"},
        {"role": "new", "label": "新客 B", "pct": 40, "rationale": "x"},
        {"role": "explore", "label": "探索", "pct": 20, "rationale": "x"},
    ],
    "why": [], "unknowns": [], "alternatives": [],
}, ensure_ascii=False)


class DuplicateRoleTest(StrategyTestBase):
    def test_reply_with_duplicate_role_raises_strategy_failed(self):
        """F03-I19：`plan.adopt_strategy` 用 role 當 key 塞金額，同一個 role 出現兩次會讓
        其中一列的金額悄悄消失，group 日預算加總就會少於 budget_planned——即使百分比加總到
        100，也不能讓這個分配活到採用那一步。"""
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_DUPLICATE_ROLE_REPLY)

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
        self.assertEqual(history["source"], "ads_loop")

    def _connect_and_bind_account(self, account_id: str) -> str:
        meta_repo.save_token(web.conn, self.org_id, "tok")
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": account_id, "name": account_id, "currency": "TWD"},
        ])
        web.conn.commit()
        local_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, self.org_id)
            if a["account_id"] == account_id
        )
        meta_repo.bind(web.conn, self.org_id, self.brand_id, local_id)
        web.conn.commit()
        return local_id

    def test_no_loop_history_falls_back_to_bound_account_recent_spend(self):
        """F05-I11／演練四 V-13：迴圈自己沒有已結案花費，但品牌綁了廣告帳戶且帳戶近 30 天
        有真花費——退回讀帳戶歷史，不是誤判成沒投放過。"""
        account_id = self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        for offset, spend in ((5, 300), (10, 600)):
            meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [{
                "level": "campaign", "entity_id": "camp-1", "entity_name": "camp-1",
                "campaign_id": "camp-1", "adset_id": None, "ad_id": None,
                "spend_date": today - timedelta(days=offset), "spend": spend,
                "impressions": 100, "clicks": 10, "roas": None,
                "actions": None, "action_values": None,
                "attribution_window": "7d_click,1d_view",
            }])
        web.conn.commit()

        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)
        self.assertIsNotNone(history)
        self.assertEqual(history["source"], "meta_account")
        self.assertEqual(history["last_daily_budget"], round(900 / 30))
        self.assertIsNone(history["cpa"])  # 沒追蹤到轉換事件，不是 0
        self.assertEqual(history["sample_days"], 30)
        self.assertIsNone(history["sample_ads"])

    def test_bound_account_with_zero_recent_spend_is_still_cold_start(self):
        """帳戶接了，但 30 天內沒有任何花費——誠實冷啟動，不假裝有歷史。"""
        self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self.assertIsNone(ads_repo.budget_history(web.conn, self.org_id, self.brand_id))


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


class PromptCapsTest(StrategyTestBase):
    """F04-I03: prompt 別傾印——45 條事實只送前 20 條（新到舊）、25 條學習只送前 10 條；
    `basis` 只收真的進 prompt 的那些筆數；prompt 裡不再帶「更新於」。"""

    def test_facts_and_learnings_are_capped_and_basis_matches_the_prompt(self):
        for i in range(45):
            bi_repo.create_brand_fact(
                web.conn, self.brand_id, actor=ACTOR, fact_type="other",
                label=f"事實{i}", value=f"值{i}", status="confirmed", confirmed_by=ACTOR,
            )
        for i in range(25):
            bi_repo.record_learning(
                web.conn, self.brand_id, actor=ACTOR, learning_text=f"學習{i}",
                applicability_scope="brand", confidence="likely", sample_size="1 個活動",
            )
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        detail = self._generate()

        sent_prompt = provider.calls[0]["messages"][0]["content"]
        self.assertNotIn("更新於", sent_prompt)
        self.assertIn("（另有 25 筆較舊的品牌事實沒有列出）", sent_prompt)

        basis = detail["budget_basis_json"]["basis"]
        self.assertEqual(len(basis["brand_facts"]), 20)
        self.assertEqual(len(basis["learnings"]), 10)


class LabelFilledByProgramTest(StrategyTestBase):
    def test_reply_without_label_gets_label_filled_from_role(self):
        reply = json.dumps({
            "allocation": [
                {"role": "new", "pct": 50, "rationale": "打平 CPA 還沒驗證過新客"},
                {"role": "retarget", "pct": 30, "rationale": "有過去購買資料"},
                {"role": "explore", "pct": 20, "rationale": "測試新素材角度"},
            ],
            "why": [], "unknowns": [], "alternatives": [],
        }, ensure_ascii=False)
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(reply)

        detail = self._generate()

        allocation = detail["budget_basis_json"]["strategy"]["allocation"]
        self.assertEqual(allocation[0]["label"], "新客")


_REPLY_WITH_4_LEARNING_GOALS = json.dumps({
    "allocation": [
        {"role": "new", "label": "新客", "pct": 50, "rationale": "打平 CPA 還沒驗證過新客"},
        {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": "有過去購買資料"},
        {"role": "explore", "label": "探索", "pct": 20, "rationale": "測試新素材角度"},
    ],
    "why": [], "unknowns": [], "alternatives": [],
    "learning_goals": ["問題一", "問題二", "問題三", "問題四"],
}, ensure_ascii=False)


class LearningGoalsTest(StrategyTestBase):
    def test_more_than_3_learning_goals_are_truncated_to_3(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_REPLY_WITH_4_LEARNING_GOALS)

        detail = self._generate()

        learning_goals = detail["budget_basis_json"]["strategy"]["learning_goals"]
        self.assertEqual(len(learning_goals), 3)
        self.assertEqual(learning_goals, ["問題一", "問題二", "問題三"])

    def test_reply_without_learning_goals_yields_empty_list_and_keeps_old_shape(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

        detail = self._generate()

        strategy_payload = detail["budget_basis_json"]["strategy"]
        self.assertEqual(strategy_payload["learning_goals"], [])
        self.assertEqual(len(strategy_payload["allocation"]), 3)


class SetAllocationTest(StrategyTestBase):
    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()
        strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key="custom", custom_total=30000, actor=ACTOR,
        )

    def test_amounts_sum_exactly_and_rationale_is_unchanged(self):
        detail = strategy.set_allocation(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            allocation=[
                {"role": "new", "pct": 50}, {"role": "retarget", "pct": 30},
                {"role": "explore", "pct": 20},
            ],
            actor=ACTOR,
        )
        allocation = detail["budget_basis_json"]["strategy"]["allocation"]
        self.assertEqual(sum(item["amount"] for item in allocation), 30000)
        by_role = {item["role"]: item for item in allocation}
        self.assertEqual(by_role["new"]["rationale"], "打平 CPA 還沒驗證過新客")

    def test_bad_sum_raises_allocation_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            strategy.set_allocation(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                allocation=[
                    {"role": "new", "pct": 50}, {"role": "retarget", "pct": 30},
                    {"role": "explore", "pct": 10},
                ],
                actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "allocation_invalid")

    def test_after_plan_adopted_raises_plan_already_adopted(self):
        orig_plan_provider = plan.PROVIDER
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        try:
            plan.adopt_strategy(
                web.conn, self.org_id, self.brand_id, self.campaign["id"], actor=ACTOR,
            )
        finally:
            plan.PROVIDER = orig_plan_provider

        with self.assertRaises(ValueError) as ctx:
            strategy.set_allocation(
                web.conn, self.org_id, self.brand_id, self.campaign["id"],
                allocation=[
                    {"role": "new", "pct": 50}, {"role": "retarget", "pct": 30},
                    {"role": "explore", "pct": 20},
                ],
                actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "plan_already_adopted")


class ProductsSectionSellWaysTest(StrategyTestBase):
    """F05-I02: knowledge groups by mother product, money stays per sell way
    (ARCHITECTURE.md §8 item 1)."""

    def setUp(self):
        super().setUp()
        self.mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)

    def _sell_way(self, name: str, price: int) -> dict:
        child = bi_repo.create_product(
            web.conn, self.brand_id, name=f"薑黃錠 · {name}", actor=ACTOR,
            parent_id=self.mother["id"],
        )
        bi_repo.save_product_economics(
            web.conn, self.brand_id, child["id"], actor=ACTOR,
            selling_price=price, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=100, shipping_cost=50,
        )
        return child

    def test_one_fact_block_and_three_priced_sell_ways(self):
        a = self._sell_way("單瓶", 1200)
        b = self._sell_way("3 入組", 3200)
        c = self._sell_way("5 入組", 5000)
        product_ids = [a["id"], b["id"], c["id"]]

        text, basis = strategy._products_section(
            web.conn, self.org_id, self.brand_id, product_ids)

        self.assertEqual(text.count("事實："), 1)
        self.assertIn("單瓶 NT$1200", text)
        self.assertIn("3 入組 NT$3200", text)
        self.assertIn("5 入組 NT$5000", text)
        self.assertEqual(len(basis), 3)
        self.assertEqual({b["product_id"] for b in basis}, set(product_ids))

    def test_nine_sell_ways_capped_at_eight_with_overflow_note(self):
        product_ids = [self._sell_way(f"賣法{i}", 100 + i)["id"] for i in range(9)]

        text, basis = strategy._products_section(
            web.conn, self.org_id, self.brand_id, product_ids)

        self.assertIn("另有 1 種賣法沒有列出", text)
        self.assertEqual(len(basis), 8)

    def test_sell_way_without_economics_still_prints_no_price_data(self):
        priced = self._sell_way("單瓶", 1200)
        unpriced = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 隨身包", actor=ACTOR,
            parent_id=self.mother["id"],
        )

        text, basis = strategy._products_section(
            web.conn, self.org_id, self.brand_id, [priced["id"], unpriced["id"]])

        self.assertIn("隨身包 沒有價格資料", text)
        self.assertEqual(len(basis), 1)


class BudgetUsesFirstSellWayForMotherProductTest(StrategyTestBase):
    def test_campaign_on_mother_product_computes_from_first_sell_way(self):
        mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        first = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR, parent_id=mother["id"])
        bi_repo.save_product_economics(
            web.conn, self.brand_id, first["id"], actor=ACTOR,
            selling_price=1200, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=200, shipping_cost=50,
        )

        economics, product_id = budget._economics_for(
            web.conn, self.brand_id, [mother["id"]])

        self.assertIsNotNone(economics)
        self.assertEqual(product_id, first["id"])


if __name__ == "__main__":
    unittest.main()
