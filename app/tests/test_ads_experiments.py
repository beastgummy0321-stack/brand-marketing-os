"""F11 comparison controls, explicit confirmation, stale snapshots and conservative results."""

from datetime import timedelta
from unittest.mock import patch

from app.ads import closeout, experiments, plan, repository, simulation_recovery
from app.core.db import jsonb
from app.shared import web

from .test_ads_publish_simulated import SimulatedPublishTestBase


class ExperimentTest(SimulatedPublishTestBase):
    def setUp(self):
        super().setUp()
        c = self._campaign(
            start_date=self.today - timedelta(days=6),
            end_date=self.today,
            groups=1,
            ads_per_group=2,
        )
        self.args = (web.conn, self.org_id, self.brand_id, c["id"])
        self.ads = repository.campaign_detail(*self.args)["groups"][0]["ads"]
        plan.update_ad(
            web.conn,
            self.org_id,
            self.brand_id,
            self.ads[1]["id"],
            {"coordinates": {"hook": "comparison"}},
            actor="tester",
        )

    def confirm(self, fingerprint=None):
        p, _ = experiments.propose(*self.args)
        experiments.confirm(
            *self.args,
            fingerprint=fingerprint or p["fingerprint"],
            controls_checked=True,
            actor="tester",
        )

    def fill(self, days=7, purchases=10, second_spend=200):
        simulation_recovery.start(*self.args, actor="tester", confirm_isolation=True)
        for i in range(days):
            rows = [
                {
                    "ad_id": a["id"],
                    "spend": 100.0 if j == 0 else second_spend,
                    "impressions": 1000,
                    "clicks": 100,
                    "purchases": purchases,
                    "revenue": 1000.0,
                }
                for j, a in enumerate(self.ads)
            ]
            simulation_recovery.save_day(
                *self.args,
                self.today - timedelta(days=i),
                rows,
                revision=0,
                mode="daily_increment",
                actor="tester",
            )

    def test_read_only_proposal_and_explicit_idempotent_confirmation(self):
        before = repository.get_campaign(*self.args)["context_json"]
        state = experiments.read(*self.args)
        p = state["proposal"]
        self.assertEqual(repository.get_campaign(*self.args)["context_json"], before)
        self.assertEqual(p["variable"], "開場")
        self.assertEqual(len(p["variants"]), 2)
        self.assertEqual(state["result"]["verdict"], "看不出")
        with self.assertRaisesRegex(ValueError, "核對"):
            experiments.confirm(
                *self.args, fingerprint=p["fingerprint"], controls_checked=False, actor="tester"
            )
        self.confirm()
        first = experiments.read(*self.args)["confirmed"]
        self.confirm()
        self.assertEqual(experiments.read(*self.args)["confirmed"], first)
        self.assertEqual(first["confirmed_by"], "tester")
        self.assertEqual(first["timing"], "before_data")

    def test_different_audiences_or_multiple_variables_are_not_a_comparison(self):
        for dimension in ("audience", "offer"):
            with self.subTest(dimension=dimension):
                plan.update_ad(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    self.ads[1]["id"],
                    {"coordinates": {dimension: "different"}},
                    actor="tester",
                )
                p, reason = experiments.propose(*self.args)
                self.assertIsNone(p)
                self.assertIn("缺少合格對照", reason)
                plan.update_ad(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    self.ads[1]["id"],
                    {"coordinates": {dimension: self.ads[1][f"{dimension}_key"]}},
                    actor="tester",
                )

    def test_conditions_change_requires_a_fresh_confirmation(self):
        self.confirm()
        old = experiments.read(*self.args)["confirmed"]["fingerprint"]
        repository.update_campaign(*self.args, {"success_target": 200})
        changed = experiments.read(*self.args)
        self.assertTrue(changed["stale"])
        self.assertIn("已過期", changed["result"]["reason"])
        with self.assertRaisesRegex(ValueError, "已變更"):
            self.confirm(old)
        self.confirm()
        self.assertFalse(experiments.read(*self.args)["stale"])

    def test_material_or_manual_delivery_changes_invalidate_confirmation(self):
        self.confirm()
        with patch("app.ads.experiments._materials", return_value={"ad": {"output_id": "new"}}):
            self.assertTrue(experiments.read(*self.args)["stale"])
        detail = repository.get_campaign(*self.args)
        context = {**detail["context_json"], "manual_delivery": {"g": {"values": {"utm": "new"}}}}
        web.conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE id=%s", (jsonb(context), self.args[-1])
        )
        self.assertTrue(experiments.read(*self.args)["stale"])

    def test_missing_days_and_small_samples_never_produce_a_winner(self):
        self.confirm()
        self.fill(days=1, purchases=1)
        result = experiments.read(*self.args)
        self.assertFalse(result["stale"])
        self.assertIn("缺日", result["result"]["reason"])
        self.fill(days=7, purchases=1)
        self.assertIn("樣本不足", experiments.read(*self.args)["result"]["reason"])

    def test_complete_simulated_observation_is_not_claimed_as_causal(self):
        self.confirm()
        self.fill()
        result = experiments.read(*self.args)
        self.assertEqual(result["result"]["verdict"], "觀察到差異")
        self.assertIn("不構成市場優勝或因果", result["result"]["reason"])
        self.assertEqual(result["result"]["values"][0]["value"], 10)
        closed = closeout.close(*self.args, actor="tester")
        self.assertEqual(closed["status"], "closed")
        with self.assertRaisesRegex(ValueError, "已結案"):
            self.confirm()

    def test_post_data_confirmation_is_labelled_retrospective_and_budget_cap_stops_judgment(self):
        self.fill(second_spend=400)
        self.confirm()
        state = experiments.read(*self.args)
        self.assertEqual(state["confirmed"]["timing"], "retrospective")
        self.assertEqual(state["result"]["verdict"], "看不出")
        self.assertIn("停止條件", state["result"]["reason"])

    def test_small_difference_does_not_overstate_winner(self):
        self.fill(second_spend=101)
        self.confirm()
        self.assertIn("未達預設", experiments.read(*self.args)["result"]["reason"])

    def test_other_brand_cannot_read_or_confirm_this_campaign(self):
        args = (web.conn, self.org_id, "foreign", self.args[-1])
        with self.assertRaisesRegex(ValueError, "找不到"):
            experiments.read(*args)
        with self.assertRaisesRegex(ValueError, "找不到"):
            experiments.confirm(*args, fingerprint="fake", controls_checked=True, actor="tester")


    def test_query_order_is_not_a_material_change(self):
        self.confirm()
        detail = repository.campaign_detail(*self.args)
        detail["groups"] = list(reversed(detail["groups"]))
        for group in detail["groups"]:
            group["ads"] = list(reversed(group["ads"]))
        with patch("app.ads.experiments._detail", return_value=detail):
            self.assertFalse(experiments.read(*self.args)["stale"])
