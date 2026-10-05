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

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import ads_learnings, budget, change_control_launch, plan, strategy
from app.ads import external_repository as external
from app.ads import learning as ads_learning
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.llm import gateway, providers
from app.meta import repository as meta_repo
from app.tests.fixtures.ads_external import outcome_seed

from .identity_test_helpers import mint_hs256

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
            {"name": "新客-廣告一", "coordinates": _coordinates("new1"),
             "scene": "上班族午休在辦公室滑手機找點心"},
        ]},
        {"role": "retarget", "name": "再行銷組", "ads": [
            {"name": "再行銷-廣告一", "coordinates": _coordinates("rt1"),
             "scene": "看過商品頁的人晚上在家猶豫要不要下單"},
        ]},
        {"role": "explore", "name": "探索組", "ads": [
            {"name": "探索-廣告一", "coordinates": _coordinates("ex1"),
             "scene": "健身房的人運動完在櫃檯看補給品"},
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
    # F33-I01：`_VALID_REPLY` 分了 `retarget`，而 `retarget` 只在品牌有再行銷來源時才是可用
    # 角色（Contract P）——基底把精靈答案設成「投放過」讓既有測試的品牌合格；要測一個
    # 從沒投放過的品牌就把這個旗標關掉。
    ELIGIBLE = True

    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心策略", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        if self.ELIGIBLE:
            self.brand = bi_repo.set_advertising_history(
                web.conn, self.brand_id, "has_history", actor=ACTOR,
            )
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
            "objective": "購買", "target_cost": 300,
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

    def _assert_refusal(self, exc: Exception, code: str) -> None:
        """F50 Contract J: the refusal names its rule, keeps `strategy_failed` as `str()`, and is
        written on the judged task row."""
        assert isinstance(exc, plan.PlannerRefused)
        reason = strategy.REFUSALS[code]
        self.assertEqual((str(exc), exc.code, exc.reason), ("strategy_failed", code, reason))
        row = gateway.get_task(web.conn, exc.task_id)
        assert row is not None
        self.assertEqual((row["error_code"], row["error"]),
                         ("program_refused", f"{code}: {reason}"))


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
        # No own cap and no product -> no cap resolves, so every amount stays unknown.
        self.campaign = self._create_campaign(target_cost=None, context_json={"product_ids": []})
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

    def test_visual_track_learnings_never_leak_into_the_ads_prompt(self):
        """F07-I01：`learning_ledger` 有兩條軌（ads／visual），策略只讀 `ads`——視覺學習
        絕不能出現在投放策略的 prompt 或 basis 裡（ARCHITECTURE.md §3「兩條軌、一張表」）。"""
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="再行銷受眾對折扣文案反應特別好", applicability_scope="brand",
            confidence="likely", sample_size="2 個活動",
        )
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="手機原生抓拍風格轉換較高", applicability_scope="brand",
            confidence="likely", sample_size="3 張圖", source_track="visual",
        )
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        detail = self._generate()

        sent_prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("再行銷受眾對折扣文案反應特別好", sent_prompt)
        self.assertNotIn("手機原生抓拍風格轉換較高", sent_prompt)
        learnings = detail["budget_basis_json"]["basis"]["learnings"]
        texts = [row["text"] for row in learnings]
        self.assertIn("再行銷受眾對折扣文案反應特別好", texts)
        self.assertNotIn("手機原生抓拍風格轉換較高", texts)

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


class AssumptionNoteTest(StrategyTestBase):
    """F05-I12：使用者在精靈點過「不知道」的數字，策略頁的依據要看得出是假設值——句子由
    程式組，名稱與百分比一律從 `app.brand_intelligence.benchmarks` 取。"""

    def test_economics_with_assumptions_yields_a_note_naming_them(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product["id"], actor=ACTOR,
            selling_price=1000, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=300, shipping_cost=100, close_rate=20,
            assumptions=["close_rate"],
        )
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

        detail = self._generate()

        basis = detail["budget_basis_json"]["basis"]
        self.assertIn("assumption_note", basis)
        self.assertIn("假設", basis["assumption_note"])
        self.assertIn("成交率假設 20%", basis["assumption_note"])

    def test_economics_without_assumptions_has_no_note(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(_VALID_REPLY)

        detail = self._generate()

        basis = detail["budget_basis_json"]["basis"]
        self.assertNotIn("assumption_note", basis)


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
        self._assert_refusal(ctx.exception, "pct_invalid")


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
        self._assert_refusal(ctx.exception, "role_repeated")


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
            outcome_seed.seed_day(web.conn, self.org_id, self.brand_id, closed["id"], "group",
                                  group["id"], day, spend=spend, purchases=purchases,
                                  source="simulated")
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

    def _upsert_account_days(self, account_id: str, days: list[tuple[int, float]]) -> None:
        """`days` = [(offset_from_today, spend), ...] campaign-level rows on the bound account."""
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        for offset, spend in days:
            meta_repo.upsert_entity_spend(web.conn, self.org_id, account_id, [{
                "level": "campaign", "entity_id": "camp-1", "entity_name": "camp-1",
                "campaign_id": "camp-1", "adset_id": None, "ad_id": None,
                "spend_date": today - timedelta(days=offset), "spend": spend,
                "impressions": 100, "clicks": 10, "roas": None,
                "actions": None, "action_values": None,
                "attribution_window": "7d_click,1d_view",
            }])
        web.conn.commit()

    def test_no_loop_history_falls_back_to_bound_account_recent_spend(self):
        """F05-I11／演練四 V-13：迴圈自己沒有已結案花費，但品牌綁了廣告帳戶且帳戶近 30 天
        有真花費——退回讀帳戶歷史，不是誤判成沒投放過。F36-I05（演練六 #15，裁決 B）：
        分母是「有花費的天數」——只投 2 天（300＋600）的帳戶日均是 450，不是 900/30。"""
        account_id = self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self._upsert_account_days(account_id, [(5, 300), (10, 600)])

        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)
        self.assertIsNotNone(history)
        self.assertEqual(history["source"], "meta_account")
        self.assertEqual(history["last_daily_budget"], 450)
        self.assertIsNone(history["cpa"])  # 沒追蹤到轉換事件，不是 0
        self.assertEqual(history["sample_days"], 2)
        self.assertIsNone(history["sample_ads"])
        self.assertEqual(
            history["source_text"], "Meta 廣告帳戶全部活動，近 30 天有投放的 2 天平均日花費"
        )

    def test_account_history_caption_prints_source_text_unchanged(self):
        """F36-I05 #3: `budget._history_scenarios` prints `source_text` as-is — the day count
        lives there once; the caption must not re-add a 「30 天」 of its own."""
        account_id = self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self._upsert_account_days(account_id, [(5, 300), (10, 600)])
        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)

        scenarios = budget._history_scenarios(history, 14)
        captions = [row["caption"] for row in scenarios["scenarios"]]
        self.assertTrue(all(
            c.startswith("Meta 廣告帳戶全部活動，近 30 天有投放的 2 天平均日花費 NT$450 ×")
            for c in captions
        ), captions)
        self.assertTrue(all(c.count("30 天") == 1 for c in captions), captions)
        self.assertEqual(scenarios["basis"]["sample_days"], 2)

    def test_account_history_with_thirty_full_days_is_unchanged(self):
        """30 天窗每天都有花費 → 分母仍是 30，結果跟以前一模一樣（不是回歸）。"""
        account_id = self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self._upsert_account_days(account_id, [(offset, 100) for offset in range(30)])

        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)
        self.assertIsNotNone(history)
        self.assertEqual(history["last_daily_budget"], 100)
        self.assertEqual(history["sample_days"], 30)
        self.assertEqual(
            history["source_text"], "Meta 廣告帳戶全部活動，近 30 天有投放的 30 天平均日花費"
        )

    def test_bound_account_with_zero_recent_spend_is_still_cold_start(self):
        """帳戶接了，但 30 天內沒有任何花費——誠實冷啟動，不假裝有歷史。"""
        self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self.assertIsNone(ads_repo.budget_history(web.conn, self.org_id, self.brand_id))

    def test_bound_account_with_only_zero_spend_rows_is_still_cold_start(self):
        """F36-I05: rows exist but every day spent 0 — zero days with spend > 0 is「沒有歷史」,
        never a division by zero or a NT$0 base."""
        account_id = self._connect_and_bind_account(f"act_{uuid4().hex[:8]}")
        self._upsert_account_days(account_id, [(3, 0), (7, 0)])
        self.assertIsNone(ads_repo.budget_history(web.conn, self.org_id, self.brand_id))

    def test_null_purchases_day_excluded_from_median_and_sample_ads_never_treated_as_zero(self):
        """F16-I01 repair regression: a day where the group has no tracked purchases at all
        (`purchases IS NULL` — exactly the shape a normalised legacy Meta row or an
        untracked Meta day has) must be excluded from both the daily-CPA median and the
        `purchases > 0` sample-ads count, never coerced into a real counted zero. The untracked
        day below carries the largest spend on purpose: if `repository.py:463-495` regressed to
        `COALESCE(SUM(purchases), 0)` in the SQL or `float(row["purchases"] or 0)` in the
        median comprehension, this either crashes on division by the coerced zero or drags
        `sample_days`/`cpa` away from the two tracked days' own numbers — either way this test
        fails."""
        tag = uuid4().hex[:8]
        closed = self._create_campaign(status="closed")
        group = web.conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key,"
            " name, role, daily_budget) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (f"adg_{tag}", self.org_id, self.brand_id, closed["id"], "meta", "新客組", "new",
             400),
        ).fetchone()
        web.conn.execute(
            "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name,"
            " local_state) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (f"ada_{tag}", self.org_id, self.brand_id, closed["id"], group["id"], "測試廣告",
             "bound"),
        )
        outcome_seed.seed_day(web.conn, self.org_id, self.brand_id, closed["id"], "group",
                              group["id"], "2026-10-01", spend=5000, purchases=None,
                              source="meta")
        for day, spend, purchases in (("2026-10-02", 400, 2), ("2026-10-03", 600, 2)):
            outcome_seed.seed_day(web.conn, self.org_id, self.brand_id, closed["id"], "group",
                                  group["id"], day, spend=spend, purchases=purchases,
                                  source="simulated")
        web.conn.commit()

        history = ads_repo.budget_history(web.conn, self.org_id, self.brand_id)

        self.assertIsNotNone(history)
        self.assertEqual(history["sample_days"], 2)  # 未追蹤那天不算進去，只有兩天真的有追蹤
        self.assertEqual(history["cpa"], 250)  # median(200, 300)，跟未追蹤那天的大額花費無關
        self.assertEqual(history["sample_ads"], 1)  # 未追蹤那天不會讓廣告被誤算進樣本


class ProviderFailureTest(StrategyTestBase):
    def test_provider_failure_raises_and_leaves_campaign_without_a_strategy(self):
        self.campaign = self._create_campaign()
        strategy.PROVIDER = providers.FakeProvider(
            exception=providers.ProviderTimeoutError("AI 服務逾時未回應，請再試一次。"),
        )

        with self.assertRaises(ValueError) as ctx:
            self._generate()
        self.assertEqual(str(ctx.exception), "strategy_failed")
        assert isinstance(ctx.exception, plan.PlannerRefused)
        self.assertEqual(ctx.exception.code, "llm_failed")
        self.assertEqual(len(strategy.PROVIDER.calls), 1)  # a provider failure is not retried

        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["budget_basis_json"], {})


class PromptCapsTest(StrategyTestBase):
    """F04-I03: prompt 別傾印——45 條事實只送前 20 條（新到舊）、12 條學習只送前 10 條；
    `basis` 只收真的進 prompt 的那些筆數；prompt 裡不再帶「更新於」。F41-I02 之後每個商品只留
    最新一條期別判決；F48 Contract P 之後只讀這個賣法（與品牌層）的學習——所以上限用這個賣法
    的 12 條事件學習（`ads;` scope，各自獨立）來驗。"""

    def test_facts_and_learnings_are_capped_and_basis_matches_the_prompt(self):
        for i in range(45):
            bi_repo.create_brand_fact(
                web.conn, self.brand_id, actor=ACTOR, fact_type="positioning",
                label=f"事實{i}", value=f"值{i}", status="confirmed", confirmed_by=ACTOR,
            )
        for i in range(12):
            bi_repo.record_learning(
                web.conn, self.brand_id, actor=ACTOR, learning_text=f"學習{i}",
                applicability_scope=f"ads;event={i}", confidence="likely",
                sample_size="1 個活動", product_id=self.product["id"],
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

    def test_bundle_lists_every_component_products_facts_and_one_price_line(self):
        """F43-I02: a bundle's knowledge is its components' (`knowledge_product_ids`)."""
        fish_oil = bi_repo.create_product(web.conn, self.brand_id, name="魚油", actor=ACTOR)
        for product in (self.mother, fish_oil):  # F50 Contract R: a bundle takes ready products
            bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"],
                                         [{"who": "測試客群", "pain_keys": ["cost"]}], actor=ACTOR)
        for product, value in ((self.mother, "薑黃素 95%"), (fish_oil, "rTG 型態")):
            bi_repo.create_product_fact(
                web.conn, self.brand_id, product["id"], actor=ACTOR, fact_type="core_info",
                label="成分", value=value, status="confirmed", confirmed_by=ACTOR,
            )
        bases = [bi_repo.save_sell_way(web.conn, self.brand_id, name="單件", actor=ACTOR,
                                       product_id=product["id"],
                                       economics={"selling_price": 900})["id"]
                 for product in (self.mother, fish_oil)]
        bundle = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="保養雙入組", actor=ACTOR,
            components=[{"sell_way_id": base, "qty": 1} for base in bases],
            economics={"selling_price": 1800, "unit_variable_cost": 400, "shipping_cost": 60},
        )

        text, basis = strategy._products_section(
            web.conn, self.org_id, self.brand_id, [bundle["id"]])

        self.assertIn("- 薑黃錠｜事實：成分：薑黃素 95%", text)
        self.assertIn("- 魚油｜事實：成分：rTG 型態", text)
        self.assertEqual(text.count("賣法："), 1)
        self.assertIn("保養雙入組 NT$1800", text)
        self.assertEqual([row["product_id"] for row in basis], [bundle["id"]])


class CustomerGroupsInStrategyPromptTest(StrategyTestBase):
    """F43-I02: 【這個賣法的顧客】 sits after 【這個賣法】 (F48) and its group ids reach
    `basis.knowledge_item_ids`; a product without groups says so."""

    def _prompt(self) -> tuple[str, dict]:
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider
        detail = self._generate()
        return provider.calls[0]["messages"][0]["content"], detail

    def test_two_groups_reach_the_prompt_after_the_products_and_the_basis(self):
        groups = bi_repo.save_customer_groups(web.conn, self.brand_id, self.product["id"], [
            {"who": "下班後夜跑的上班族", "pain_keys": ["uncertainty"],
             "quote": "晚上跑步車子看不到我", "when_used": "下班後在河濱夜跑"},
            {"who": "帶小孩散步的爸媽", "pain_keys": ["effort", "cost"],
             "quote": "反光條一洗就掉", "when_used": "晚餐後推車散步"},
        ], actor=ACTOR)

        prompt, detail = self._prompt()

        self.assertIn(
            "【這個賣法的顧客】\n"
            "第 1 群：下班後夜跑的上班族｜煩惱：怕買錯（pain=uncertainty）"
            "｜顧客會說：晚上跑步車子看不到我｜什麼時候用：下班後在河濱夜跑\n"
            "第 2 群：帶小孩散步的爸媽｜煩惱：太麻煩（pain=effort）、太貴（pain=cost）"
            "｜顧客會說：反光條一洗就掉｜什麼時候用：晚餐後推車散步",
            prompt,
        )
        products_at = prompt.rindex("【這個賣法】")
        customers_at = prompt.rindex("【這個賣法的顧客】")
        learnings_at = prompt.rindex("【過去的學習】")
        self.assertLess(products_at, customers_at)
        self.assertLess(customers_at, learnings_at)
        knowledge_item_ids = detail["budget_basis_json"]["basis"]["knowledge_item_ids"]
        for group in groups:
            self.assertIn(group["id"], knowledge_item_ids)

    def test_product_without_groups_says_so(self):
        prompt, _ = self._prompt()
        self.assertIn("【這個賣法的顧客】（這個商品還沒有建顧客群）", prompt)


# F43-I04: `BudgetUsesFirstSellWayForMotherProductTest` (the parent -> first-sell-way fallback) was
# deleted with the fallback -- a campaign always carries a sell-way id; see
# `test_ads_budget_sell_way.py`.


class ScriptedReplyValidatesTest(StrategyTestBase):
    """形狀絆線（F06-I05）：`providers.SCRIPTED_REPLIES["ads_strategy"]` 必須通過
    `strategy.generate` 自己的驗證，e2e 才不會在這裡默默掉進 provider 失敗分支。"""

    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()
        strategy.PROVIDER = _fake(
            json.dumps(providers.SCRIPTED_REPLIES["ads_strategy"], ensure_ascii=False)
        )

    def test_scripted_reply_generates_and_saves_expected_roles(self):
        detail = self._generate()
        allocation = detail["budget_basis_json"]["strategy"]["allocation"]
        self.assertEqual([item["role"] for item in allocation], ["new", "retarget", "explore"])

    def test_scripted_prose_carries_no_number(self):
        """F48 Contract S: no digit, `%` or `NT$` in any prose of the scripted reply."""
        reply = providers.SCRIPTED_REPLIES["ads_strategy"]
        prose = [row["rationale"] for row in reply["allocation"]]
        for key in ("why", "unknowns", "alternatives", "learning_goals"):
            prose += reply[key]
        self.assertFalse(strategy._has_number(prose), prose)


if __name__ == "__main__":
    unittest.main()


class CurrentCpaScenariosTest(StrategyTestBase):
    def test_edit_refresh_and_selection_keep_adopted_amount(self):
        self.campaign = self._create_campaign(end_date="2026-10-14", target_cost=210)
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()
        strategy.select_scenario(web.conn, self.org_id, self.brand_id, self.campaign["id"],
                                 scenario_key="recommended", actor=ACTOR)
        ads_repo.save_campaign_target(web.conn, self.org_id, self.brand_id, self.campaign["id"],
                                      basis="own", value=300, expected_revision=0, actor=ACTOR)
        for _ in range(2):
            detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id,
                                              self.campaign["id"])
            assert detail is not None
            assert detail["budget_planned"] == 14700
            rows = detail["budget_basis_json"]["scenarios"]["scenarios"]
            assert [r["total"] for r in rows] == [8400, 21000, 42000]
            assert float(detail["budget_planned"]) / detail["cap"]["value"] == 49
        # Dropping the own cap falls back to break-even (1000 - 300 - 100 = 600) for the
        # projection only; the adopted amount never moves.
        ads_repo.save_campaign_target(web.conn, self.org_id, self.brand_id, self.campaign["id"],
                                      basis="break_even", expected_revision=1, actor=ACTOR)
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        assert detail is not None
        rows = detail["budget_basis_json"]["scenarios"]["scenarios"]
        assert [r["total"] for r in rows] == [16800, 42000, 84000]
        assert detail["budget_planned"] == 14700

    def test_prompt_names_the_one_cap(self):
        self.campaign = self._create_campaign(target_cost=450)
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider
        self._generate()
        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("上限（每筆購買成本）：450", prompt)
        self.assertNotIn("success_", prompt)


class CalendarInStrategyPromptTest(StrategyTestBase):
    """F33-I02（ruling 2A、Contract Q）：策略 prompt 帶【投放期間內的行事曆】，只列跟期間重疊
    的列——預設 Campaign 2026-10-01～10-10 跨國慶日；跨到表外的年份要有「沒有資料」的註記，
    不能安靜地變成空白。"""

    def _prompt(self, **overrides) -> str:
        self.campaign = self._create_campaign(**overrides)
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider
        self._generate()
        return provider.calls[0]["messages"][0]["content"]

    def test_prompt_lists_the_calendar_rows_overlapping_the_period(self):
        prompt = self._prompt()
        self.assertIn("【投放期間內的行事曆】\n", prompt)
        self.assertIn("國慶日", prompt)
        self.assertNotIn("雙 11 檔", prompt)
        self.assertNotIn("不要假設沒有活動", prompt)
        # 行事曆段落接在 F33-I01 的兩段之後（Contract P 的段落文字不動）；任務檔前面也提到
        # 這兩個標題，所以取最後一次出現的位置才是真正的段落。
        self.assertLess(prompt.rindex("【可用角色】"), prompt.rindex("【投放期間內的行事曆】"))

    def test_period_outside_the_table_gets_the_coverage_note(self):
        prompt = self._prompt(start_date="2028-03-01", end_date="2028-03-10")
        self.assertIn("【投放期間內的行事曆】\n期間內沒有登記的假日、考季或檔期\n", prompt)
        self.assertIn("2028 年的假日與考季沒有資料，不要假設沒有活動", prompt)


_RANKED_HEADER = "【上幾期的排名（程式排的；每筆＝花費÷成交）】"
_RANKED_EMPTY = "【上幾期的排名】（還沒有結案過的廣告）"


class RankedLearningsInStrategyPromptTest(StrategyTestBase):
    """F46-I04（Contract G／L）：策略 prompt 帶程式排好的【上幾期的排名】（取代【座標成績表】），
    接在【過去的學習】之後；`basis.coordinate_scoreboard` 列出它用到的學習列 id，
    `basis.ranked_learnings` 存它 prompt 用的那份 view（查看策略依據＝模型真的看過的），
    不再寫 `basis.coordinate_learnings`。顧客群用這次的【這個賣法的顧客】編號。排名列是
    closeout 寫的 `v=2` 列——這裡直接用公開的 `record_learning` 種一列。"""

    def _seed_scoreboard(self) -> dict:
        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'audience','aud_last','陌生・知道問題')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        closed = self._create_campaign(
            name="上一期 Campaign", start_date="2026-09-01", end_date="2026-09-10",
            status="closed",
        )
        group = plan.create_group(
            web.conn, self.org_id, self.brand_id, closed["id"], name="上一期新客組", role="new",
            daily_budget=500,
        )
        ad = plan.create_ad(
            web.conn, self.org_id, self.brand_id, closed["id"], group["id"], name="上一期-免運",
            coordinates=_coordinates("last"),
        )
        (self.customer_group,) = bi_repo.save_customer_groups(
            web.conn, self.brand_id, self.product["id"],
            [{"who": "下班後夜跑的上班族", "pain_keys": ["effort"]}], actor=ACTOR,
        )
        keys = _coordinates("last")
        scope = (
            "coord；v=2；verdict=keep；rank=1；of=1；sales=6；spend=1200；cpr=200；cap=300；few=0"
            f"；group={self.customer_group['id']}；"
            + "；".join(
                f"{dim}={keys[dim]}"
                for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format")
            )
            + "；cur=TWD"
        )
        web.conn.execute("UPDATE ads_campaign SET closed_at = now() WHERE id = %s",
                         (closed["id"],))
        return bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="第 1／1 名「上一期-免運」每筆 200", applicability_scope=scope,
            confidence="observed", sample_size="高",
            source_cycle_id=f"{closed['id']}:{ad['id']}", source_track="coordinate",
        )

    def _generate_and_capture(self) -> tuple[str, dict]:
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider
        detail = self._generate()
        return provider.calls[0]["messages"][0]["content"], detail

    def test_scoreboard_reaches_the_prompt_and_the_basis(self):
        learning = self._seed_scoreboard()
        prompt, detail = self._generate_and_capture()

        self.assertIn(_RANKED_HEADER, prompt)
        self.assertIn(
            "- 顧客群 第 1 群（下班後夜跑的上班族）｜1 則廣告｜賣 6 筆｜花 1,200｜每筆 200"
            "｜上限 300", prompt,
        )
        self.assertIn(
            "- 上一期 Campaign第 1／1 名｜留下｜顧客群 1｜「上一期-免運」｜每筆 200｜賣 6 筆"
            "｜花 1,200｜陌生・知道問題（audience=aud_last）、",
            prompt,
        )
        self.assertNotIn("座標成績表", prompt)
        # 段落接在【過去的學習】之後、預算情境之前；任務檔前面也提到【上幾期的排名】，取最後一次。
        self.assertLess(prompt.rindex("【過去的學習】"), prompt.rindex(_RANKED_HEADER))
        self.assertLess(prompt.rindex(_RANKED_HEADER), prompt.rindex("【程式算好的預算情境"))
        basis = detail["budget_basis_json"]["basis"]
        self.assertEqual(basis["coordinate_scoreboard"], [learning["id"]])
        self.assertIn(learning["id"], basis["knowledge_item_ids"])
        # 排名列不是句子學習：`basis.learnings` 仍然只讀 `ads` 軌。
        self.assertEqual(basis["learnings"], [])
        self.assertNotIn("coordinate_learnings", basis)
        # The stored view is the one the prompt was built from.
        ranked = basis["ranked_learnings"]
        (campaign_view,) = ranked["campaigns"]
        self.assertEqual(campaign_view["campaign_name"], "上一期 Campaign")
        self.assertEqual(campaign_view["rule_text"], "1 則每筆低於上限 300 → 留下；其餘換掉")
        (row,) = campaign_view["rows"]
        self.assertEqual(
            {k: row[k] for k in ("rank", "of", "ad_name", "verdict", "verdict_label",
                                 "cost_per_sale", "sales", "spend", "customer_group")},
            {"rank": 1, "of": 1, "ad_name": "上一期-免運", "verdict": "keep",
             "verdict_label": "留下", "cost_per_sale": 200, "sales": 6, "spend": 1200,
             "customer_group": {"id": self.customer_group["id"], "who": "下班後夜跑的上班族"}},
        )
        self.assertEqual(
            row["coordinates"][0],
            {"dimension": "audience", "dimension_label": "受眾", "key": "aud_last",
             "label": "陌生・知道問題"},
        )
        self.assertEqual(ranked["groups"][0]["who"], "下班後夜跑的上班族")

    def test_empty_brand_says_there_is_nothing_ranked(self):
        prompt, detail = self._generate_and_capture()

        self.assertIn(_RANKED_EMPTY, prompt)
        self.assertNotIn(_RANKED_HEADER, prompt)
        basis = detail["budget_basis_json"]["basis"]
        self.assertEqual(basis["coordinate_scoreboard"], [])
        self.assertEqual(basis["ranked_learnings"], {"campaigns": [], "groups": [], "next": None})
        self.assertNotIn("coordinate_learnings", basis)

    def test_the_department_file_builds_on_kept_ads_by_name(self):
        text = strategy.DEPARTMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("`rationale` 要點名這次建立在哪幾則「留下」的廣告上", text)
        self.assertIn("不再用的「換掉」那一群＋角度", text)
        self.assertNotIn("座標成績表", text)


class OneCurrentLearningPerProductTest(StrategyTestBase):
    """F41-I02 (drill-8 #11): two closed periods' verdicts for the same sell-way -> only the newer
    reaches the prompt and `basis.learnings`; a campaign without a sell-way (imported) is one
    brand-level row. Event learnings (`ads;` scope: pause／A/B／month settle) are separate
    findings and all stay. F48-I03 (Contract W): every row here is written by the production
    writers (`learning.write_learning`, `ads_learnings.record_for_ab_item`), which store the
    campaign's sell-way themselves -- so two sell-ways keep two verdicts, and F48 Contract P
    prints only this campaign's sell-way's (plus brand-level ones) to its planner."""

    @staticmethod
    def _verdict_json(actual: float) -> dict:
        return {"target": 300.0, "actual": actual,
                "sample": {"purchases": 6, "days": 10, "bucket": "中"}}

    def _close(self, campaign: dict, verdict: str, actual: float) -> dict:
        return ads_learning.write_learning(
            web.conn, self.org_id, self.brand_id, campaign["id"], verdict,
            self._verdict_json(actual), actor=ACTOR,
        )

    def test_only_the_newest_verdict_per_sell_way_reaches_prompt_and_basis(self):
        other = bi_repo.create_product(web.conn, self.brand_id, name="登山背心", actor=ACTOR)
        imported_old = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="舊帳戶・上一季",
        )
        imported_new = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="舊帳戶・這一季",
        )
        old_a = self._create_campaign(name="夜跑背心・第一期")
        new_a = self._create_campaign(name="夜跑背心・第二期")
        only_b = self._create_campaign(
            name="登山背心・第一期", context_json={"product_ids": [other["id"]]},
        )
        ab = {"dimension_label": "開場", "winner": {"value_label": "甲"},
              "loser": {"value_label": "乙"}}

        rows = {
            "imported_old": self._close(imported_old, "未達成", 500.0),
            "old_a": self._close(old_a, "未達成", 400.0),
            "event_a": ads_learnings.record_for_ab_item(
                web.conn, self.org_id, self.brand_id, old_a["id"],
                {"plan_json": {"source": "ab", "ab": ab}}, {"id": "adx-ab-1", "kind": "pause"},
            ),
            "imported_new": self._close(imported_new, "達成", 280.0),
            "new_a": self._close(new_a, "達成", 250.0),
            "only_b": self._close(only_b, "達成", 260.0),
        }
        # The writers stored each campaign's sell-way (nothing here passes `product_id`).
        self.assertEqual({key: row["product_id"] for key, row in rows.items()}, {
            "imported_old": None, "old_a": self.product["id"], "event_a": self.product["id"],
            "imported_new": None, "new_a": self.product["id"], "only_b": other["id"],
        })

        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        detail = self._generate()

        sent_prompt = provider.calls[0]["messages"][0]["content"]
        for kept in ("new_a", "imported_new", "event_a"):
            self.assertIn(rows[kept]["learning_text"], sent_prompt)
        # F48 Contract P: another sell-way's verdict never reaches this sell-way's planner.
        for dropped in ("old_a", "imported_old", "only_b"):
            self.assertNotIn(rows[dropped]["learning_text"], sent_prompt)
        texts = [row["text"] for row in detail["budget_basis_json"]["basis"]["learnings"]]
        self.assertEqual(texts, [
            rows["new_a"]["learning_text"], rows["imported_new"]["learning_text"],
            rows["event_a"]["learning_text"],
        ])


class DepartmentNamesCoordinatesByLabelTest(unittest.TestCase):
    def test_the_department_file_forbids_coordinate_keys_in_owner_sentences(self):
        text = strategy.DEPARTMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("座標一律用中文名稱，不寫英文代碼", text)

    def test_the_department_file_names_the_group_each_role_targets(self):
        text = strategy.DEPARTMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("每個角色的 `rationale` 要點名這個角色打的是哪一群", text)


class BudgetCapSelectionTest(StrategyTestBase):
    """F28-I03: a total above the budget cap (`constraints_json.budget`) is saved only with an
    explicit confirmation, which is recorded; within the cap, or with no cap, as before.
    Cap 300 x 2/5/10 x 10 days -> 6000 / 15000 / 30000."""

    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign(constraints_json={"budget": 20000})
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()

    def _select(self, key, **kwargs):
        return strategy.select_scenario(
            web.conn, self.org_id, self.brand_id, self.campaign["id"],
            scenario_key=key, actor=ACTOR, **kwargs,
        )

    def _planned(self):
        row = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        assert row is not None
        return row

    def test_over_cap_without_confirmation_is_refused_with_the_amount(self):
        with self.assertRaises(strategy.OverCapUnconfirmed) as ctx:
            self._select("aggressive")
        self.assertEqual(str(ctx.exception), "over_cap_unconfirmed")
        self.assertEqual((ctx.exception.total, ctx.exception.cap, ctx.exception.over),
                         (30000, 20000, 10000))
        self.assertIsNone(self._planned()["budget_planned"])

    def test_confirmed_over_cap_is_saved_and_recorded(self):
        detail = self._select("aggressive", confirm_over_cap=True)
        self.assertEqual(detail["budget_planned"], 30000)
        confirmation = detail["budget_basis_json"]["over_cap_confirmation"]
        self.assertEqual({k: confirmation[k] for k in ("by", "total", "cap", "over")},
                         {"by": ACTOR, "total": 30000, "cap": 20000, "over": 10000})
        self.assertTrue(confirmation["at"])
        row = next(r for r in detail["budget_basis_json"]["scenarios"]["scenarios"]
                   if r["key"] == "aggressive")
        self.assertEqual(row["over_cap"], 10000)

    def test_custom_total_over_cap_needs_the_same_confirmation(self):
        with self.assertRaises(strategy.OverCapUnconfirmed):
            self._select("custom", custom_total=20001)
        detail = self._select("custom", custom_total=20001, confirm_over_cap=True)
        self.assertEqual(detail["budget_planned"], 20001)
        self.assertEqual(detail["budget_basis_json"]["over_cap_confirmation"]["over"], 1)

    def test_within_cap_and_the_cap_row_need_no_confirmation(self):
        self._select("aggressive", confirm_over_cap=True)
        detail = self._select("recommended")
        self.assertEqual(detail["budget_planned"], 15000)
        self.assertNotIn("over_cap_confirmation", detail["budget_basis_json"])
        detail = self._select("cap")
        self.assertEqual(detail["budget_planned"], 20000)
        self.assertEqual(detail["budget_scenario"], "cap")

    def test_no_cap_behaves_as_before(self):
        self.campaign = self._create_campaign()
        self._generate()
        detail = self._select("aggressive")
        self.assertEqual(detail["budget_planned"], 30000)
        self.assertIsNone(detail["budget_basis_json"]["scenarios"]["budget_cap"])
        self.assertNotIn("over_cap_confirmation", detail["budget_basis_json"])

    def test_generated_allocation_splits_the_cap_when_the_recommendation_is_over(self):
        self.campaign = self._create_campaign(constraints_json={"budget": 12000})
        detail = self._generate()
        scenarios = detail["budget_basis_json"]["scenarios"]
        self.assertEqual(scenarios["recommended"], "cap")
        allocation = detail["budget_basis_json"]["strategy"]["allocation"]
        self.assertEqual(sum(item["amount"] for item in allocation), 12000)


class BudgetCapRoutesTest(StrategyTestBase):
    """F28-I03 HTTP contract: 409 `over_cap_unconfirmed`, and `PUT .../strategy/budget-cap`
    (user ruling 2026-09-25: editable after the wizard, in any status, internal only)."""

    def setUp(self):
        self.client = TestClient(main.app)
        user = uuid4()
        token = mint_hs256(sub=str(user), email=f"adscap-{user.hex[:8]}@example.com")
        self.headers = {"Authorization": f"Bearer {token}"}
        org_id = self.client.get("/api/identity/me", headers=self.headers).json()["org"]["id"]
        self._orig_provider = strategy.PROVIDER
        self.org_id = org_id
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=org_id, name="測試品牌：預算上限", client_name=None, actor=ACTOR,
        )["id"]
        # F33-I01：`_VALID_REPLY` 帶 `retarget`，品牌要先合格（同 `StrategyTestBase`）。
        bi_repo.set_advertising_history(
            web.conn, self.brand_id, "has_history", actor=ACTOR,
        )
        self.product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        self.campaign = self._create_campaign(constraints_json={"budget": 20000})
        strategy.PROVIDER = _fake(_VALID_REPLY)
        self._generate()
        web.conn.commit()

    def _url(self, suffix: str = "", campaign_id: str | None = None) -> str:
        cid = campaign_id or self.campaign["id"]
        return f"/api/ads/brands/{self.brand_id}/campaigns/{cid}{suffix}"

    def _put(self, body, campaign_id: str | None = None):
        return self.client.put(
            self._url("/strategy/budget-cap", campaign_id), json=body, headers=self.headers,
        )

    def _read(self) -> dict:
        response = self.client.get(self._url(), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["campaign"]

    def _choose(self, key: str, **extra):
        return self.client.post(
            self._url("/strategy/scenario"), json={"scenario_key": key, **extra},
            headers=self.headers,
        )

    def test_scenario_over_cap_is_409_until_confirmed(self):
        response = self._choose("aggressive")
        self.assertEqual(response.status_code, 409, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "over_cap_unconfirmed")
        self.assertIn("10,000", error["message"])
        response = self._choose("aggressive", confirm_over_cap=True)
        self.assertEqual(response.status_code, 200, response.text)
        campaign = response.json()["campaign"]
        self.assertEqual(campaign["budget_planned"], 30000)
        self.assertEqual(campaign["budget_basis_json"]["over_cap_confirmation"]["over"], 10000)

    def test_set_and_clear_the_cap(self):
        response = self._put({"budget_cap": 25000})
        self.assertEqual(response.status_code, 200, response.text)
        campaign = response.json()["campaign"]
        self.assertEqual(campaign["constraints_json"]["budget"], 25000)
        self.assertEqual(campaign["context_json"]["field_sources"]["budget"], "user")
        self.assertEqual(campaign["budget_basis_json"]["scenarios"]["budget_cap"], 25000)

        response = self._put({"budget_cap": None})
        self.assertEqual(response.status_code, 200, response.text)
        campaign = response.json()["campaign"]
        self.assertNotIn("budget", campaign["constraints_json"])
        scenarios = campaign["budget_basis_json"]["scenarios"]
        self.assertIsNone(scenarios["budget_cap"])
        self.assertNotIn("cap", [r["key"] for r in scenarios["scenarios"]])

    def test_invalid_values_are_422_and_change_nothing(self):
        for body in ({"budget_cap": 0}, {"budget_cap": -5}, {"budget_cap": 1.5},
                     {"budget_cap": "100"}, {"budget_cap": True}, {}):
            with self.subTest(body=body):
                response = self._put(body)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["code"], "budget_cap_invalid")
        self.assertEqual(self._read()["constraints_json"]["budget"], 20000)

    def test_saved_scenario_now_over_the_cap_stays_saved_and_shows_over(self):
        self.assertEqual(self._choose("recommended").status_code, 200)
        before = self._read()
        response = self._put({"budget_cap": 12000})
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()["campaign"]
        self.assertEqual(after["budget_planned"], 15000)
        self.assertEqual(after["budget_scenario"], "recommended")
        self.assertEqual(after["budget_basis_json"]["strategy"],
                         before["budget_basis_json"]["strategy"])
        scenarios = after["budget_basis_json"]["scenarios"]
        row = next(r for r in scenarios["scenarios"] if r["key"] == "recommended")
        self.assertEqual(row["over_cap"], 3000)
        self.assertEqual(scenarios["recommended"], "cap")

    def test_non_draft_campaign_cap_is_editable_and_the_launch_snapshot_is_unchanged(self):
        self.assertEqual(self._choose("recommended").status_code, 200)
        orig_plan_provider = plan.PROVIDER
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        try:
            adopted = self.client.post(self._url("/plan"), headers=self.headers)
        finally:
            plan.PROVIDER = orig_plan_provider
        self.assertEqual(adopted.status_code, 200, adopted.text)
        self.assertEqual(adopted.json()["campaign"]["status"], "ready")
        snapshot_before = change_control_launch.snapshot(
            web.conn, self.org_id, self.brand_id, self.campaign["id"])

        response = self._put({"budget_cap": 9000})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["campaign"]["status"], "ready")
        self.assertEqual(response.json()["campaign"]["budget_planned"], 15000)
        self.assertEqual(
            change_control_launch.snapshot(
                web.conn, self.org_id, self.brand_id, self.campaign["id"]),
            snapshot_before,
        )

    def test_live_campaign_cap_is_editable(self):
        live = self._create_campaign(status="live", constraints_json={})
        web.conn.commit()
        response = self._put({"budget_cap": 50000}, live["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["campaign"]["constraints_json"], {"budget": 50000})


# F33-I01：一個從沒投放過的品牌只有 new／explore 兩個可用角色，模型照著回兩個。
_TWO_ROLE_REPLY = json.dumps({
    "allocation": [
        {"role": "new", "pct": 70, "rationale": "沒投放過，先找新客"},
        {"role": "explore", "pct": 30, "rationale": "測試素材角度"},
    ],
    "why": ["這個品牌沒有暖受眾"], "unknowns": [], "alternatives": [],
}, ensure_ascii=False)


class StartingPointFreshBrandTest(StrategyTestBase):
    """F33-I01（ruling 1A、Contract P）：從沒投放過的品牌——精靈還沒問、沒有花費歷史、沒讀過
    平台資料——prompt 每一行都寫「不知道／還沒」而不是 0，【可用角色】只有 `new、explore`，
    分了 `retarget` 的回覆整包退回、什麼都不存。"""

    ELIGIBLE = False

    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()

    def _prompt(self, reply: str) -> tuple[str, dict]:
        provider = _fake(reply)
        strategy.PROVIDER = provider
        detail = self._generate()
        return provider.calls[0]["messages"][0]["content"], detail

    def _observe(self, *, day, clicks, purchases) -> None:
        """一筆既有活動的廣告層讀回（`metric_scope='ad'`），走 ads 自己的外部來源寫入路徑。"""
        imported = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動",
        )
        entity = external.upsert_entity(web.conn, self.org_id, self.brand_id, imported["id"], {
            "platform": "meta", "source_account": "act_1", "native_kind": "ad",
            "native_id": f"ad_{uuid4().hex[:8]}",
        })
        external.upsert_observation(web.conn, self.org_id, self.brand_id, imported["id"], {
            "entity_id": entity["id"], "day": day, "metric_scope": "ad", "attribution_key": "a",
            "currency": "TWD", "source": "meta", "spend": 100, "clicks": clicks,
            "purchases": purchases,
        })
        web.conn.commit()

    def test_fresh_brand_prompt_states_every_unknown_and_offers_new_and_explore_only(self):
        prompt, detail = self._prompt(_TWO_ROLE_REPLY)

        self.assertIn("【可用角色】\nnew、explore\n", prompt)
        self.assertIn("【這個品牌的起點】\n", prompt)
        self.assertIn("- 投放過沒：精靈還沒問", prompt)
        self.assertIn("- 花費歷史：沒有可用的花費歷史", prompt)
        self.assertIn("- 近 90 天平台讀回：還沒讀過平台資料", prompt)
        self.assertIn("- 迴圈購買（已結案的活動）：沒有", prompt)
        self.assertIn("- 像素：還沒讀像素", prompt)
        self.assertIn("- 訂單：訂單資料不在這裡，別假設有回購名單", prompt)
        self.assertNotIn("點擊 0", prompt)  # 沒讀過不是 0
        # F39-I05：沒結案過的品牌，起點段一個字都不多——沒有「初始值」也沒有「已結案」那行。
        self.assertIn("- 投放過沒：精靈還沒問\n- 花費歷史：", prompt)
        self.assertNotIn("初始值", prompt)
        self.assertNotIn("- 已結案：", prompt)
        roles = [row["role"] for row in detail["budget_basis_json"]["strategy"]["allocation"]]
        self.assertEqual(roles, ["new", "explore"])

    def test_fresh_brand_refuses_a_reply_that_names_retarget_and_saves_nothing(self):
        strategy.PROVIDER = _fake(_VALID_REPLY)

        with self.assertRaises(ValueError) as ctx:
            self._generate()
        self._assert_refusal(ctx.exception, "role_unavailable")

        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["budget_basis_json"], {})

    def test_wizard_answer_none_is_quoted_and_still_offers_no_retarget(self):
        bi_repo.set_advertising_history(
            web.conn, self.brand_id, "none", actor=ACTOR,
        )
        prompt, _ = self._prompt(_TWO_ROLE_REPLY)
        self.assertIn("- 投放過沒：精靈答過：沒投放過", prompt)
        self.assertIn("【可用角色】\nnew、explore\n", prompt)

    def test_external_clicks_in_the_last_90_days_offer_retarget(self):
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        self._observe(day=today - timedelta(days=5), clicks=12, purchases=None)

        prompt, detail = self._prompt(_VALID_REPLY)

        self.assertIn("【可用角色】\nnew、retarget、explore\n", prompt)
        self.assertIn("- 近 90 天平台讀回：點擊 12、購買 不知道（沒追蹤到）", prompt)
        roles = [row["role"] for row in detail["budget_basis_json"]["strategy"]["allocation"]]
        self.assertEqual(roles, ["new", "retarget", "explore"])

    def test_platform_rows_with_zero_clicks_read_as_zero_and_offer_no_retarget(self):
        """讀過平台、真的是 0——那就印 0，不印「還沒讀過」；0 個點擊不是再行銷來源。"""
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        self._observe(day=today - timedelta(days=5), clicks=0, purchases=0)

        prompt, _ = self._prompt(_TWO_ROLE_REPLY)

        self.assertIn("- 近 90 天平台讀回：點擊 0、購買 0", prompt)
        self.assertIn("【可用角色】\nnew、explore\n", prompt)

    def test_rows_older_than_90_days_say_so_and_do_not_offer_retarget(self):
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        self._observe(day=today - timedelta(days=120), clicks=40, purchases=None)

        prompt, _ = self._prompt(_TWO_ROLE_REPLY)

        self.assertIn("- 近 90 天平台讀回：近 90 天沒有資料（更早的有讀過）", prompt)
        self.assertIn("【可用角色】\nnew、explore\n", prompt)

    def test_closed_loop_purchases_offer_retarget_and_are_counted(self):
        tag = uuid4().hex[:8]
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        closed = self._create_campaign(status="closed")
        group = web.conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key,"
            " name, role, daily_budget) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (f"adg_{tag}", self.org_id, self.brand_id, closed["id"], "meta", "新客組", "new",
             400),
        ).fetchone()
        for offset, spend, purchases in ((3, 400, 2), (2, 600, 2)):
            outcome_seed.seed_day(web.conn, self.org_id, self.brand_id, closed["id"], "group",
                                  group["id"], today - timedelta(days=offset), spend=spend,
                                  purchases=purchases, source="simulated")
        web.conn.commit()

        prompt, detail = self._prompt(_VALID_REPLY)

        self.assertIn("- 迴圈購買（已結案的活動）：4 筆", prompt)
        self.assertIn("- 花費歷史：上一期日預算（樣本 2 天）", prompt)
        self.assertIn("【可用角色】\nnew、retarget、explore\n", prompt)
        roles = [row["role"] for row in detail["budget_basis_json"]["strategy"]["allocation"]]
        self.assertEqual(roles, ["new", "retarget", "explore"])


class StartingPointEligibleBrandTest(StrategyTestBase):
    """F33-I01：精靈答過「投放過」的品牌——三個角色都可用，三角色的回覆照存。"""

    def test_has_history_brand_offers_retarget_and_saves_the_three_role_reply(self):
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        detail = self._generate()

        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("- 投放過沒：精靈答過：投放過", prompt)
        self.assertIn("【可用角色】\nnew、retarget、explore\n", prompt)
        roles = [row["role"] for row in detail["budget_basis_json"]["strategy"]["allocation"]]
        self.assertEqual(roles, ["new", "retarget", "explore"])

    def test_cached_pixels_are_counted_in_the_starting_point(self):
        self.campaign = self._create_campaign(context_json={
            "product_ids": [self.product["id"]],
            "launch_settings": {"pixels": {"items": [{"id": "px1"}, {"id": "px2"}]}},
        })
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        self._generate()

        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("- 像素：已讀到 2 個像素", prompt)


class StartingPointClosedCampaignsTest(StrategyTestBase):
    """F39-I05（drill-7 #5）：品牌用這個系統結案過之後，精靈答案只是初始值，起點段多一行
    「已結案 N 期；最近一期…」，數字照 `closed_at` 最新那期的 `verdict_json` 印。"""

    def _close(self, name: str, *, closed_at: str, verdict: str | None,
               verdict_json: dict) -> dict:
        closed = self._create_campaign(name=name, status="closed")
        web.conn.execute(
            "UPDATE ads_campaign SET verdict = %s, verdict_json = %s, closed_at = %s"
            " WHERE id = %s",
            (verdict, coredb.jsonb(verdict_json), closed_at, closed["id"]),
        )
        web.conn.commit()
        return closed

    def test_two_closed_campaigns_turn_the_wizard_answer_into_an_initial_value(self):
        self._close("第一期", closed_at="2026-08-31T00:00:00Z", verdict="未達成",
                    verdict_json={"actual": 420.0, "target": 300.0})
        self._close("第二期", closed_at="2026-09-20T00:00:00Z", verdict="達成",
                    verdict_json={"actual": 255.456, "target": 300.0})
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        self._generate()

        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn(
            "- 投放過沒：精靈答過：投放過（初始值；已用這個系統結案 2 期，以下列實際結果為準）\n"
            "- 已結案：2 期；最近一期「第二期」每筆 255.46 對上限 300，結果 達成\n"
            "- 花費歷史：",
            prompt,
        )
        self.assertNotIn("第一期", prompt)

    def test_an_older_verdict_json_without_numbers_prints_a_dash(self):
        """Blocked-if 條款：舊形狀的 `verdict_json` 缺 `actual`／`target` 就印「—」，不回填。"""
        self._close("舊的一期", closed_at="2026-09-01T00:00:00Z", verdict=None,
                    verdict_json={})
        self.campaign = self._create_campaign()
        provider = _fake(_VALID_REPLY)
        strategy.PROVIDER = provider

        self._generate()

        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn("- 已結案：1 期；最近一期「舊的一期」每筆 — 對上限 —，結果 —\n", prompt)


class ValidateReplyAvailableSetTest(unittest.TestCase):
    """`_validate_reply` 拿的是程式列的可用角色集合，不是寫死的三個。"""

    def test_a_role_outside_the_available_set_is_refused(self):
        data = json.loads(_VALID_REPLY)
        self.assertIsNone(strategy._validate_reply(data, frozenset({"new", "explore"})))
        validated = strategy._validate_reply(data, frozenset({"new", "retarget", "explore"}))
        self.assertIsNotNone(validated)
        assert validated is not None
        self.assertEqual([row["role"] for row in validated["allocation"]],
                         ["new", "retarget", "explore"])


# -- F50 Contract J (R7 B3): refusal codes, and the one automatic retry (user ruling 2026-10-04) --


class _Replies:
    """A provider answering `texts` in order (the last one repeats)."""

    name = "fake"

    def __init__(self, *texts: str):
        self.texts, self.calls = list(texts), []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0, effort=None,
                 tools=None, org_id=None):
        self.calls.append({"messages": messages})
        return providers.ProviderResponse(
            output_text=self.texts[min(len(self.calls), len(self.texts)) - 1], structured=None,
            usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
        )


def _number_reply() -> str:
    reply = json.loads(_VALID_REPLY)
    reply["why"] = ["上一期每筆 392 最便宜"]
    return json.dumps(reply, ensure_ascii=False)


class StrategyRefusalTest(StrategyTestBase):
    """Contract J: a strategy refused by a program rule is asked once more with the refusal in
    the prompt (the retry's reply is used); a second refusal is raised with its code, stored on
    its row and printed in the 502."""

    def setUp(self):
        super().setUp()
        self.campaign = self._create_campaign()
        web.conn.commit()  # the route reads it on its own connection

    def _rows(self) -> list:
        return gateway.find_tasks_for_scope(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, task_type="ads_strategy",
            context_scope={"campaign_id": self.campaign["id"]},
        )

    def test_a_refused_strategy_is_asked_once_more_with_the_refusal_and_the_retry_is_used(self):
        provider = _Replies(_number_reply(), _VALID_REPLY)
        strategy.PROVIDER = provider
        detail = self._generate()
        self.assertEqual(len(provider.calls), 2)
        retry = provider.calls[1]["messages"][0]["content"]
        self.assertNotIn(plan.RETRY_HEADER, provider.calls[0]["messages"][0]["content"])
        self.assertTrue(retry.endswith(
            f"{plan.RETRY_HEADER}（這次請改掉下面的問題，其他規則照舊）\n"
            f"- number_in_prose：{strategy.REFUSALS['number_in_prose']}"))
        first, second = self._rows()
        self.assertEqual(first["error"],
                         f"number_in_prose: {strategy.REFUSALS['number_in_prose']}")
        self.assertEqual(detail["budget_basis_json"]["basis"]["llm_task_id"], second["id"])

    def test_a_second_refusal_is_raised_stored_and_printed_in_the_502(self):
        strategy.PROVIDER = _Replies(_number_reply(), _BAD_SUM_REPLY)
        response = TestClient(main.app).post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}/strategy")
        self.assertEqual(response.status_code, 502)
        reason = strategy.REFUSALS["pct_invalid"]
        self.assertEqual(response.json()["error"], {
            "code": "strategy_failed",
            "message": f"{strategy.STRATEGY_FAILED_MESSAGE}（{reason}）",
            "details": {"refusal": "pct_invalid", "reason": reason},
        })
        self.assertEqual([row["error"].split(":")[0] for row in self._rows()],
                         ["number_in_prose", "pct_invalid"])
        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(campaign["budget_basis_json"], {})

    def test_every_refusal_code_has_a_sentence(self):
        self.assertEqual(set(strategy.REFUSALS), {
            "llm_failed", "reply_unreadable", "reply_invalid", "number_in_prose",
            "role_unavailable", "pct_invalid", "role_repeated",
        })
        for code in ("reply_invalid", "number_in_prose", "role_unavailable"):
            self.assertEqual(strategy._check_reply(  # noqa: SLF001
                {"allocation": "x"} if code == "reply_invalid" else
                {**json.loads(_VALID_REPLY), "why": ["多 20%"]} if code == "number_in_prose"
                else json.loads(_VALID_REPLY), frozenset({"new", "explore"}))[1], code)
