"""F11 comparison controls, explicit confirmation, stale snapshots and conservative results."""

import json
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
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

    def test_settings_contract_replaces_overrides_and_restores_one_value(self):
        state = experiments.read(*self.args)
        settings = state["settings"]
        self.assertEqual(settings["revision"], "0")
        self.assertEqual(settings["scope"], "campaign")
        self.assertEqual(
            settings["defaults"],
            {
                "min_days": 7,
                "min_conversions_each": 10,
                "relative_difference": 0.1,
                "window": {
                    "start": str(self.today - timedelta(days=6)),
                    "end": str(self.today),
                },
            },
        )
        first = experiments.save_settings(
            *self.args,
            revision="0",
            overrides={"min_conversions_each": 12, "relative_difference": 0.25},
            actor="tester",
        )
        self.assertEqual(first["revision"], "1")
        self.assertEqual(first["customized"], ["min_conversions_each", "relative_difference"])
        second = experiments.save_settings(
            *self.args,
            revision="1",
            overrides={"relative_difference": 0.25},
            actor="tester",
        )
        self.assertEqual(second["overrides"], {"relative_difference": 0.25})
        self.assertEqual(second["effective"]["min_conversions_each"], 10)
        self.assertEqual(second["effective"]["relative_difference"], 0.25)

    def test_settings_reject_unknown_invalid_and_stale_values(self):
        invalid = [
            {"unknown": 1},
            {"min_days": 0},
            {"min_days": True},
            {"min_conversions_each": 1.5},
            {"relative_difference": float("nan")},
            {"relative_difference": 1.01},
            {"window": {"start": "bad", "end": str(self.today)}},
            {
                "window": {
                    "start": str(self.today - timedelta(days=7)),
                    "end": str(self.today),
                }
            },
            {"min_days": 8},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(experiments.InvalidSettings):
                experiments.save_settings(
                    *self.args, revision="0", overrides=overrides, actor="tester"
                )
        experiments.save_settings(
            *self.args, revision="0", overrides={"relative_difference": 0.2}, actor="tester"
        )
        with self.assertRaisesRegex(experiments.StaleSettings, "重新讀取"):
            experiments.save_settings(
                *self.args, revision="0", overrides={}, actor="tester"
            )

    def test_non_default_thresholds_and_window_drive_text_and_judgment(self):
        settings = experiments.save_settings(
            *self.args,
            revision="0",
            overrides={
                "min_days": 3,
                "min_conversions_each": 2,
                "relative_difference": 0.6,
                "window": {
                    "start": str(self.today - timedelta(days=2)),
                    "end": str(self.today),
                },
            },
            actor="tester",
        )
        self.assertEqual(
            settings["effective"]["window"]["start"],
            str(self.today - timedelta(days=2)),
        )
        proposal, _ = experiments.propose(*self.args)
        self.assertIn("60%", proposal["hypothesis"])
        self.assertEqual(proposal["rules"]["min_conversions_each"], 2)
        self.confirm(proposal["fingerprint"])
        self.fill(days=3, purchases=2)
        result = experiments.read(*self.args)["result"]
        self.assertEqual(result["verdict"], "看不出")
        self.assertIn("60%", result["reason"])

    def test_same_effective_defaults_keep_old_confirmation_valid_and_restore_it(self):
        original, _ = experiments.propose(*self.args)
        legacy = {
            **original,
            "rules": {
                "min_days": 7,
                "min_purchases_each": 10,
                "relative_difference": 0.1,
            },
            "confirmed_at": "2026-09-01T00:00:00+00:00",
            "confirmed_by": "legacy-tester",
            "timing": "before_data",
        }
        legacy = json.loads(json.dumps(legacy, default=str))
        detail = repository.get_campaign(*self.args)
        context = {**detail["context_json"], "comparison_plan": legacy}
        web.conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE id=%s",
            (jsonb(context), self.args[-1]),
        )
        legacy_read = experiments.read(*self.args)
        self.assertEqual(legacy_read["confirmed"], legacy)
        self.assertFalse(legacy_read["stale"])
        same = experiments.save_settings(
            *self.args,
            revision="0",
            overrides={
                "min_days": 7,
                "min_conversions_each": 10,
                "relative_difference": 0.1,
                "window": original["window"],
            },
            actor="tester",
        )
        self.assertEqual(experiments.propose(*self.args)[0]["fingerprint"], original["fingerprint"])
        self.assertFalse(experiments.read(*self.args)["stale"])
        changed = experiments.save_settings(
            *self.args,
            revision=same["revision"],
            overrides={"relative_difference": 0.2},
            actor="tester",
        )
        self.assertTrue(experiments.read(*self.args)["stale"])
        experiments.save_settings(
            *self.args, revision=changed["revision"], overrides={}, actor="tester"
        )
        restored = experiments.read(*self.args)
        self.assertFalse(restored["stale"])
        self.assertEqual(restored["confirmed"], legacy)
        self.assertIn("min_purchases_each", original["snapshot"]["rules"])

    def test_saved_window_becomes_unavailable_after_period_shrinks_until_reset(self):
        saved = experiments.save_settings(
            *self.args,
            revision="0",
            overrides={
                "min_days": 3,
                "window": {
                    "start": str(self.today - timedelta(days=4)),
                    "end": str(self.today - timedelta(days=2)),
                },
            },
            actor="tester",
        )
        repository.update_campaign(
            *self.args,
            {"start_date": self.today - timedelta(days=2), "end_date": self.today},
        )
        unavailable = experiments.read(*self.args)
        self.assertIsNone(unavailable["proposal"])
        self.assertIn("不再符合共同投放期間", unavailable["missing"])
        self.assertEqual(
            unavailable["settings"]["overrides"]["window"]["start"],
            str(self.today - timedelta(days=4)),
        )
        with self.assertRaisesRegex(ValueError, "不再符合"):
            experiments.confirm(
                *self.args,
                fingerprint="old",
                controls_checked=True,
                actor="tester",
            )
        reset = experiments.save_settings(
            *self.args, revision=saved["revision"], overrides={}, actor="tester"
        )
        self.assertEqual(reset["overrides"], {})
        self.assertIsNotNone(experiments.read(*self.args)["proposal"])

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
        with self.assertRaisesRegex(experiments.ClosedSettings, "已結案"):
            experiments.save_settings(
                *self.args, revision="0", overrides={}, actor="tester"
            )

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
        with self.assertRaisesRegex(ValueError, "找不到"):
            experiments.save_settings(
                *args, revision="0", overrides={}, actor="tester"
            )

    def test_unsupported_metric_is_explicitly_unavailable_without_purchase_fallback(self):
        detail = repository.campaign_detail(*self.args)
        detail["success_metric"] = "platform_custom_metric"
        with patch("app.ads.experiments._detail", return_value=detail):
            proposal, missing = experiments.propose(*self.args)
        self.assertIsNone(missing)
        self.assertIn("不支援", proposal["metric_label"])
        result = experiments.judge(
            *self.args, proposal=proposal, confirmed=True, stale=False
        )
        self.assertEqual(result["verdict"], "看不出")
        self.assertIn("不支援活動成功指標", result["reason"])

    def test_settings_proposal_confirmation_and_judgment_do_not_call_llm(self):
        with patch("app.llm.gateway.run_task", side_effect=AssertionError("unexpected LLM")) as run:
            state = experiments.read(*self.args)
            saved = experiments.save_settings(
                *self.args,
                revision=state["settings"]["revision"],
                overrides={"min_conversions_each": 2},
                actor="tester",
            )
            proposal, _ = experiments.propose(*self.args)
            self.confirm(proposal["fingerprint"])
            self.fill(purchases=2)
            self.assertEqual(
                experiments.read(*self.args)["settings"]["revision"], saved["revision"]
            )
            run.assert_not_called()

    def test_http_put_contract_and_revision_conflict(self):
        web.conn.commit()
        client = TestClient(main.app)
        url = (
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.args[-1]}/comparison"
        )
        state = client.get(url)
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()["settings"]["revision"], "0")
        updated = client.put(
            url,
            json={"revision": "0", "overrides": {"min_conversions_each": 12}},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["settings"]["effective"]["min_conversions_each"], 12)
        stale = client.put(url, json={"revision": "0", "overrides": {}})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["error"]["code"], "comparison_settings_stale")
        unknown = client.put(
            url,
            json={"revision": "1", "overrides": {"platform": "meta"}},
        )
        self.assertEqual(unknown.status_code, 400, unknown.text)
        self.assertEqual(unknown.json()["error"]["code"], "comparison_settings_invalid")


    def test_query_order_is_not_a_material_change(self):
        self.confirm()
        detail = repository.campaign_detail(*self.args)
        detail["groups"] = list(reversed(detail["groups"]))
        for group in detail["groups"]:
            group["ads"] = list(reversed(group["ads"]))
        with patch("app.ads.experiments._detail", return_value=detail):
            self.assertFalse(experiments.read(*self.args)["stale"])
