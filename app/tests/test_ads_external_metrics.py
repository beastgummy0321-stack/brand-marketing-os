"""Provider metrics preserve missing/zero/value and never sum competing action synonyms."""

import unittest
from unittest.mock import patch

from app.ads.adapters.meta_read import _entity, creative_summary, observation
from app.meta import graph


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

    def test_sales_objective_matches_purchase_and_leaves_existing_fields_unchanged(self):
        item = {
            "account_id": "1",
            "campaign_id": "2",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
            "spend": "50",
            "impressions": "1000",
            "clicks": "10",
            "actions": [{"action_type": "omni_purchase", "value": "4"}],
            "action_values": [{"action_type": "omni_purchase", "value": "120"}],
        }
        account = {"account_id": "1", "currency": "USD"}
        baseline = observation(item, "campaign", account)
        for objective in ("OUTCOME_SALES", "CONVERSIONS", "PRODUCT_CATALOG_SALES"):
            sales = observation(item, "campaign", account, objective)
            for key in baseline:
                self.assertEqual(sales[key], baseline[key], key)
            self.assertEqual(sales["result_kind"], "purchase")
            self.assertEqual(sales["result_count"], 4)
        self.assertNotIn("result_kind", baseline)

    def test_unmapped_objective_never_falls_back_to_purchase(self):
        item = {
            "account_id": "1",
            "campaign_id": "2",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
            "actions": [{"action_type": "omni_purchase", "value": "9"}],
        }
        for objective in ("OUTCOME_AWARENESS", "BRAND_AWARENESS", "some_future_objective", None):
            row = observation(item, "campaign", {"account_id": "1"}, objective)
            self.assertIsNone(row["result_kind"], objective)
            self.assertIsNone(row["result_count"], objective)
            self.assertIsNone(row["result_action"], objective)
            self.assertIsNone(row["result_attribution"], objective)
            self.assertEqual(row["purchases"], 9)

    def test_engagement_objective_counts_its_own_action_not_incidental_purchase(self):
        item = {
            "account_id": "1",
            "campaign_id": "2",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
            "spend": "20",
            "actions": [
                {"action_type": "post_engagement", "value": "45"},
                {"action_type": "omni_purchase", "value": "1"},
            ],
            "action_values": [{"action_type": "omni_purchase", "value": "30"}],
        }
        row = observation(item, "campaign", {"account_id": "1"}, "OUTCOME_ENGAGEMENT")
        self.assertEqual(row["result_kind"], "engagement")
        self.assertEqual(row["result_count"], 45)
        self.assertEqual(row["result_action"], "post_engagement")
        self.assertEqual(row["result_attribution"], "7d_click+1d_view")
        # The incidental purchase is still a platform fact, just never this campaign's result.
        self.assertEqual(row["purchases"], 1)
        self.assertEqual(row["revenue"], 30)

    def test_known_objective_without_that_days_action_is_unknown_not_zero(self):
        item = {
            "account_id": "1",
            "campaign_id": "2",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
        }
        row = observation(item, "campaign", {"account_id": "1"}, "OUTCOME_LEADS")
        self.assertEqual(row["result_kind"], "lead")
        self.assertIsNone(row["result_count"])
        self.assertIsNone(row["result_action"])
        self.assertIsNone(row["result_attribution"])

    def test_reader_looks_up_synced_campaign_objective_for_every_level(self):
        from app.ads import external_repository as repo
        from app.ads.adapters.meta_read import MetaReader
        from app.core import db
        from app.tests.test_ads_external_sync import setup_brand

        conn = db.current()
        org, brand = setup_brand(conn)
        campaign = repo.create_imported_campaign(conn, org, brand, name="互動活動")
        repo.upsert_entity(
            conn,
            org,
            brand,
            campaign["id"],
            {
                "platform": "meta",
                "source_account": "1",
                "native_kind": "campaign",
                "native_id": "9",
                "objective": "OUTCOME_ENGAGEMENT",
            },
        )
        conn.commit()
        account = {"account_id": "1", "currency": "USD"}
        raw = {
            "account_id": "1",
            "campaign_id": "9",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
            "spend": "20",
            "actions": [
                {"action_type": "post_engagement", "value": "45"},
                {"action_type": "omni_purchase", "value": "1"},
            ],
            "action_values": [{"action_type": "omni_purchase", "value": "30"}],
        }
        reader = MetaReader()
        with patch.object(reader, "_page", return_value={"data": [raw], "cursor": None}):
            page = reader.read_observations(
                conn, org, brand, account, native_id="9", start="2026-01-01", end="2026-01-01"
            )
        row = page.items[0]
        self.assertEqual(row["result_kind"], "engagement")
        self.assertEqual(row["result_count"], 45)
        self.assertEqual(row["result_action"], "post_engagement")
        self.assertEqual(row["result_attribution"], "7d_click+1d_view")
        self.assertEqual(row["purchases"], 1)

    def test_reader_returns_unknown_result_when_campaign_not_yet_synced(self):
        from app.ads.adapters.meta_read import MetaReader
        from app.core import db
        from app.tests.test_ads_external_sync import setup_brand

        conn = db.current()
        org, brand = setup_brand(conn)
        account = {"account_id": "1", "currency": "USD"}
        raw = {
            "account_id": "1",
            "campaign_id": "unsynced",
            "date_start": "2026-01-01",
            "date_stop": "2026-01-01",
            "spend": "20",
            "actions": [{"action_type": "omni_purchase", "value": "1"}],
        }
        reader = MetaReader()
        with patch.object(reader, "_page", return_value={"data": [raw], "cursor": None}):
            page = reader.read_observations(
                conn,
                org,
                brand,
                account,
                native_id="unsynced",
                start="2026-01-01",
                end="2026-01-01",
            )
        row = page.items[0]
        self.assertIsNone(row["result_kind"])
        self.assertIsNone(row["result_count"])
        self.assertEqual(row["purchases"], 1)

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

    def test_native_budget_resolves_zero_decimal_currency(self):
        # TWD offset 1 (docs/architecture/ads.md §6.12): 1000 minor units == NT$1000, no rounding.
        item = _entity(
            {"id": "2", "account_id": "1", "lifetime_budget": "1000"},
            "campaign",
            {"account_id": "1", "currency": "TWD"},
        )
        self.assertEqual(item["budget_type"], "lifetime")
        self.assertEqual(item["budget_amount"], 1000.0)
        self.assertEqual(item["budget_raw"]["values"]["lifetime_budget"], "1000")
        self.assertEqual(item["budget_raw"]["conversion"], "offset_table:1")
        self.assertEqual(item["availability"]["budget_amount"], "available")

    def test_native_budget_resolves_two_decimal_currency(self):
        # USD offset 100: 150055 minor units == $1500.55, exact Decimal division, no float loss.
        item = _entity(
            {"id": "3", "account_id": "1", "campaign_id": "2", "daily_budget": "150055"},
            "adset",
            {"account_id": "1", "currency": "USD"},
        )
        self.assertEqual(item["budget_type"], "daily")
        self.assertEqual(item["budget_amount"], 1500.55)
        self.assertEqual(item["budget_raw"]["conversion"], "offset_table:100")
        self.assertEqual(item["availability"]["budget_amount"], "available")

    def test_native_budget_currency_absent_from_offset_table_stays_unknown(self):
        # BTC (or any currency not in Meta's documented table) never defaults to 1 or 100.
        item = _entity(
            {"id": "4", "account_id": "1", "daily_budget": "1000"},
            "campaign",
            {"account_id": "1", "currency": "BTC"},
        )
        self.assertIsNone(item["budget_amount"])
        self.assertEqual(item["budget_raw"]["conversion"], "currency_not_in_offset_table")
        self.assertEqual(item["availability"]["budget_amount"], "unknown")

    def test_native_budget_missing_currency_stays_unknown(self):
        item = _entity(
            {"id": "5", "account_id": "1", "daily_budget": "1000"},
            "campaign",
            {"account_id": "1", "currency": None},
        )
        self.assertIsNone(item["budget_amount"])
        self.assertEqual(item["budget_raw"]["conversion"], "currency_absent")
        self.assertEqual(item["availability"]["budget_amount"], "unknown")

    def test_native_budget_absent_value_stays_unknown(self):
        item = _entity(
            {"id": "6", "account_id": "1"},
            "campaign",
            {"account_id": "1", "currency": "TWD"},
        )
        self.assertEqual(item["budget_type"], "unknown")
        self.assertIsNone(item["budget_amount"])
        self.assertEqual(item["budget_raw"]["conversion"], "no_budget_value")
        self.assertEqual(item["availability"]["budget_amount"], "unknown")

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

    def test_reader_uses_live_facade_with_current_binding(self):
        from app.ads.adapters.meta_read import MetaReader
        from app.core import db
        from app.meta import repository as source

        conn = db.current()
        account = {"account_id": "1", "currency": "USD"}
        with (
            patch.object(source, "external_bound_accounts", return_value=[account]),
            patch.object(source, "get_token", return_value="secret"),
            patch.object(
                graph,
                "fetch_page",
                return_value={
                    "data": [
                        {
                            "id": "2",
                            "account_id": "1",
                            "name": "paused",
                            "effective_status": "PAUSED",
                        }
                    ]
                },
            ) as fetch,
        ):
            page = MetaReader().list_existing(conn, "org", "brand", account)
            self.assertEqual(page.items[0]["native_status"], "PAUSED")
            self.assertEqual(fetch.call_count, 1)
        with (
            patch.object(source, "external_bound_accounts", return_value=[]),
            patch.object(graph, "fetch_page") as fetch,
        ):
            with self.assertRaises(ValueError):
                MetaReader().list_existing(conn, "org", "brand", account)
            fetch.assert_not_called()

    def test_permission_failure_is_safe_and_distinct(self):
        from app.ads.adapters.external import SourceReadError
        from app.ads.adapters.meta_read import MetaReader
        from app.core import db
        from app.meta import repository as source

        account = {"account_id": "1"}
        with (
            patch.object(source, "external_bound_accounts", return_value=[account]),
            patch.object(source, "get_token", return_value="secret"),
            patch.object(
                graph, "fetch_page", return_value={"error": {"code": 200, "message": "secret-url"}}
            ),
        ):
            with self.assertRaises(SourceReadError) as caught:
                MetaReader().list_existing(db.current(), "org", "brand", account)
        self.assertEqual(caught.exception.code, "permission_denied")
        self.assertNotIn("secret", str(caught.exception))
