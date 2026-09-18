"""Only explicit continuous, equivalent, full-account-day evidence can own observations."""

import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch

import psycopg

from app.ads import (
    asset_binding as binding,
)
from app.ads import (
    asset_binding_repository as repo,
)
from app.ads import (
    external_repository as external,
)
from app.core import db
from app.tests.test_ads_asset_binding import Fixture


class VersionMetricsTest(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(self)
        self.p = self.f.placement()

    def observation(self, day):
        f = self.f
        row = external.upsert_observation(
            f.conn,
            f.org,
            f.brand,
            f.campaign,
            {
                "entity_id": f.leaf["id"],
                "day": day,
                "metric_scope": "unit",
                "attribution_key": "7d_click",
                "currency": "TWD",
                "spend": 5,
                "source": "fake",
            },
        )
        f.conn.commit()
        return row

    def metric(self, start=date(2026, 1, 1), end=date(2026, 1, 5)):
        f = self.f
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 6, tzinfo=UTC)):
            return binding.metrics(
                f.conn, f.org, f.brand, f.campaign, self.p["id"], 1, start=start, end=end
            )

    def proof(self):
        f = self.f
        f.reader.prove = True
        f.reader.intervals = [
            {
                "start": "2025-12-31T00:00:00+08:00",
                "end": "2026-01-06T00:00:00+08:00",
                "coverage": "continuous",
                "basis": "fake source continuous history assertion",
                "creative_hash": repo.creative_hash(f.leaf["creative"]),
            }
        ]
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 1, 0, tzinfo=UTC)):
            return f.verify(self.p)

    def test_explicit_evidence_allows_only_full_days_after_first_verification(self):
        self.proof()
        self.observation(date(2026, 1, 1))
        self.observation(date(2026, 1, 2))
        out = self.metric()
        self.assertEqual([r["day"] for r in out["attributed_observations"]], [date(2026, 1, 2)])
        self.assertIsNone(out["totals"])
        self.assertEqual(len(out["observations"]), 2)

    def test_two_snapshots_user_check_never_establish_media_or_interval(self):
        f = self.f
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 1, tzinfo=UTC)):
            f.verify(self.p, user_verified=True)
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 5, tzinfo=UTC)):
            f.verify(self.p)
        self.observation(date(2026, 1, 2))
        self.assertEqual(self.metric()["attributed_observations"], [])
        self.assertEqual(len(self.metric()["observations"]), 1)

    def test_current_partial_change_day_unknown_timezone_and_dynamic_are_excluded(self):
        f = self.f
        record = self.proof()
        self.observation(date(2026, 1, 2))
        self.observation(date(2026, 1, 6))
        out = self.metric(end=date(2026, 1, 6))
        self.assertEqual(len(out["attributed_observations"]), 1)
        for updates in [
            "timezone_name=NULL",
            'creative_snapshot=\'{"kind":"dynamic"}\'::jsonb',
            "valid_to='2026-01-02T12:00:00+08:00'",
        ]:
            f.conn.execute(
                "UPDATE ads_asset_binding SET " + updates + " WHERE id=%s", (record["id"],)
            )
            f.conn.commit()
            self.assertEqual(self.metric()["attributed_observations"], [])
            f.conn.execute(
                "UPDATE ads_asset_binding SET timezone_name='Asia/Taipei',"
                "creative_snapshot=%s,valid_to=NULL WHERE id=%s",
                (db.jsonb({"kind": "image"}), record["id"]),
            )
            f.conn.commit()

    def test_refresh_missing_evidence_retains_prior_history(self):
        f = self.f
        first = self.proof()
        f.reader.prove = False
        f.reader.intervals = []
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 5, tzinfo=UTC)):
            again = f.verify(self.p)
        self.assertEqual(again["media_equivalence"], first["media_equivalence"])
        self.assertEqual(again["continuous_intervals"], first["continuous_intervals"])
        self.assertEqual(again["evidence_level"], "media_verified")
        self.observation(date(2026, 1, 2))
        self.assertEqual(len(self.metric()["attributed_observations"]), 1)

    def test_observation_claim_cannot_reference_other_brand(self):
        f = self.f
        record = self.proof()
        other = Fixture(self)
        observation = external.upsert_observation(
            other.conn,
            other.org,
            other.brand,
            other.campaign,
            {
                "entity_id": other.leaf["id"],
                "day": date(2026, 1, 2),
                "metric_scope": "unit",
                "attribution_key": "x",
                "source": "fake",
            },
        )
        f.conn.commit()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            f.conn.execute(
                "INSERT INTO ads_asset_observation_claim(observation_id,org_id,brand_id,"
                "campaign_id,binding_id) VALUES(%s,%s,%s,%s,%s)",
                (observation["id"], f.org, f.brand, f.campaign, record["id"]),
            )
        f.conn.rollback()

    def test_claim_is_not_reassigned_to_second_version(self):
        f = self.f
        record = self.proof()
        observation = self.observation(date(2026, 1, 2))
        self.assertEqual(len(self.metric()["attributed_observations"]), 1)
        f.conn.commit()
        from app.ads import user_assets_repository as assets

        newer = assets.revise(
            f.conn, f.org, f.brand, f.campaign, self.p["id"], 1, {"purpose": "new"}, "human"
        )
        f.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE "
            "id=%s AND revision=%s",
            (newer["id"], newer["revision"]),
        )
        f.conn.commit()
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 4, tzinfo=UTC)):
            f.verify(newer)
        with patch.object(binding.db, "now_utc", return_value=datetime(2026, 1, 6, tzinfo=UTC)):
            out = binding.metrics(
                f.conn,
                f.org,
                f.brand,
                f.campaign,
                newer["id"],
                2,
                start=date(2026, 1, 1),
                end=date(2026, 1, 5),
            )
        self.assertEqual(out["attributed_observations"], [])
        owner = f.conn.execute(
            "SELECT binding_id FROM ads_asset_observation_claim WHERE observation_id=%s",
            (observation["id"],),
        ).fetchone()
        self.assertEqual(owner["binding_id"], record["id"])
