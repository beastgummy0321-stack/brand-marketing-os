"""app/tests/test_ads_budget.py — F03-I04 falsifiers: breakeven never guesses a margin,
cold-start scenarios are 2/5/10x the one cap (F28-I01) with the 冷啟動估算 flag, history
scenarios are x0.6/x1/x1.6 of the previous daily budget with the sample named, and `split`
always sums exactly to the total.

F48 Contract M: `whole`／`daily_of`／`total_of` are the one money calculator; adopt (and a new
total after adoption) leaves `budget_planned == budget_total == Σ group daily × days`, a draft's
chosen total is stored unchanged with a `budget_preview` note, and the period is fixed after
adoption.
"""

import json
import random
import unittest
from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import budget, channels, learning_rank, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.tests.test_ads_strategy_decision import bind_fixture, fixture_provider

from .identity_test_helpers import mint_hs256


class BreakevenCpaTest(unittest.TestCase):
    def test_breakeven_is_price_minus_cost_minus_shipping(self):
        economics = {"selling_price": 500, "unit_variable_cost": 150, "shipping_cost": 50}
        self.assertEqual(budget.breakeven_cpa(economics), 300)

    def test_breakeven_without_shipping_remains_unknown(self):
        economics = {"selling_price": 500, "unit_variable_cost": 150, "shipping_cost": None}
        self.assertIsNone(budget.breakeven_cpa(economics))

    def test_missing_unit_variable_cost_returns_none_not_a_guess(self):
        economics = {"selling_price": 500, "unit_variable_cost": None, "shipping_cost": 50}
        self.assertIsNone(budget.breakeven_cpa(economics))

    def test_missing_economics_row_returns_none(self):
        self.assertIsNone(budget.breakeven_cpa(None))

    def test_no_ratio_constant_survives(self):
        # F28-I01: cold start multiplies the resolved cap itself -- no 0.7 on top of it.
        self.assertFalse(hasattr(budget, "TARGET_CPA_RATIO"))
        self.assertFalse(hasattr(budget, "target_cpa"))


class ScenariosTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心預算", client_name=None,
            actor="測試員",
        )
        self.brand_id = self.brand["id"]
        self.product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor="測試員")["id"]

    def test_cold_start_scenarios_are_2_5_10x_the_cap_and_flagged(self):
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=10,
            history=None, cap=300,
        )
        self.assertEqual(result["mode"], "cold_start")
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["minimum"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1500)
        self.assertEqual(by_key["aggressive"]["daily"], 3000)
        for row in result["scenarios"]:
            self.assertIn("冷啟動估算", row["caption"])
            self.assertIn("上限", row["caption"])
            self.assertEqual(row["total"], row["daily"] * 10)
        self.assertEqual(result["recommended"], "recommended")
        self.assertEqual(result["basis"]["cap"], 300)
        self.assertEqual(result["basis"]["product_id"], self.product_id)

    def test_no_cap_yields_no_fabricated_scenario_numbers(self):
        # Product economics alone never turn into a number here: the caller resolves the cap.
        bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=150, shipping_cost=50,
        )
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=10,
            history=None,
        )
        self.assertEqual(result["mode"], "cold_start")
        for row in result["scenarios"]:
            self.assertIsNone(row["daily"])
            self.assertIsNone(row["total"])

    def test_history_scenarios_are_06_1_16x_previous_daily_and_name_the_sample(self):
        history = {"cpa": 280, "last_daily_budget": 1000, "sample_days": 27, "sample_ads": 4}
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        self.assertEqual(result["mode"], "history")
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["conservative"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1000)
        self.assertEqual(by_key["aggressive"]["daily"], 1600)
        self.assertEqual(by_key["recommended"]["total"], 7000)
        self.assertEqual(result["basis"]["cpa"], 280)
        self.assertEqual(result["basis"]["sample_days"], 27)
        self.assertEqual(result["basis"]["sample_ads"], 4)
        for row in result["scenarios"]:
            self.assertIn("上一期日預算", row["caption"])
            self.assertNotIn("中位數", row["caption"])

    def test_history_caption_never_mentions_cpa_median_when_cpa_absent(self):
        history = {"last_daily_budget": 1000, "sample_days": 5, "sample_ads": 1}
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        for row in result["scenarios"]:
            self.assertNotIn("中位數", row["caption"])
            self.assertNotIn("CPA", row["caption"])

    def test_history_caption_names_the_source_when_given_and_amount_is_unchanged(self):
        """F05-I11: `source_text` 只換 caption 開頭那句話，三張卡的金額不動。"""
        history = {
            "cpa": 280, "last_daily_budget": 1000, "sample_days": 30, "sample_ads": None,
            "source": "meta_account", "source_text": "Meta 近 30 天平均日花費",
        }
        result = budget.scenarios(
            web.conn, self.org_id, self.brand_id, product_ids=[self.product_id], days=7,
            history=history,
        )
        by_key = {row["key"]: row for row in result["scenarios"]}
        self.assertEqual(by_key["conservative"]["daily"], 600)
        self.assertEqual(by_key["recommended"]["daily"], 1000)
        self.assertEqual(by_key["aggressive"]["daily"], 1600)
        for row in result["scenarios"]:
            self.assertIn("Meta 近 30 天平均日花費", row["caption"])
        self.assertEqual(result["basis"]["source"], "meta_account")


class SplitTest(unittest.TestCase):
    def test_split_sums_exactly_to_total_for_an_awkward_amount(self):
        rows = budget.split(30001, {"新客": 0.5, "再行銷": 0.3, "探索": 0.2})
        self.assertEqual(sum(row["amount"] for row in rows), 30001)
        by_label = {row["label"]: row["amount"] for row in rows}
        self.assertEqual(by_label["新客"], 15001)  # remainder goes to the largest share
        self.assertEqual(by_label["再行銷"], 9000)
        self.assertEqual(by_label["探索"], 6000)

    def test_split_empty_weights_returns_empty(self):
        self.assertEqual(budget.split(1000, {}), [])


if __name__ == "__main__":
    unittest.main()


class BudgetCapScenariosTest(unittest.TestCase):
    """F28-I03 (ads.md §6.32 "Budget cap is a soft warning"): `current_scenarios` reads the
    campaign's budget cap (`constraints_json.budget`) on every read -- `budget_cap`, per-row
    `over_cap`, the 照預算上限 row, and `recommended` moving to it when the old pick is over."""

    START, END = date(2026, 10, 1), date(2026, 10, 10)  # 10 days

    def _campaign(self, budget_cap=None, *, dates=True) -> dict:
        constraints = {} if budget_cap is None else {"budget": budget_cap}
        return {
            "start_date": self.START if dates else None, "end_date": self.END if dates else None,
            "constraints_json": constraints,
        }

    def _cold(self, budget_cap=None, *, cap=300, dates=True) -> dict:
        return budget.current_scenarios(
            {"mode": "cold_start"}, self._campaign(budget_cap, dates=dates), cap=cap,
        )

    def test_no_cap_unset_zero_negative_or_junk_adds_nothing(self):
        for value in (None, 0, -5, "abc", True, float("nan")):
            with self.subTest(value=value):
                result = self._cold(value)
                self.assertIsNone(result["budget_cap"])
                self.assertEqual([r["key"] for r in result["scenarios"]],
                                 ["minimum", "recommended", "aggressive"])
                self.assertTrue(all(r["over_cap"] is None for r in result["scenarios"]))
                self.assertEqual(result["recommended"], "recommended")

    def test_cold_start_labels(self):
        labels = [r["label"] for r in self._cold()["scenarios"]]
        self.assertEqual(labels, ["最低", "穩定成長", "積極"])

    def test_cap_row_and_over_amounts_when_the_recommendation_fits(self):
        # 300 x 2/5/10 x 10 days = 6000 / 15000 / 30000
        result = self._cold(20000)
        self.assertEqual(result["budget_cap"], 20000)
        rows = result["scenarios"]
        self.assertEqual([r["key"] for r in rows],
                         ["minimum", "cap", "recommended", "aggressive"])
        cap_row = rows[1]
        self.assertEqual((cap_row["label"], cap_row["daily"], cap_row["total"]),
                         ("照預算上限", 2000, 20000))
        self.assertEqual([r["over_cap"] for r in rows], [0, 0, 0, 10000])
        self.assertEqual(result["recommended"], "recommended")

    def test_recommended_moves_to_cap_when_it_is_over(self):
        result = self._cold(12000)
        self.assertEqual(result["recommended"], "cap")
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertEqual(by_key["recommended"]["over_cap"], 3000)

    def test_cap_exactly_equal_to_a_total_is_not_over(self):
        result = self._cold(15000)
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertEqual(by_key["recommended"]["over_cap"], 0)
        self.assertEqual(result["recommended"], "recommended")

    def test_unknown_totals_are_never_over(self):
        result = self._cold(12000, cap=None)  # no cost-per-result cap -> no amounts
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertIsNone(by_key["recommended"]["total"])
        self.assertIsNone(by_key["recommended"]["over_cap"])
        self.assertEqual(by_key["cap"]["total"], 12000)
        self.assertEqual(result["recommended"], "recommended")

    def test_days_unknown_keeps_the_cap_total_without_a_daily(self):
        result = self._cold(12000, dates=False)
        by_key = {r["key"]: r for r in result["scenarios"]}
        self.assertIsNone(by_key["cap"]["daily"])
        self.assertEqual(by_key["cap"]["total"], 12000)
        self.assertIsNone(by_key["aggressive"]["over_cap"])

    def test_numeric_string_cap_from_the_wizard_is_read(self):
        self.assertEqual(self._cold("20,000")["budget_cap"], 20000)

    def test_stored_history_snapshot_reconciles_idempotently_with_new_labels(self):
        stored = {
            "mode": "history", "recommended": "cap", "basis": {},
            "scenarios": [
                {"key": "conservative", "label": "保守", "daily": 600, "total": 1, "caption": "x"},
                {"key": "cap", "label": "照預算上限", "daily": 1, "total": 1, "caption": "x"},
                {"key": "recommended", "label": "推薦", "daily": 1000, "total": 1, "caption": "x"},
                {"key": "aggressive", "label": "積極", "daily": 1600, "total": 1, "caption": "x"},
            ],
        }
        campaign = self._campaign(20000)
        once = budget.current_scenarios(stored, campaign)
        twice = budget.current_scenarios(once, campaign)
        self.assertEqual(once, twice)
        self.assertEqual([r["key"] for r in once["scenarios"]],
                         ["conservative", "cap", "recommended", "aggressive"])
        self.assertEqual([r["label"] for r in once["scenarios"]],
                         ["保守", "照預算上限", "照上一期", "積極"])
        self.assertEqual([r["total"] for r in once["scenarios"]], [6000, 20000, 10000, 16000])
        self.assertEqual(once["recommended"], "recommended")  # 10000 fits under 20000
        # Lowering the cap moves the recommendation; clearing it drops the row again.
        lower = budget.current_scenarios(once, self._campaign(8000))
        self.assertEqual(lower["recommended"], "cap")
        cleared = budget.current_scenarios(lower, self._campaign(None))
        self.assertNotIn("cap", [r["key"] for r in cleared["scenarios"]])
        self.assertEqual(cleared["recommended"], "recommended")


class RecommendedWithAmountTest(unittest.TestCase):
    """F29 Contract D: the campaign read (`reconcile_campaign`) never recommends a row with no
    amount -- the projected pick when its total is known, else the first row in display order
    with a known total, else `None`. The §6.32 over-cap rule still wins when a cap exists."""

    START, END = date(2026, 10, 1), date(2026, 10, 10)  # 10 days

    def _read(self, budget_cap=None, *, cap=300, dates=True, stored=None) -> dict:
        campaign = {
            "start_date": self.START if dates else None, "end_date": self.END if dates else None,
            "constraints_json": {} if budget_cap is None else {"budget": budget_cap},
            "budget_planned": None,
            "budget_basis_json": {"scenarios": stored or {"mode": "cold_start"}},
        }
        return budget.reconcile_campaign(campaign, cap=cap)["budget_basis_json"]["scenarios"]

    def test_a_known_pick_is_kept(self):
        self.assertEqual(self._read()["recommended"], "recommended")

    def test_over_cap_rule_still_wins(self):
        # recommended (15000) is over the 12000 budget cap -> the cap row, as §6.32 rules.
        self.assertEqual(self._read(12000)["recommended"], "cap")

    def test_unknown_pick_falls_to_the_first_row_with_an_amount(self):
        # No cost-per-result cap: only the 照預算上限 row has an amount.
        scenarios = self._read(12000, cap=None)
        self.assertIsNone({r["key"]: r for r in scenarios["scenarios"]}["recommended"]["total"])
        self.assertEqual(scenarios["recommended"], "cap")

    def test_every_total_unknown_recommends_nothing(self):
        scenarios = self._read(None, cap=None)
        self.assertTrue(all(r["total"] is None for r in scenarios["scenarios"]))
        self.assertIsNone(scenarios["recommended"])

    def test_no_dates_and_no_budget_cap_recommends_nothing(self):
        # A cap but no campaign dates: every daily is known, no total is.
        self.assertIsNone(self._read(None, dates=False)["recommended"])

    def test_a_stored_null_recommendation_reprojects(self):
        # A snapshot saved with `recommended: None` is read back as a real pick once amounts
        # are known again.
        stored = {"mode": "cold_start", "recommended": None, "scenarios": []}
        self.assertEqual(self._read(stored=stored)["recommended"], "recommended")

    def test_history_pick_with_unknown_days_recommends_nothing(self):
        stored = {
            "mode": "history", "recommended": "recommended", "basis": {},
            "scenarios": [
                {"key": "conservative", "label": "保守", "daily": 600, "total": None,
                 "caption": "x"},
                {"key": "recommended", "label": "照上一期", "daily": 1000, "total": None,
                 "caption": "x"},
            ],
        }
        self.assertIsNone(self._read(dates=False, stored=stored)["recommended"])


# -- F48 Contract M: one money calculator ---------------------------------------------------------

_ROLES = ("new", "retarget", "explore")
_LABELS = {"new": "新客", "retarget": "再行銷", "explore": "探索"}


def _allocation(pcts) -> list[dict]:
    return [
        {"role": role, "label": _LABELS[role], "pct": pct, "rationale": None}
        for role, pct in zip(_ROLES, pcts, strict=True)
    ]


def _random_pcts(rng) -> tuple:
    first = rng.randint(5, 85)
    second = rng.randint(5, 95 - first)
    return first, second, 100 - first - second


def _fake(rendered_output: str) -> providers.FakeProvider:
    return fixture_provider(rendered_output)


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": "none",
        "format": f"format_{tag}",
    }


_PLAN_REPLY = json.dumps({"groups": [
    {"role": "new", "name": "新客組", "ads": [
        {"name": "新客-廣告一", "coordinates": _coordinates("new1"),
         "scene": "上班族午休在辦公室滑手機找點心"}]},
    {"role": "retarget", "name": "再行銷組", "ads": [
        {"name": "再行銷-廣告一", "coordinates": _coordinates("rt1"),
         "scene": "看過商品頁的人晚上在家猶豫要不要下單"}]},
    {"role": "explore", "name": "探索組", "ads": [
        {"name": "探索-廣告一", "coordinates": _coordinates("ex1"),
         "scene": "健身房的人運動完在櫃檯看補給品"}]},
]}, ensure_ascii=False)


class MoneyCalculatorTest(unittest.TestCase):
    """`whole` is half up (never banker's), `daily_of` floors, `total_of` is exact."""

    def test_whole_is_half_up_and_passes_none(self):
        self.assertEqual([budget.whole(v) for v in (2.5, 3.5, 0.49, 1999.5, -0.5)],
                         [3, 4, 0, 2000, 0])
        self.assertIsNone(budget.whole(None))
        # The owner-facing string and the wizard's break-even are the same rounding.
        self.assertEqual(learning_rank.whole(2.5), "3")
        self.assertEqual(learning_rank.whole(1234.5), "1,235")

    def test_daily_of_floors_and_total_of_is_exact(self):
        self.assertEqual(budget.daily_of(10000, 7), 1428)
        self.assertEqual(budget.daily_of(30001, 30), 1000)
        self.assertEqual(budget.daily_of(800, 31), 25)
        self.assertIsNone(budget.daily_of(None, 7))
        self.assertIsNone(budget.daily_of(1000, 0))
        self.assertEqual(budget.total_of(1428, 7), 9996)
        self.assertIsNone(budget.total_of(None, 7))
        self.assertIsNone(budget.total_of(1000, 0))

    def test_preview_notes_only_a_total_the_daily_cannot_reach(self):
        self.assertEqual(budget.preview(800, 31), {
            "daily": 25, "total": 775, "chosen": 800,
            "note": "每天要是整數，這期實際 775",
        })
        self.assertEqual(budget.preview(15000, 10)["note"], None)
        self.assertIsNone(budget.preview(None, 10))

    def test_cap_row_never_goes_over_its_own_cap(self):
        campaign = {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31),
                    "constraints_json": {"budget": 10000}}
        result = budget.current_scenarios({"mode": "cold_start"}, campaign, cap=300)
        cap_row = next(r for r in result["scenarios"] if r["key"] == budget.CAP_KEY)
        self.assertEqual((cap_row["daily"], cap_row["total"], cap_row["over_cap"]),
                         (322, 9982, 0))

    def test_split_of_the_daily_total_always_adds_up(self):
        rng = random.Random(48)
        cases = [(10000, 7, (50, 30, 20)), (30001, 30, (50, 30, 20))]
        cases += [(rng.randint(100, 500000), rng.randint(1, 60), _random_pcts(rng))
                  for _ in range(300)]
        for total, days, pcts in cases:
            with self.subTest(total=total, days=days, pcts=pcts):
                daily = budget.daily_of(total, days)
                amounts = [row["amount"] for row in budget.split(
                    daily, {str(i): p / 100 for i, p in enumerate(pcts)})]
                self.assertEqual(sum(amounts), daily)
                self.assertTrue(all(isinstance(a, int) for a in amounts))
                adopted = budget.total_of(sum(amounts), days)
                self.assertLessEqual(adopted, total)
                self.assertGreater(adopted, total - days)

    def test_resplit_keeps_a_hand_added_groups_share(self):
        groups = [
            {"id": "a", "role": "new", "daily_budget": 500},
            {"id": "b", "role": "explore", "daily_budget": 300},
            {"id": "c", "role": "retarget", "daily_budget": 200},  # not in the allocation
        ]
        allocation = [{"role": "new", "pct": 60}, {"role": "explore", "pct": 40}]
        after = budget.resplit(2000, groups, allocation)
        self.assertEqual(sum(after.values()), 2000)
        self.assertEqual(after, {"a": 960, "b": 640, "c": 400})


class AdoptRoundsTheTotalPropertyTest(unittest.TestCase):
    """Done 2／7: after adopt `budget_planned == budget_total == Σ group daily × days`, every group
    daily is whole and Σ daily == `daily_of(chosen, days)` -- over random totals／days／pcts."""

    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：一套算錢", client_name=None,
            actor="測試員",
        )["id"]
        self._orig_provider = plan.PROVIDER

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def test_adopt_leaves_planned_equal_to_the_derived_total(self):
        rng = random.Random(7)
        cases = [(10000, 7, (50, 30, 20)), (30001, 30, (50, 30, 20))]
        cases += [(rng.randint(1000, 300000), rng.randint(1, 45), _random_pcts(rng))
                  for _ in range(10)]
        start = date(2026, 10, 1)
        for n, (total, days, pcts) in enumerate(cases):
            with self.subTest(total=total, days=days, pcts=pcts):
                campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
                    "name": f"一套算錢 第 {n} 期", "goal_text": "衝購買",
                    "objective": "購買", "target_cost": max(1, budget.daily_of(total, days) / 6),
                    "start_date": start, "end_date": start + timedelta(days=days - 1),
                    "status": "draft", "budget_planned": total,
                    "budget_scenario": "custom",
                    "budget_basis_json": {"strategy": {"allocation": _allocation(pcts)}},
                }, created_by="測試員")
                plan.PROVIDER = _fake(_PLAN_REPLY)
                revision = bind_fixture(
                    web.conn, self.org_id, self.brand_id, campaign["id"], json.loads(_PLAN_REPLY)
                )
                detail = plan.adopt_strategy(
                    web.conn, self.org_id, self.brand_id, campaign["id"], actor="測試員",
                    expected_revision=revision, operation_id=f"money-{campaign['id']}",
                )
                dailies = [float(g["daily_budget"]) for g in detail["groups"]]
                self.assertTrue(all(d.is_integer() for d in dailies))
                self.assertEqual(sum(dailies), budget.daily_of(total, days))
                self.assertEqual(float(detail["budget_planned"]), sum(dailies) * days)
                self.assertEqual(float(detail["budget_total"]), float(detail["budget_planned"]))
                self.assertIsNone(detail["budget_preview"]["note"])
                # The strategy tab's role amounts are the groups' money after adoption.
                amounts = [r["amount"] for r in
                           detail["budget_basis_json"]["strategy"]["allocation"]]
                self.assertEqual(sum(amounts), float(detail["budget_planned"]))


class BudgetRoutesTest(unittest.TestCase):
    """Route contract: a draft's custom total is stored unchanged with `budget_preview.note`; on a
    `ready` campaign a new total re-splits the unbound ad sets (`resplit`), a bound one is 409;
    PATCH of the period after adoption is 409 `plan_already_adopted`."""

    START = date(2026, 10, 1)

    def setUp(self):
        self.client = TestClient(main.app)
        user = uuid4()
        token = mint_hs256(sub=str(user), email=f"adsmoney-{user.hex[:8]}@example.com")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.org_id = self.client.get(
            "/api/identity/me", headers=self.headers).json()["org"]["id"]
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：預算路由", client_name=None,
            actor="測試員",
        )["id"]

    def _campaign(self, *, days: int, status: str = "draft", planned=None) -> dict:
        allocation = [dict(row, amount=None) for row in _allocation((50, 30, 20))]
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "預算路由", "goal_text": "衝購買", "objective": "購買", "target_cost": 300,
            "start_date": self.START, "end_date": self.START + timedelta(days=days - 1),
            "status": status, "budget_planned": planned, "budget_scenario": "custom",
            "budget_basis_json": {
                "scenarios": {"mode": "history", "recommended": "recommended", "basis": {},
                              "scenarios": [{"key": "recommended", "label": "照上一期",
                                             "daily": 1000, "total": 1000 * days,
                                             "caption": "x"}]},
                "strategy": {"allocation": allocation},
            },
        }, created_by="測試員")
        web.conn.commit()
        return campaign

    def _ready(self) -> tuple[dict, list[dict]]:
        campaign = self._campaign(days=10, status="ready", planned=10000)
        channel_key = channels.default_channel_key(web.conn, self.org_id, self.brand_id, None)
        groups = [
            ads_repo.create_group(web.conn, self.org_id, self.brand_id, campaign["id"],
                                  channel_key=channel_key, name=_LABELS[role], role=role,
                                  daily_budget=daily)
            for role, daily in (("new", 500), ("retarget", 300), ("explore", 200))
        ]
        web.conn.commit()
        return campaign, groups

    def _url(self, campaign_id: str, suffix: str = "") -> str:
        return f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}{suffix}"

    def _choose_total(self, campaign_id: str, total):
        return self.client.post(
            self._url(campaign_id, "/strategy/scenario"),
            json={"scenario_key": "custom", "custom_total": total}, headers=self.headers,
        )

    def test_a_custom_total_is_stored_unchanged_and_the_preview_notes_the_real_total(self):
        campaign = self._campaign(days=31)
        response = self._choose_total(campaign["id"], 800)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["resplit"])
        self.assertEqual(float(body["campaign"]["budget_planned"]), 800)
        self.assertEqual(body["campaign"]["budget_preview"], {
            "daily": 25, "total": 775, "chosen": 800, "note": "每天要是整數，這期實際 775",
        })
        read = self.client.get(self._url(campaign["id"]), headers=self.headers)
        self.assertEqual(read.json()["campaign"]["budget_preview"]["note"],
                         "每天要是整數，這期實際 775")

    def test_a_total_below_one_a_day_is_refused_and_nothing_is_stored(self):
        campaign = self._campaign(days=31)
        response = self._choose_total(campaign["id"], 30)
        self.assertEqual(response.status_code, 400, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "total_below_one_per_day")
        self.assertEqual(error["message"], "總預算太少：每天不到 1 元")
        self.assertIsNone(
            ads_repo.get_campaign(web.conn, self.org_id, self.brand_id,
                                  campaign["id"])["budget_planned"])
        # Exactly one a day is enough.
        self.assertEqual(self._choose_total(campaign["id"], 31).status_code, 200)

    def test_a_new_total_on_a_ready_campaign_resplits_the_ad_sets(self):
        campaign, groups = self._ready()
        response = self._choose_total(campaign["id"], 20005)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        by_id = {g["id"]: g for g in groups}
        self.assertEqual(
            sorted((r["role"], r["before"], r["after"]) for r in body["resplit"]),
            [("explore", 200, 400), ("new", 500, 1000), ("retarget", 300, 600)],
        )
        self.assertEqual({r["group_id"] for r in body["resplit"]}, set(by_id))
        detail = body["campaign"]
        self.assertEqual(sorted(float(g["daily_budget"]) for g in detail["groups"]),
                         [400, 600, 1000])
        # Adopt's rounding: 2000 a day x 10 days, and the derived total agrees.
        self.assertEqual(float(detail["budget_planned"]), 20000)
        self.assertEqual(float(detail["budget_total"]), 20000)

    def test_a_bound_ad_set_refuses_the_new_total_and_changes_nothing(self):
        campaign, groups = self._ready()
        web.conn.execute("UPDATE ads_delivery_group SET local_state = 'bound' WHERE id = %s",
                         (groups[0]["id"],))
        web.conn.commit()
        response = self._choose_total(campaign["id"], 20005)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "campaign_bound")
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(float(detail["budget_planned"]), 10000)
        self.assertEqual(sorted(float(g["daily_budget"]) for g in detail["groups"]),
                         [200, 300, 500])

    def test_the_period_cannot_change_after_adoption_but_the_cap_can(self):
        campaign, _groups = self._ready()
        for body in ({"start_date": "2026-10-02"}, {"end_date": "2026-10-20"},
                     {"product_ids": []}, {"customer_group_ids": []},
                     {"constraints_json": {"platform": "google_ads"}}):
            with self.subTest(body=body):
                response = self.client.patch(self._url(campaign["id"]), json=body,
                                             headers=self.headers)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["error"]["code"], "plan_already_adopted")
        response = self.client.patch(self._url(campaign["id"]),
                                     json={"constraints_json": {"budget": 30000}},
                                     headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        draft = self._campaign(days=10)
        response = self.client.patch(self._url(draft["id"]), json={"end_date": "2026-10-20"},
                                     headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
