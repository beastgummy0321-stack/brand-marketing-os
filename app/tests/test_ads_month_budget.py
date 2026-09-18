"""Money falsifiers: whole month, attribution backfill, delta and unknown evidence."""

import unittest
from datetime import date
from unittest.mock import patch

from app.ads import month_budget as budget
from app.brand_intelligence import repository as brands
from app.core import db


def root(**changes):
    return {
        "id": "c",
        "platform": "fixture",
        "source_account": "a",
        "native_kind": "campaign",
        "native_id": "1",
        "parent_native_id": None,
        "budget_type": "daily",
        "budget_amount": 100,
        "currency": "TWD",
        "native_status": "ACTIVE",
        **changes,
    }


def spend(day, value, **changes):
    return {
        "entity_id": "c",
        "day": day,
        "metric_scope": "campaign",
        "currency": "TWD",
        "spend": value,
        "observed_at": "2026-09-10T12:00:00Z",
        **changes,
    }


def calculate(**changes):
    return budget.calculate(
        **{
            "amount": 10000,
            "currency": "TWD",
            "start": date(2026, 9, 1),
            "today": date(2026, 9, 10),
            "entities": [root()],
            "observations": [spend("2026-09-09", 900), spend("2026-09-10", 100)],
            "pending": [],
            "uncertainties": [],
            **changes,
        }
    )


def change(amount):
    return {
        "kind": "budget",
        "target_id": "c",
        "before": {"daily_amount": 100},
        "after": {"daily_amount": amount},
    }


class MonthlyCalculationTest(unittest.TestCase):
    def test_absent_spend_evidence_is_not_zero(self):
        result = calculate(observations=[], uncertainties=["帳戶尚未完整核對"])
        self.assertIsNone(result["known_spend"])
        self.assertIsNone(result["available"])

    def test_whole_month_not_next_review_and_today_not_double_counted(self):
        result = calculate()
        self.assertEqual(result["known_spend"], 1000)
        self.assertEqual(result["ongoing_estimate"], 2000)
        self.assertEqual(result["available"], 7000)
        self.assertEqual(result["period_end"], "2026-09-30")

    def test_unverified_decrease_does_not_fund_an_increase(self):
        result = calculate(pending=[change(50), change(150)])
        self.assertEqual(result["reserved_increases"], 1050)
        self.assertEqual(result["available"], 5950)

    def test_today_overspend_cannot_reduce_future_days(self):
        result = calculate(amount=2125, observations=[spend("2026-09-10", 175)])
        self.assertEqual(result["ongoing_estimate"], 2000)
        self.assertEqual(result["available"], -50)
        self.assertFalse(result["can_increase"])

    def test_unknown_parent_budget_is_not_absence_of_parent_budget(self):
        result = calculate(
            entities=[
                root(budget_amount=None, budget_raw={"values": {"daily_budget": "50000"}}),
                root(
                    id="s",
                    native_kind="adset",
                    native_id="2",
                    parent_native_kind="campaign",
                    parent_native_id="1",
                ),
            ]
        )
        self.assertIsNone(result["available"])
        self.assertFalse(result["can_increase"])

    def test_updated_budget_replaces_estimate_not_add_to_it(self):
        before = calculate(pending=[change(150)])
        after = calculate(entities=[root(budget_amount=150)], pending=[change(150)])
        self.assertEqual(after["reserved_increases"], 0)
        self.assertEqual(before["available"], after["available"])

    def test_repeated_approval_for_same_owner_does_not_double_reserve(self):
        result = calculate(pending=[change(150), change(175)])
        self.assertEqual(result["reserved_increases"], 1575)

    def test_attribution_backfill_spend_is_selected_once(self):
        result = calculate(
            observations=[
                spend("2026-09-09", 900, attribution_key="unavailable"),
                spend(
                    "2026-09-09",
                    950,
                    attribution_key="purchase",
                    observed_at="2026-09-10T13:00:00Z",
                ),
            ]
        )
        self.assertEqual(result["known_spend"], 950)

    def test_same_time_contradictory_spend_is_uncertain(self):
        result = calculate(observations=[spend("2026-09-09", 900), spend("2026-09-09", 950)])
        self.assertIsNone(result["available"])
        self.assertFalse(result["can_increase"])

    def test_ad_spend_is_not_added_to_campaign_spend(self):
        result = calculate(
            entities=[
                root(),
                root(
                    id="a",
                    native_kind="ad",
                    native_id="3",
                    parent_native_id="1",
                    budget_amount=None,
                ),
            ],
            observations=[
                spend("2026-09-09", 900),
                spend("2026-09-09", 900, entity_id="a", metric_scope="ad"),
            ],
        )
        self.assertEqual(result["known_spend"], 900)

    def test_lifetime_or_currency_or_unit_unknown_never_creates_balance(self):
        for entity in (
            root(budget_type="lifetime"),
            root(currency="USD"),
            root(budget_amount=None),
        ):
            with self.subTest(entity=entity):
                result = calculate(entities=[entity])
                self.assertIsNone(result["available"])
                self.assertFalse(result["can_increase"])

    def test_offer_expiry_bounds_commitment(self):
        result = calculate(entities=[root(end_date="2026-09-15")])
        self.assertEqual(result["ongoing_estimate"], 500)

    def test_paused_does_not_erase_already_spent_money(self):
        result = calculate(entities=[root(native_status="PAUSED")])
        self.assertEqual(result["known_spend"], 1000)
        self.assertEqual(result["ongoing_estimate"], 0)

    def test_pending_launch_without_end_reserves_through_month_end(self):
        result = calculate(
            entities=[],
            observations=[],
            pending=[{"kind": "launch", "target_id": "new", "after": {"daily_amount": 200}}],
        )
        self.assertEqual(result["reserved_increases"], 4200)

    def test_parent_and_child_budget_not_silently_summed(self):
        result = calculate(
            entities=[
                root(),
                root(
                    id="s",
                    native_kind="adset",
                    native_id="2",
                    parent_native_kind="campaign",
                    parent_native_id="1",
                ),
            ]
        )
        self.assertIsNone(result["available"])
        self.assertEqual(result["known_ongoing_estimate"], 2000)


class MonthlyPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="月額驗收", actor="test", client_name=None
        )["id"]
        self.month = "2026-09"

    def test_save_reopen_revision_and_keep_legacy_amount_untouched(self):
        with patch.object(budget, "_inventory", return_value=([], [], ["帳戶尚未核對"])):
            saved = budget.save(
                self.conn,
                self.org,
                self.brand,
                month=self.month,
                currency="TWD",
                amount=30000,
                expected_revision=0,
                actor="test",
            )
            read = budget.view(self.conn, self.org, self.brand, self.month)
            self.assertEqual(saved, read)
            self.assertEqual(read["amount"], 30000)
            self.assertIsNone(read["available"])
            with self.assertRaisesRegex(ValueError, "已被更新"):
                budget.save(
                    self.conn,
                    self.org,
                    self.brand,
                    month=self.month,
                    currency="TWD",
                    amount=50000,
                    expected_revision=0,
                    actor="test",
                )

    def test_unknown_allows_copy_and_risk_reduction_but_not_raise(self):
        with (
            patch.object(budget, "view", return_value={"amount": 30000, "uncertainties": ["缺日"]}),
            patch.object(budget.settings, "today_for_org", return_value=date(2026, 9, 10)),
        ):
            for item in ({"kind": "copy"}, {"kind": "pause"}, change(50)):
                budget.preflight(self.conn, self.org, self.brand, self.month, [item])
            with self.assertRaisesRegex(ValueError, "餘額尚不確定"):
                budget.preflight(self.conn, self.org, self.brand, self.month, [change(150)])

    def test_invalid_money_is_rejected_without_writing(self):
        for value in (True, -1, "NaN", "Infinity", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                budget.save(
                    self.conn,
                    self.org,
                    self.brand,
                    month=self.month,
                    currency="TWD",
                    amount=value,
                    expected_revision=0,
                    actor="test",
                )

    def test_other_org_cannot_confirm_budget(self):
        with self.assertRaisesRegex(ValueError, "找不到"):
            budget.save(
                self.conn,
                "wrong-org",
                self.brand,
                month=self.month,
                currency="TWD",
                amount=30000,
                expected_revision=0,
                actor="test",
            )
