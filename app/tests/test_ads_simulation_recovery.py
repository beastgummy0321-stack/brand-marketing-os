"""Isolated manual recovery: provenance, replacement, coverage and brand learning boundaries."""

from datetime import timedelta
from unittest.mock import patch

from pydantic import ValidationError

from app.ads import closeout, outcome, repository, simulation_mode, simulation_recovery, strategy
from app.ads.adapters import manual, simulated
from app.ads.simulation_routes import Save
from app.brand_intelligence import repository as bi_repo
from app.shared import web

from .test_ads_publish_simulated import SimulatedPublishTestBase


class SimulationRecoveryTest(SimulatedPublishTestBase):
    def setUp(self):
        super().setUp()
        self.c = self._campaign(
            start_date=self.today - timedelta(days=6),
            end_date=self.today,
            groups=1,
            ads_per_group=2,
        )
        self.args = (web.conn, self.org_id, self.brand_id, self.c["id"])
        self.ads = repository.campaign_detail(*self.args)["groups"][0]["ads"]

    def start(self):
        simulation_recovery.start(*self.args, actor="tester", confirm_isolation=True)

    def row(self, i=0, **values):
        return {
            "ad_id": self.ads[i]["id"],
            "spend": 100.0,
            "impressions": 1000,
            "clicks": 100,
            "purchases": 10,
            "revenue": 1000.0,
            **values,
        }

    def save(self, rows, revision=0, day=None, mode="daily_increment"):
        simulation_recovery.save_day(
            *self.args, day or self.today, rows, revision=revision, mode=mode, actor="tester"
        )

    def test_explicit_start_is_idempotent_and_never_invents_outcomes(self):
        with self.assertRaisesRegex(ValueError, "請確認"):
            simulation_recovery.start(*self.args, actor="tester", confirm_isolation=False)
        self.assertFalse(simulation_mode.enabled(web.conn, self.org_id, self.brand_id))
        self.start()
        first = self._actions(self.c["id"])
        self.start()
        simulated.generate_outcomes(*self.args)
        self.assertEqual(first, self._actions(self.c["id"]))
        self.assertEqual(self._outcome_rows(self.c["id"]), [])
        self.assertTrue(
            all(
                a["external_id"].startswith("sim_")
                for a in repository.campaign_detail(*self.args)["groups"][0]["ads"]
            )
        )

    def test_disjoint_saved_days_never_mark_the_gap_as_read(self):
        self.start()
        first = self.today - timedelta(days=6)
        self.save([self.row()], day=first)
        self.save([self.row()], day=first + timedelta(days=2))

        sync = repository.get_campaign(*self.args)["context_json"]["external_sync"]
        self.assertEqual(sync["observations"]["coverage"],
                         {"start": first.isoformat(), "end": first.isoformat()})
        missing = outcome.summary(*self.args)["coverage"]["missing_days"]
        self.assertIn((first + timedelta(days=1)).isoformat(), missing)
        self.assertNotIn(first.isoformat(), missing)

        self.save([self.row()], day=first + timedelta(days=1))
        sync = repository.get_campaign(*self.args)["context_json"]["external_sync"]
        self.assertEqual(sync["observations"]["coverage"],
                         {"start": first.isoformat(),
                          "end": (first + timedelta(days=1)).isoformat()})

    def test_zero_and_missing_are_distinct_and_resend_does_not_accumulate(self):
        self.start()
        zero = self.row(spend=0.0, impressions=0, clicks=0, purchases=0, revenue=0.0)
        self.save([zero])
        self.save([zero])
        read = simulation_recovery.read_day(*self.args, self.today)
        self.assertEqual(read["revision"], 1)
        self.assertEqual(len(read["rows"]), 1)
        self.assertEqual(read["receipts"][str(self.today)]["missing_ad_count"], 1)
        self.assertEqual(float(read["rows"][0]["spend"]), 0)
        self.assertEqual(len(self._outcome_rows(self.c["id"])), 2)
        self.save([self.row(), self.row(1)], revision=1)
        self.assertEqual(outcome.summary(*self.args)["totals"]["spend"], 200)
        with self.assertRaisesRegex(ValueError, "其他操作"):
            self.save([zero], revision=1)
        self.save([], revision=2)
        self.assertEqual(self._outcome_rows(self.c["id"]), [])

    def test_rejects_wrong_dates_coordinates_and_cumulative_mode(self):
        self.start()
        for rows, day, mode in [
            ([self.row()], self.today + timedelta(days=1), "daily_increment"),
            ([self.row()], self.today - timedelta(days=7), "daily_increment"),
            ([self.row(ad_id="foreign")], self.today, "daily_increment"),
            ([self.row(), self.row()], self.today, "daily_increment"),
            ([self.row(clicks=1001)], self.today, "daily_increment"),
            ([self.row()], self.today, "cumulative"),
        ]:
            with self.subTest(rows=rows, day=day, mode=mode), self.assertRaises(ValueError):
                self.save(rows, day=day, mode=mode)
        self.assertEqual(self._outcome_rows(self.c["id"]), [])

    def test_schema_rejects_missing_negative_nonfinite_and_fractional_counts(self):
        for key, value in [
            ("spend", -1),
            ("revenue", float("inf")),
            ("clicks", 0.5),
            ("purchases", True),
            ("impressions", "1"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                Save.model_validate(
                    {"revision": 0, "mode": "daily_increment", "rows": [self.row(**{key: value})]}
                )
        row = self.row()
        del row["revenue"]
        with self.assertRaises(ValidationError):
            Save.model_validate({"revision": 0, "mode": "daily_increment", "rows": [row]})

    def test_cannot_mix_real_bindings_accounts_or_environment(self):
        with (
            patch(
                "app.ads.simulation_recovery.meta_repo.bound_account_ids_for_brand",
                return_value=["act_real"],
            ),
            self.assertRaisesRegex(ValueError, "真實"),
        ):
            self.start()
        with patch("app.ads.simulation_recovery.config.settings") as config:
            config.return_value.brand_os_env = "production"
            with self.assertRaisesRegex(ValueError, "本機"):
                self.start()
        self.start()
        with self.assertRaisesRegex(ValueError, "隔離模擬"):
            manual.publish(*self.args, actor="tester")

    def test_old_random_data_is_rejected_before_brand_is_marked(self):
        simulated.publish(*self.args, actor="tester")
        with self.assertRaisesRegex(ValueError, "已有示意成效"):
            self.start()
        self.assertFalse(simulation_mode.enabled(web.conn, self.org_id, self.brand_id))

    def test_close_freezes_provenance_and_keeps_learning_in_brand(self):
        self.start()
        for i in range(7):
            self.save([self.row(), self.row(1)], day=self.today - timedelta(days=i))
        closed = closeout.close(*self.args, actor="tester")
        self.assertEqual(closed["verdict"], "達成")
        self.assertEqual(closed["verdict_json"]["data_source"], "isolated_simulation")
        self.assertEqual(len(closed["verdict_json"]["simulation_receipts"]), 7)
        with self.assertRaisesRegex(ValueError, "凍結"):
            self.save([], revision=1)
        self.assertEqual(
            closeout.close(*self.args, actor="tester")["verdict_json"], closed["verdict_json"]
        )
        # Two consistent campaigns lift the next-round learning to likely.
        second = self._campaign(
            start_date=self.today - timedelta(days=6),
            end_date=self.today,
            groups=1,
            ads_per_group=1,
        )
        args2 = (web.conn, self.org_id, self.brand_id, second["id"])
        simulation_recovery.start(*args2, actor="tester", confirm_isolation=True)
        ad2 = repository.campaign_detail(*args2)["groups"][0]["ads"][0]["id"]
        for i in range(7):
            simulation_recovery.save_day(
                *args2,
                self.today - timedelta(days=i),
                [self.row(ad_id=ad2)],
                revision=0,
                mode="daily_increment",
                actor="tester",
            )
        closeout.close(*args2, actor="tester")
        text, basis = strategy._learnings_section(web.conn, self.brand_id)
        self.assertIn("隔離模擬，非市場實證", text)
        self.assertTrue(basis)
        other = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="other", actor="tester", client_name=None
        )
        self.assertEqual(strategy._learnings_section(web.conn, other["id"])[1], [])

    def test_partial_recovery_cannot_be_judged_as_complete(self):
        self.start()
        self.save([self.row(purchases=100)])
        closed = closeout.close(*self.args, actor="tester")
        self.assertEqual(closed["verdict"], "看不出")
        self.assertIn("缺日或缺廣告", closed["verdict_json"]["missing"])
