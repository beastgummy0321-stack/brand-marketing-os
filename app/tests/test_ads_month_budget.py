"""Money falsifiers: whole month, attribution backfill, delta and unknown evidence."""

import unittest
from datetime import date
from unittest.mock import patch

from app.ads import external_repository as external
from app.ads import month_budget as budget
from app.brand_intelligence import repository as brands
from app.core import db


def root(**changes):
    return {
        "id": "c",
        # F49 Contract L: an owner's delivery is read through its platform's status table
        # (`lifecycle.may_spend`), so the fixture names a platform that has one.
        "platform": "meta",
        "source_account": "a",
        "native_kind": "campaign",
        "native_id": "1",
        "parent_native_id": None,
        "budget_type": "daily",
        "budget_amount": 100,
        "currency": "TWD",
        "native_status": "ACTIVE",
        "sync_status": "success",
        "launch_read_verified": True,
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

    def test_read_back_launch_reserves_only_unrepresented_owner_days(self):
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "start_date": "2026-09-10", "end_date": "2026-09-13"}}
        owner = root(id="external", campaign_id="internal", budget_amount=140,
                     start_date="2026-09-10", end_date="2026-09-13")
        cases = [
            ("unbuilt", [], 560, 0),
            ("campaign budget", [owner], 0, 560),
            ("partial amount", [{**owner, "budget_amount": 100}], 160, 400),
            ("partial dates", [{**owner, "end_date": "2026-09-11"}], 280, 280),
            ("unrelated", [{**owner, "campaign_id": "other"}], 560, 560),
            ("paused", [{**owner, "native_status": "PAUSED"}], 560, 0),
        ]
        for label, entities, reserved, ongoing in cases:
            with self.subTest(label=label):
                result = calculate(entities=entities, observations=[], pending=[launch, launch])
                self.assertEqual(result["reserved_increases"], reserved)
                self.assertEqual(result["ongoing_estimate"], ongoing)
                self.assertEqual(result["available"], 10000 - reserved - ongoing)

    def test_read_back_launch_uses_abos_once_and_keeps_budget_delta(self):
        parent = root(id="external", campaign_id="internal", budget_amount=None,
                      budget_type="unknown", budget_raw={"owner": "children_verified"})
        children = [root(id=f"s{i}", native_id=str(i+2), campaign_id="internal",
                         native_kind="adset", parent_native_kind="campaign", parent_native_id="1",
                         budget_amount=70, end_date="2026-09-13") for i in range(2)]
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "start_date": "2026-09-10", "end_date": "2026-09-13"}}
        increase = {"kind": "budget", "target_id": "s0", "target": {"end_date": "2026-09-13"},
                    "before": {"daily_amount": 70}, "after": {"daily_amount": 84}}
        result = calculate(
            entities=[parent, *children], observations=[], pending=[launch, increase])
        self.assertEqual(result["ongoing_estimate"], 560)
        self.assertEqual(result["reserved_increases"], 56)
        self.assertEqual(result["available"], 9384)

    def test_read_back_launch_does_not_reserve_today_spending_again(self):
        owner = root(campaign_id="internal", budget_amount=140, end_date="2026-09-13")
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "end_date": "2026-09-13"}}
        result = calculate(
            entities=[owner], observations=[spend("2026-09-10", 100)], pending=[launch])
        self.assertEqual(result["known_spend"], 100)
        self.assertEqual(result["ongoing_estimate"], 460)
        self.assertEqual(result["reserved_increases"], 0)
        self.assertEqual(result["available"], 9440)

    def test_launch_credit_requires_same_campaign_and_scoped_parent(self):
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "end_date": "2026-09-13"}}
        parent = root(campaign_id="internal", budget_amount=None, budget_type="unknown",
                      budget_raw={"owner": "children_verified"})
        child = root(id="s", native_id="2", campaign_id="internal", native_kind="adset",
                     parent_native_kind="campaign", parent_native_id="1", budget_amount=140,
                     end_date="2026-09-13")
        for bad_parent in ({**parent, "campaign_id": "other"},
                           {**parent, "source_account": "other"},
                           {**parent, "brand_id": "other"}):
            with self.subTest(parent=bad_parent):
                result = calculate(entities=[bad_parent, child], observations=[], pending=[launch])
                self.assertEqual(result["reserved_increases"], 560)

    def test_launch_credit_does_not_cross_date_gaps(self):
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "start_date": "2026-09-10", "end_date": "2026-09-13"}}
        owner = root(campaign_id="internal", budget_amount=140, start_date="2026-09-12",
                     end_date="2026-09-15")
        result = calculate(entities=[owner], observations=[], pending=[launch])
        self.assertEqual(result["reserved_increases"], 280)
        self.assertEqual(result["ongoing_estimate"], 560)
        self.assertEqual(result["available"], 9160)

    def test_read_back_launch_cannot_make_unknown_budget_spendable(self):
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "end_date": "2026-09-13"}}
        for owner in (root(campaign_id="internal", budget_amount=None),
                      root(campaign_id="internal", currency="USD")):
            with self.subTest(owner=owner):
                result = calculate(entities=[owner], observations=[], pending=[launch])
                self.assertEqual(result["reserved_increases"], 560)
                self.assertIsNone(result["available"])
                self.assertFalse(result["can_increase"])

    def test_launch_hold_requires_known_running_and_clean_structure_read(self):
        launch = {"kind": "launch", "target_id": "internal", "after": {
            "daily_amount": 140, "end_date": "2026-09-13"}}
        for extra in ({"native_status": None}, {"native_status": "MYSTERY"},
                      {"sync_status": "failed"}, {"launch_read_verified": False},
                      {"launch_read_verified": None}):
            with self.subTest(extra=extra):
                owner = root(campaign_id="internal", budget_amount=140,
                             end_date="2026-09-13", **extra)
                result = calculate(entities=[owner], observations=[], pending=[launch])
                self.assertEqual(result["reserved_increases"], 560)
                if extra.get("native_status", "ACTIVE") != "ACTIVE":
                    self.assertIsNone(result["available"])

    def test_ongoing_owners_name_each_running_entity_with_days_times_daily(self):
        # F40-I01: the approve page's 預留 breakdown -- 9/10 … 9/14 is 5 days at 100 a day.
        result = calculate(
            entities=[root(name="九月活動", end_date="2026-09-14")],
            observations=[spend("2026-09-09", 900)],
        )
        self.assertEqual(result["ongoing_owners"], [
            {"entity_id": "c", "name": "九月活動", "daily": 100.0, "days": 5,
             "commitment": 500.0},
        ])
        owner = result["ongoing_owners"][0]
        self.assertEqual(owner["days"] * owner["daily"], owner["commitment"])
        self.assertEqual(result["ongoing_estimate"], 500)

    def test_ongoing_owners_ordered_by_commitment_desc_and_skip_closed(self):
        result = calculate(
            entities=[
                root(id="small", native_id="1", name="小", end_date="2026-09-11"),
                root(id="big", native_id="2", name="大", budget_amount=300),
                root(id="paused", native_id="3", name="停", native_status="PAUSED"),
            ],
            observations=[],
        )
        self.assertEqual(
            [(o["entity_id"], o["commitment"]) for o in result["ongoing_owners"]],
            [("big", 6300.0), ("small", 200.0)],
        )

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

    def test_each_refusal_carries_its_reason_code_and_sentence(self):
        """F51 Contract C: `preflight` raises `MonthBudgetBlocked` with one of three codes, the
        sentence read from the one table (`BLOCKED_TEXT`)."""
        cases = (
            ("month_not_current", date(2026, 10, 1), {"amount": 30000, "uncertainties": []}),
            ("balance_unknown", date(2026, 9, 10), {"amount": 30000, "uncertainties": ["缺日"]}),
            ("balance_unknown", date(2026, 9, 10), {"amount": None, "uncertainties": []}),
            ("over_month_total", date(2026, 9, 10),
             {"amount": 30000, "uncertainties": [], "available": -1}),
        )
        for reason, today, view in cases:
            with (
                self.subTest(reason=reason, view=view),
                patch.object(budget, "view", return_value=view),
                patch.object(budget.settings, "today_for_org", return_value=today),
                self.assertRaises(budget.MonthBudgetBlocked) as caught,
            ):
                budget.preflight(self.conn, self.org, self.brand, self.month, [change(150)])
            self.assertEqual(caught.exception.code, reason)
            self.assertEqual(str(caught.exception), budget.BLOCKED_TEXT[reason])
            self.assertIsInstance(caught.exception, ValueError)

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

    def test_total_must_be_above_zero_and_the_refusal_names_the_field(self):
        """F47-I06 (Contract A, drill-10 V3): 0 and a negative are refused with a sentence, never
        stored as 0; nothing is written, so the month stays unset (`amount` null)."""
        for value, sentence in ((0, "每月品牌總額要大於 0。"), (-5000, "每月品牌總額要大於 0。"),
                                (None, "每月品牌總額請填數字。")):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                budget.save(
                    self.conn, self.org, self.brand, month=self.month, currency="TWD",
                    amount=value, expected_revision=0, actor="test",
                )
            self.assertEqual(str(caught.exception), sentence)
        with patch.object(budget, "_inventory", return_value=([], [], [])):
            self.assertIsNone(budget.view(self.conn, self.org, self.brand, self.month)["amount"])

    def test_route_answers_the_store_sentence_for_zero_negative_and_empty(self):
        from fastapi.testclient import TestClient

        from app import main

        client = TestClient(main.app)
        self.conn.commit()
        for amount, sentence in ((0, "每月品牌總額要大於 0。"), (-5000, "每月品牌總額要大於 0。"),
                                 (None, "每月品牌總額請填數字。")):
            with self.subTest(amount=amount):
                response = client.put(
                    f"/api/ads/brands/{self.brand}/monthly-budget",
                    json={"month": self.month, "currency": "TWD", "amount": amount,
                          "expected_revision": 0},
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["error"]["message"], sentence)

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


class FreshnessClockTest(unittest.TestCase):
    """F39-I06 (drill-7 #17, one clock): `_fresh` reads the module-level `now_utc`, the name the
    drill clock rebinds -- never `datetime.now`, which the drill cannot move."""

    def test_fresh_follows_module_now_utc(self):
        from datetime import UTC, datetime, timedelta

        stamp = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        with patch.object(budget, "now_utc", return_value=stamp + timedelta(hours=25)):
            self.assertFalse(budget._fresh(stamp.isoformat()))
        with patch.object(budget, "now_utc", return_value=stamp + timedelta(hours=23)):
            self.assertTrue(budget._fresh(stamp.isoformat()))
        with patch.object(budget, "now_utc", return_value=stamp + timedelta(hours=23)):
            self.assertTrue(budget._fresh(stamp.replace(tzinfo=None).isoformat() + "Z"))
        self.assertFalse(budget._fresh(None))


class ImportedCampaignMonthCoverageTest(unittest.TestCase):
    """F49 Contract V: an imported campaign with no account-month proof is complete for the month
    only when every campaign day so far was read (`coverage.covered`) -- a range read in two
    parts counts, a gap does not."""

    GAP = "本月成效仍有缺日，已知花費不是完整月累計。"

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="月額缺日", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="既有活動"
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        self.conn.commit()

        class Reader:
            def accounts(self, conn, org, brand):
                return [{"account_id": "act_1", "currency": "TWD", "timezone_name": "Asia/Taipei"}]

        patcher = patch.object(
            budget.channels, "external_reader",
            side_effect=lambda key: Reader() if key == "meta" else None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, start, end):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"status": "success", "coverage": {"start": str(start), "end": str(end)}},
        )
        self.conn.commit()

    def issues(self):
        return budget._inventory(self.conn, self.org, self.brand, date(2026, 9, 1),
                                 date(2026, 9, 10))[2]

    def test_a_fully_read_month_has_no_missing_days(self):
        # Two clean reads finishing in either order: the union covers the month so far.
        self.read(date(2026, 9, 6), date(2026, 9, 10))
        self.read(date(2026, 9, 1), date(2026, 9, 5))
        self.assertNotIn(self.GAP, self.issues())

    def test_a_gap_is_missing_days(self):
        self.read(date(2026, 9, 1), date(2026, 9, 4))
        self.read(date(2026, 9, 6), date(2026, 9, 10))
        self.assertIn(self.GAP, self.issues())

    def test_inventory_requires_fresh_complete_structure_before_launch_credit(self):
        from datetime import UTC, datetime, timedelta

        stamp = datetime(2026, 9, 10, 12, tzinfo=UTC)
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "native_status": "ACTIVE", "sync_status": "success",
             "last_success_at": stamp, "budget_type": "daily", "budget_amount": 140,
             "currency": "TWD", "end_date": date(2026, 9, 13)},
        )
        launch = {"kind": "launch", "target_id": self.campaign, "after": {
            "daily_amount": 140, "end_date": "2026-09-13"}}
        cases = [
            ({}, 560),
            ({"status": "success", "last_success_at": stamp - timedelta(days=2)}, 560),
            ({"status": "success", "last_success_at": stamp}, 0),
            ({"status": "partial", "error": "incomplete"}, 560),
            ({"status": "failed", "error": "offline"}, 560),
        ]
        for state, reserved in cases:
            with self.subTest(state=state), patch.object(budget, "now_utc", return_value=stamp):
                external.record_sync(
                    self.conn, self.org, self.brand, self.campaign,
                    section="structure", state=state,
                )
                entities, observations, _ = budget._inventory(
                    self.conn, self.org, self.brand, date(2026, 9, 1), date(2026, 9, 10))
                result = calculate(entities=entities, observations=observations, pending=[launch])
                self.assertEqual(result["reserved_increases"], reserved)
