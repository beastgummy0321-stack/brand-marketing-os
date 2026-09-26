"""app/tests/test_ads_plan.py — F03-I06 falsifiers: adopting a strategy writes group daily
budgets that sum exactly to `round(budget_planned / days)` even on an awkward split (proves
`budget.split()`'s remainder rule, not a naive `total / groups`); `budget_planned` survives both
the adopt and a later group edit unchanged; every ad carries all seven coordinates and a name
unique inside the campaign; adopting twice is refused; editing a bound group's budget writes
exactly one `ads_action` row (unbound edits write none); a budget raise above the brand's
approved `max_daily_amount` is refused before anything is written.
"""

import json
import unittest

import app.shared.web as web
from app.ads import plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import db as coredb
from app.llm import providers

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


class PlanTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心展開", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self._orig_provider = plan.PROVIDER

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _create_adopted_campaign(
        self, *, budget_planned: float = 30001, start_date: str = "2026-10-01",
        end_date: str = "2026-10-14", platform: str | None = None,
    ) -> dict:
        """14 天（含頭尾）、50／30／20 的角色分配——刻意選 30001／14 這種除不整的數字：
        naive `total / groups` 會漏掉餘數，`budget.split()` 才會精準加總（Done 第一句）。"""
        allocation = [
            {"role": "new", "label": "新客", "pct": 50, "rationale": None},
            {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": None},
            {"role": "explore", "label": "探索", "pct": 20, "rationale": None},
        ]
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫產品衝購買",
            "objective": "購買", "target_cost": 300,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": budget_planned, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }
        if platform is not None:
            campaign["constraints_json"] = {"platform": platform}
        return ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                         created_by=ACTOR)

    def _adopt(self, campaign_id: str) -> dict:
        return plan.adopt_strategy(
            web.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR,
        )


class GroupBudgetsSumExactlyTest(PlanTestBase):
    def test_awkward_split_sums_exactly_to_rounded_daily_total(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        days = 14
        expected_daily_total = round(30001 / days)  # 2144 — 50/30/20 floors to 2143, +1 remainder
        group_budgets = [float(g["daily_budget"]) for g in detail["groups"]]
        self.assertEqual(sum(group_budgets), expected_daily_total)
        self.assertEqual(len(detail["groups"]), 3)
        self.assertEqual(detail["status"], "ready")


class BudgetPlannedNeverRewrittenTest(PlanTestBase):
    def test_budget_planned_survives_adopt_and_a_later_group_edit(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = self._adopt(campaign["id"])
        self.assertEqual(float(detail["budget_planned"]), 30001)

        group = detail["groups"][0]
        plan.update_group(
            web.conn, self.org_id, self.brand_id, group["id"],
            {"daily_budget": float(group["daily_budget"]) + 10}, actor=ACTOR,
        )
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(float(reloaded["budget_planned"]), 30001)


class AdCoordinatesAndNamesTest(PlanTestBase):
    def test_every_ad_has_seven_coordinates_and_a_unique_name(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        names = []
        for group in detail["groups"]:
            for ad in group["ads"]:
                names.append(ad["name"])
                for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format"):
                    self.assertTrue(ad[f"{dim}_key"], f"{dim} 不該是空的")
        self.assertEqual(len(names), len(set(names)))


class DeclaredPlatformDrivesChannelKeyTest(PlanTestBase):
    def test_adopt_uses_the_campaigns_declared_platform_not_meta(self):
        """F05-I05：`constraints_json.platform = "google_ads"` 的 Campaign 採用策略後，
        投放組的 channel_key 是 google_ads，不是寫死的 meta（§0「不預設」）。"""
        campaign = self._create_adopted_campaign(platform="google_ads")
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        self.assertTrue(detail["groups"])
        for group in detail["groups"]:
            self.assertEqual(group["channel_key"], "google_ads")


class AdoptTwiceRefusedTest(PlanTestBase):
    def test_adopting_a_second_time_is_refused(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        self._adopt(campaign["id"])

        with self.assertRaises(ValueError) as ctx:
            self._adopt(campaign["id"])
        self.assertEqual(str(ctx.exception), "plan_already_adopted")


class LastGroupDeleteRefusedTest(PlanTestBase):
    def test_deleting_the_last_group_is_refused(self):
        """Adopt refuses a second run, so an adopted plan with zero groups is a dead end."""
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        groups = self._adopt(campaign["id"])["groups"]

        for group in groups[:-1]:
            plan.delete_group(web.conn, self.org_id, self.brand_id, group["id"])
        with self.assertRaises(ValueError) as ctx:
            plan.delete_group(web.conn, self.org_id, self.brand_id, groups[-1]["id"])
        self.assertEqual(str(ctx.exception), "last_group")
        self.assertIsNotNone(ads_repo.get_group(web.conn, self.org_id, self.brand_id,
                                                groups[-1]["id"]))


class GroupEditActionTraceTest(PlanTestBase):
    def test_editing_a_bound_group_writes_one_action_unbound_writes_none(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = self._adopt(campaign["id"])
        bound_group, unbound_group = detail["groups"][0], detail["groups"][1]

        web.conn.execute(
            "UPDATE ads_delivery_group SET local_state = 'bound' WHERE id = %s",
            (bound_group["id"],),
        )
        web.conn.commit()

        before_budget = float(bound_group["daily_budget"])
        after_budget = before_budget + 5
        plan.update_group(
            web.conn, self.org_id, self.brand_id, bound_group["id"],
            {"daily_budget": after_budget}, actor=ACTOR,
        )
        actions = list(web.conn.execute(
            "SELECT * FROM ads_action WHERE target_id = %s", (bound_group["id"],),
        ))
        self.assertEqual(len(actions), 1)
        action = dict(actions[0])
        self.assertEqual(action["kind"], "budget")
        self.assertEqual(action["sync_state"], "pending_manual")
        self.assertEqual(float(action["before_json"]["daily_budget"]), before_budget)
        self.assertEqual(float(action["after_json"]["daily_budget"]), after_budget)

        plan.update_group(
            web.conn, self.org_id, self.brand_id, unbound_group["id"],
            {"name": "改個名字"}, actor=ACTOR,
        )
        unbound_actions = list(web.conn.execute(
            "SELECT * FROM ads_action WHERE target_id = %s", (unbound_group["id"],),
        ))
        self.assertEqual(len(unbound_actions), 0)


class BudgetCeilingTest(PlanTestBase):
    def test_a_raise_above_the_approved_ceiling_is_refused(self):
        campaign = self._create_adopted_campaign()  # daily_total 2144 > 核准上限 100
        approval_mod.approve(
            web.conn, org_id=self.org_id, brand_id=self.brand_id,
            scope_type=plan.APPROVAL_SCOPE_TYPE, scope_ref=campaign["id"],
            content_hash="whatever", amount=100, max_daily_amount=100, actor=ACTOR,
        )
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        with self.assertRaises(ValueError) as ctx:
            self._adopt(campaign["id"])
        self.assertEqual(str(ctx.exception), "budget_exceeds_approval")

        groups = list(web.conn.execute(
            "SELECT id FROM ads_delivery_group WHERE campaign_id = %s", (campaign["id"],),
        ))
        self.assertEqual(groups, [])  # 拒絕在寫任何列之前發生


class CalendarInDeliveryPlanPromptTest(PlanTestBase):
    """F33-I02（Contract Q）：展開投放組的 prompt 也帶【投放期間內的行事曆】——預設 Campaign
    2026-10-01～10-14 跨國慶日；已採用的角色分配那幾行（Contract P）不動。"""

    def _prompt(self, **overrides) -> str:
        campaign = self._create_adopted_campaign(**overrides)
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        self._adopt(campaign["id"])
        return provider.calls[0]["messages"][0]["content"]

    def test_prompt_lists_the_calendar_rows_overlapping_the_period(self):
        prompt = self._prompt()
        self.assertIn("【投放期間內的行事曆】\n", prompt)
        self.assertIn("國慶日", prompt)
        self.assertNotIn("雙 11 檔", prompt)
        self.assertIn("- new（新客）：50%", prompt)
        # 任務檔前面也提到這個標題，取最後一次出現的位置才是真正的段落。
        self.assertLess(
            prompt.index("- explore（探索）：20%"), prompt.rindex("【投放期間內的行事曆】"),
        )

    def test_period_outside_the_table_gets_the_coverage_note(self):
        prompt = self._prompt(start_date="2028-03-01", end_date="2028-03-14")
        self.assertIn("【投放期間內的行事曆】\n期間內沒有登記的假日、考季或檔期\n", prompt)
        self.assertIn("2028 年的假日與考季沒有資料，不要假設沒有活動", prompt)


if __name__ == "__main__":
    unittest.main()
