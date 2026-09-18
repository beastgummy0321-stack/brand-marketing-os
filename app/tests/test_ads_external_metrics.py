"""Provider metrics preserve missing/zero/value and never sum competing action synonyms."""

import unittest

from app.ads.adapters.meta_read import _entity, creative_summary, observation


class MetricsTest(unittest.TestCase):
    def test_missing_zero_and_value(self):
        base = {
            "account_id": "1",
            "campaign_id": "2",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
        }
        for value in (None, "0", "17"):
            row = observation(
                base | ({"spend": value} if value is not None else {}),
                "campaign",
                {"account_id": "1", "currency": "USD"},
            )
            self.assertEqual(row["spend"], None if value is None else float(value))
            self.assertIsNone(row["purchases"])
        row = observation(
            base
            | {
                "actions": [
                    {"action_type": "omni_purchase", "value": "3"},
                    {"action_type": "purchase", "value": "5"},
                ]
            },
            "campaign",
            {"account_id": "1"},
        )
        self.assertEqual(row["purchases"], 3)
        self.assertIsNone(row["revenue"])

    def test_creative_types_do_not_fabricate_video_original(self):
        for value, kind in (
            ({"image_hash": "hash"}, "image"),
            ({"video_id": "v", "thumbnail_url": "https://image"}, "video"),
            (
                {"object_story_spec": {"link_data": {"child_attachments": [{"image_hash": "a"}]}}},
                "carousel",
            ),
            ({"asset_feed_spec": {"images": [{"hash": "a"}]}}, "dynamic"),
        ):
            result = creative_summary(value)
            self.assertEqual(result["kind"], kind)
            self.assertIsNone(result["video_original"])
        self.assertEqual(
            creative_summary({"asset_feed_spec": {}, "image_hash": "a"})["kind"], "image"
        )

    def test_native_budget_keeps_unknown_denominator(self):
        item = _entity(
            {"id": "2", "account_id": "1", "lifetime_budget": "1000"},
            "campaign",
            {"account_id": "1", "currency": "JPY"},
        )
        self.assertEqual(item["budget_type"], "lifetime")
        self.assertIsNone(item["budget_amount"])
        self.assertEqual(item["budget_raw"]["values"]["lifetime_budget"], "1000")

    def test_external_view_pages_without_mixing_dimensions(self):
        from datetime import date

        from app.ads import external_repository as repo
        from app.core import db
        from app.tests.test_ads_external_sync import setup_brand

        conn = db.current()
        org, brand = setup_brand(conn)
        campaign = repo.create_imported_campaign(conn, org, brand, name="分頁")
        entity = repo.upsert_entity(
            conn,
            org,
            brand,
            campaign["id"],
            {"platform": "other", "source_account": "a", "native_kind": "root", "native_id": "1"},
        )
        for i in range(105):
            repo.upsert_observation(
                conn,
                org,
                brand,
                campaign["id"],
                {
                    "entity_id": entity["id"],
                    "day": date.today(),
                    "metric_scope": "root",
                    "attribution_key": str(i),
                    "source": "other",
                    "currency": "TWD" if i % 2 else "USD",
                    "spend": i,
                },
            )
        first = repo.external_view(conn, org, brand, campaign["id"])
        second = repo.external_view(
            conn, org, brand, campaign["id"], observation_after=first["next_observation_cursor"]
        )
        self.assertEqual(len(first["observations"]), 100)
        self.assertEqual(len(second["observations"]), 5)
        ids = [r["id"] for r in first["observations"] + second["observations"]]
        self.assertEqual(len(set(ids)), 105)
        self.assertIsNone(second["next_observation_cursor"])
        self.assertNotIn("totals", first)
