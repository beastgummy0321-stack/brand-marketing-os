"""Native source data keeps scope, nulls, currencies and arbitrary parent chains."""

import unittest
from contextlib import contextmanager
from datetime import date

import psycopg
from pydantic import ValidationError

from app.ads import external_repository as external
from app.ads.external_models import ExternalEntity, ExternalObservation
from app.brand_intelligence import repository as brands
from app.core import db


@contextmanager
def transaction(conn):
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class ExternalSchemaTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="原生測試", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="原生"
        )["id"]
        self.conn.commit()

    def entity(self, native_id="root", **extra):
        return external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "third-platform",
                "source_account": "account",
                "native_kind": "portfolio",
                "native_id": native_id,
                **extra,
            },
        )

    def test_nullable_campaign_and_lifetime_budget_arbitrary_tree(self):
        root = self.entity(
            budget_type="lifetime",
            budget_amount=12500,
            currency="TWD",
            budget_source="platform",
            native_status="PAUSED",
        )
        child = self.entity(
            "child",
            native_kind="line-item",
            parent_native_kind="portfolio",
            parent_native_id="root",
        )
        self.entity(
            "leaf",
            native_kind="creative-unit",
            parent_native_kind="line-item",
            parent_native_id="child",
        )
        self.conn.commit()
        self.assertEqual(root["budget_amount"], 12500)
        self.assertIsNone(child["budget_amount"])
        self.assertEqual(
            len(external.external_view(self.conn, self.org, self.brand, self.campaign)["entities"]),
            3,
        )
        # A smaller successful page is an upsert, never deletion evidence.
        self.entity(budget_type="lifetime", budget_amount=12500, currency="TWD")
        self.assertEqual(
            len(external.external_view(self.conn, self.org, self.brand, self.campaign)["entities"]),
            3,
        )

    def test_observation_dimensions_and_unknown_are_preserved(self):
        entity = self.entity()
        for currency in ("TWD", "USD"):
            for attribution in ("7d_click", "1d_view"):
                external.upsert_observation(
                    self.conn,
                    self.org,
                    self.brand,
                    self.campaign,
                    {
                        "entity_id": entity["id"],
                        "day": date(2026, 1, 1),
                        "metric_scope": "portfolio",
                        "attribution_key": attribution,
                        "currency": currency,
                        "source": "platform",
                        "spend": 5,
                    },
                )
        rows = external.external_view(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        )["observations"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(
            all(
                r["purchases"] is None and r["availability"]["purchases"] == "unknown" for r in rows
            )
        )
        self.assertTrue(all(r["spend"] == 5 for r in rows))

    def test_cross_account_and_brand_parent_fk_rejected(self):
        self.entity()
        self.conn.commit()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with transaction(self.conn):
                self.entity(
                    "bad",
                    source_account="other",
                    parent_native_kind="portfolio",
                    parent_native_id="root",
                )
        other = brands.create_brand(
            self.conn, org_id=self.org, name="另一品牌", actor="test", client_name=None
        )["id"]
        self.conn.commit()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO ads_external_entity(id,org_id,brand_id,campaign_id,platform,"
                    "source_account,native_kind,native_id) VALUES (%s,%s,%s,%s,'x','a','k','n')",
                    (db.new_id("aex"), self.org, other, self.campaign),
                )

    def test_cross_brand_observation_fk_rejected(self):
        entity = self.entity()
        other = brands.create_brand(
            self.conn, org_id=self.org, name="另一品牌", actor="test", client_name=None
        )["id"]
        campaign = external.create_imported_campaign(self.conn, self.org, other, name="其他")
        self.conn.commit()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with transaction(self.conn):
                external.upsert_observation(
                    self.conn,
                    self.org,
                    other,
                    campaign["id"],
                    {
                        "entity_id": entity["id"],
                        "day": "2026-01-01",
                        "metric_scope": "root",
                        "attribution_key": "unknown",
                        "source": "platform",
                    },
                )

    def test_cycle_and_remount_rejected(self):
        self.entity()
        self.entity("child", parent_native_kind="portfolio", parent_native_id="root")
        self.conn.commit()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction(self.conn):
                self.entity(parent_native_kind="portfolio", parent_native_id="child")
        other = external.create_imported_campaign(self.conn, self.org, self.brand, name="other")
        with self.assertRaisesRegex(ValueError, "already_imported"):
            external.upsert_entity(
                self.conn,
                self.org,
                self.brand,
                other["id"],
                {
                    "platform": "third-platform",
                    "source_account": "account",
                    "native_kind": "portfolio",
                    "native_id": "root",
                },
            )

    def test_sync_failure_retains_success_and_coverage(self):
        external.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="observations",
            state={"last_success_at": "2026-01-01", "coverage": ["2025-12-01", "2026-01-01"]},
        )
        external.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="observations",
            state={
                "status": "error",
                "error": "permission",
                "last_attempt_at": "2026-01-02",
                "last_success_at": None,
                "coverage": None,
            },
        )
        view = external.external_view(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(view["sync"]["observations"]["last_success_at"], "2026-01-01")
        self.assertEqual(view["coverage"]["observations"], ["2025-12-01", "2026-01-01"])

    def test_non_finite_values_and_false_availability_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValidationError):
                ExternalEntity(
                    platform="x",
                    source_account="a",
                    native_kind="k",
                    native_id="n",
                    budget_amount=value,
                )
            with self.assertRaises(ValidationError):
                ExternalObservation(
                    entity_id="e",
                    day="2026-01-01",
                    metric_scope="k",
                    attribution_key="x",
                    source="x",
                    spend=value,
                )
        with self.assertRaises(ValidationError):
            ExternalObservation(
                entity_id="e",
                day="2026-01-01",
                metric_scope="k",
                attribution_key="x",
                source="x",
                availability={"spend": "available"},
            )

    def test_structure_patch_preserves_creative_success(self):
        self.entity(creative={"body": "原本文案"}, last_success_at="2026-01-01T00:00:00Z")
        updated = self.entity(name="新名稱", sync_status="error", sync_error="partial")
        self.assertEqual(updated["creative"], {"body": "原本文案"})
        self.assertEqual(updated["last_success_at"].date(), date(2026, 1, 1))

    def test_successful_retry_clears_previous_error_code(self):
        external.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="structure",
            state={"status": "error", "error": "permission", "error_code": "permission_denied"},
        )
        external.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="structure",
            state={"status": "success", "error": None},
        )
        state = external.external_view(self.conn, self.org, self.brand, self.campaign)["sync"][
            "structure"
        ]
        self.assertIsNone(state["error"])
        self.assertIsNone(state["error_code"])


class CampaignTargetSchemaTest(unittest.TestCase):
    """F16-I04 (`supabase/migrations/20260920000005_ads_campaign_target.sql` +
    `20260920000006_ads_campaign_target_columns.sql`, the repair round): `result_kind` and
    `target_revision` from `..._0005`; the own-columns `target_cost`/`target_basis` from
    `..._0006` (only `own` may carry a `target_cost`); `success_metric` restored to
    cpa/roas/purchases -- `cost_per_result` is rejected again, and legacy rows keep their
    free-text `success_basis` meaning untouched."""

    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="目標成本 schema", actor="test", client_name=None
        )["id"]
        self.conn.commit()

    def test_result_kind_and_default_target_revision(self):
        campaign_id = db.new_id("adc")
        self.conn.execute(
            "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,result_kind) "
            "VALUES (%s,%s,%s,'target 測試','imported','purchase')",
            (campaign_id, self.org, self.brand),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT result_kind,target_revision FROM ads_campaign WHERE id=%s",
            (campaign_id,),
        ).fetchone()
        self.assertEqual(row["result_kind"], "purchase")
        self.assertEqual(row["target_revision"], 0)

    def test_success_metric_rejects_cost_per_result_again(self):
        """`..._0006` undoes `..._0005`'s widening (architect ruling: the target cost gets its
        own columns, nothing writes `success_metric='cost_per_result'` again)."""
        campaign_id = db.new_id("adc")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,success_metric) "
                    "VALUES (%s,%s,%s,'target 測試','imported','cost_per_result')",
                    (campaign_id, self.org, self.brand),
                )

    def test_target_cost_rejected_for_a_computed_basis(self):
        campaign_id = db.new_id("adc")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,target_basis,"
                    "target_cost) VALUES (%s,%s,%s,'target 測試','imported','break_even',100)",
                    (campaign_id, self.org, self.brand),
                )

    def test_own_basis_requires_a_target_cost(self):
        campaign_id = db.new_id("adc")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,target_basis) "
                    "VALUES (%s,%s,%s,'target 測試','imported','own')",
                    (campaign_id, self.org, self.brand),
                )

    def test_own_basis_with_target_cost_is_accepted(self):
        campaign_id = db.new_id("adc")
        self.conn.execute(
            "INSERT INTO ads_campaign(id,org_id,brand_id,name,origin,target_basis,target_cost) "
            "VALUES (%s,%s,%s,'target 測試','imported','own',250)",
            (campaign_id, self.org, self.brand),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT target_basis,target_cost FROM ads_campaign WHERE id=%s", (campaign_id,),
        ).fetchone()
        self.assertEqual(row["target_basis"], "own")
        self.assertEqual(float(row["target_cost"]), 250.0)

    def test_legacy_success_metric_rows_keep_free_text_basis_untouched(self):
        campaign_id = db.new_id("adc")
        self.conn.execute(
            "INSERT INTO ads_campaign(id,org_id,brand_id,name,goal_text,objective,origin,"
            "success_metric,success_basis,success_target) VALUES "
            "(%s,%s,%s,'legacy','為了測試','購買','internal','cpa','一句話說明',100)",
            (campaign_id, self.org, self.brand),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT success_basis,result_kind FROM ads_campaign WHERE id=%s", (campaign_id,),
        ).fetchone()
        self.assertEqual(row["success_basis"], "一句話說明")
        self.assertIsNone(row["result_kind"])
