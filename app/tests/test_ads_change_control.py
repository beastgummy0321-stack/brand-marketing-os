"""Approval fingerprints, scoped retries and readback evidence against a platform double."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import asset_binding_repository as bindings
from app.ads import change_control as service
from app.ads import change_control_data as data
from app.ads import change_control_verify as verification
from app.ads import external_repository as external
from app.ads import external_sync
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db


class ChangeControlTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="變更測試", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="持續活動"
        )["id"]
        self.root = self.entity("1", "campaign")
        self.group = self.entity(
            "2",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="1",
            budget_type="daily",
            budget_amount=1000,
            currency="TWD",
        )
        self.ad = self.entity(
            "3",
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative={
                "kind": "image",
                "fields": {"body": "原文案", "title": "原標題", "image_hash": "image-one"},
            },
        )
        self.conn.commit()
        self.month = db.now_utc().strftime("%Y-%m")

    def entity(self, native_id, native_kind, **extra):
        return external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fake",
                "source_account": "account",
                "native_id": native_id,
                "native_kind": native_kind,
                "native_status": "ACTIVE",
                **extra,
            },
        )

    def create(self, **overrides):
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.month,
            "title": "只改原 B 文案",
            "items": [
                {
                    "kind": "copy",
                    "target_id": self.ad["id"],
                    "after": {"body": "新文案"},
                    "reason": "驗證新訴求，未聲稱因果",
                }
            ],
        }
        return service.create(
            self.conn, self.org, self.brand, self.campaign, {**payload, **overrides}, "test"
        )

    def approve(self, created):
        return service.approve(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            created["id"],
            created["content_hash"],
            "test",
        )

    def count(self, table):
        return self.conn.execute(
            f"SELECT count(*) AS n FROM {table} WHERE brand_id=%s", (self.brand,)
        ).fetchone()["n"]

    def test_same_operation_replays_same_list_but_changed_request_conflicts(self):
        first = self.create(operation_id="stable-key")
        again = self.create(operation_id="stable-key")
        self.assertEqual(first["id"], again["id"])
        with self.assertRaisesRegex(ValueError, "同一次操作"):
            self.create(operation_id="stable-key", title="不同清單")
        self.assertEqual(self.count("ads_change_set"), 1)

    def test_approve_lost_response_replay_is_atomic_and_not_a_platform_result(self):
        first = self.create()
        approved = self.approve(first)
        again = self.approve(first)
        self.assertEqual(approved["approval_id"], again["approval_id"])
        self.assertEqual(self.count("approval"), 1)
        self.assertEqual(self.count("ads_action"), 1)
        self.assertEqual(again["items"][0]["verification_state"], "pending")
        self.assertIsNone(again["items"][0]["verified_at"])
        row = self.conn.execute(
            "SELECT content_hash FROM approval WHERE id=%s", (approved["approval_id"],)
        ).fetchone()
        self.assertEqual(row["content_hash"], first["content_hash"])
        self.assertNotEqual(row["content_hash"], self.campaign)

    def test_action_failure_rolls_back_approval_audit_and_set_state(self):
        first = self.create()
        audits = self.count("audit_log")
        with patch.object(service, "_insert_actions", side_effect=ValueError("injected failure")):
            with self.assertRaises(ValueError):
                self.approve(first)
        self.assertEqual(self.count("approval"), 0)
        self.assertEqual(self.count("ads_action"), 0)
        self.assertEqual(self.count("audit_log"), audits)
        self.assertEqual(
            data.get(self.conn, self.org, self.brand, self.campaign, first["id"])["status"], "draft"
        )

    def test_wrong_hash_and_relevant_external_copy_change_reject_approval(self):
        first = self.create()
        with self.assertRaises(ValueError):
            service.approve(
                self.conn, self.org, self.brand, self.campaign, first["id"], "wrong", "test"
            )
        self.entity(
            "3",
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative={"fields": {"body": "外部已修改"}},
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "設定已改變"):
            self.approve(first)
        self.assertEqual(self.count("approval"), 0)

    def test_normal_sync_and_unrelated_budget_do_not_invalidate_copy(self):
        first = self.create()
        self.entity(
            "3",
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative=self.ad["creative"],
            last_success_at=db.now_utc(),
        )
        self.entity(
            "2",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="1",
            budget_type="daily",
            budget_amount=900,
            currency="TWD",
        )
        self.conn.commit()
        self.assertEqual(self.approve(first)["status"], "approved")

    def test_scoped_target_and_list_cannot_cross_brand_or_campaign(self):
        first = self.create()
        other = brands.create_brand(
            self.conn, org_id=self.org, name="別品牌", actor="test", client_name=None
        )["id"]
        other_campaign = external.create_imported_campaign(
            self.conn, self.org, other, name="另一活動"
        )["id"]
        self.conn.commit()
        with self.assertRaises(ValueError):
            data.get(self.conn, self.org, other, other_campaign, first["id"])
        with self.assertRaises(ValueError):
            service.create(
                self.conn,
                self.org,
                other,
                other_campaign,
                {
                    "operation_id": "same-key",
                    "title": "跨品牌",
                    "month": self.month,
                    "items": [
                        {
                            "kind": "copy",
                            "target_id": self.ad["id"],
                            "after": {"body": "wrong"},
                            "reason": "wrong",
                        }
                    ],
                },
                "test",
            )

    def test_client_cannot_invent_before_and_duplicate_items_are_rejected(self):
        item = {
            "kind": "copy",
            "target_id": self.ad["id"],
            "after": {"body": "新文案"},
            "reason": "test",
        }
        with self.assertRaises(ValueError):
            self.create(items=[{**item, "before": {"body": "invented"}}])
        with self.assertRaises(ValueError):
            self.create(items=[item, item])

    def test_deferred_requires_revisit_and_revision_keeps_original(self):
        first = self.create()
        with self.assertRaises(ValueError):
            service.decide(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                first["id"],
                "deferred",
                "需要更多資料",
                None,
                "test",
            )
        service.decide(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            first["id"],
            "deferred",
            "需要更多資料",
            (db.now_utc() + timedelta(days=1)).isoformat(),
            "test",
        )
        revised = self.create(supersedes_id=first["id"])
        original = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertEqual(original["status"], "superseded")
        self.assertEqual(original["content_hash"], first["content_hash"])
        self.assertEqual(revised["plan_json"]["supersedes_id"], first["id"])

    def _readback(self, current, body="新文案", fail=False, wrong_account=False):
        ad = copy.deepcopy(self.ad)
        ad["creative"]["fields"]["body"] = body
        if wrong_account:
            ad["source_account"] = "another"
        proof = {"entity": ad, "parents": [self.group, self.root]}

        class Reader:
            def verify_native(self, *args, **kwargs):
                if fail:
                    raise ValueError("private provider failure")
                return proof

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            return verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                current["id"],
                current["items"][0]["id"],
                "test",
            )

    def test_partial_completion_separate_report_observation_and_setting_match(self):
        first = self.create(
            items=[
                {
                    "kind": "copy",
                    "target_id": self.ad["id"],
                    "after": {"body": "新文案"},
                    "reason": "文案測試",
                },
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": 800},
                    "reason": "降低風險",
                },
            ]
        )
        approved = self.approve(first)
        reported = service.report(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            approved["id"],
            approved["items"][0]["id"],
            "test",
        )
        self.assertEqual(reported["items"][0]["verification_state"], "reported")
        self.assertIsNone(reported["items"][0]["first_observed_at"])
        checked = self._readback(approved)
        self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
        self.assertFalse(checked["items"][0]["evidence_json"]["delivery_confirmed"])
        self.assertEqual(checked["items"][0]["evidence_json"]["media_equivalence"], "unknown")
        self.assertEqual(checked["items"][1]["verification_state"], "pending")
        self.assertEqual(checked["status"], "approved")

    def test_unknown_and_external_deviation_are_not_success_and_can_retry(self):
        approved = self.approve(self.create())
        for kwargs in ({"fail": True}, {"wrong_account": True}):
            self.assertEqual(
                self._readback(approved, **kwargs)["items"][0]["verification_state"], "unknown"
            )
        self.assertEqual(
            self._readback(approved, body="外部版本")["items"][0]["verification_state"], "deviated"
        )
        self.assertEqual(self._readback(approved)["items"][0]["verification_state"], "confirmed")

    def test_same_target_pending_action_cannot_be_approved_twice(self):
        self.approve(self.create())
        with self.assertRaisesRegex(ValueError, "已有相同操作"):
            self.approve(self.create())

    def test_readback_refreshes_workspace_and_revision_baseline_but_preserves_approval(self):
        asset_id = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,'key','original.png',"
            "'image/png',1,'ready')",
            (asset_id, self.org, self.brand, asset_id),
        )
        placement = assets.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            asset_id,
            {"body": "原文案"},
            "test",
        )
        binding_id = db.new_id("aab")
        self.conn.execute(
            "INSERT INTO ads_asset_binding(id,org_id,brand_id,campaign_id,placement_id,"
            "placement_revision,entity_id,platform,source_account,native_kind,native_id,"
            "existence_status,creative_snapshot,creative_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,'fake','account','ad','3',"
            "'platform_confirmed',%s,%s)",
            (
                binding_id,
                self.org,
                self.brand,
                self.campaign,
                placement["id"],
                placement["revision"],
                self.ad["id"],
                db.jsonb(self.ad["creative"]),
                bindings.creative_hash(self.ad["creative"]),
            ),
        )
        self.conn.commit()
        original = self.approve(self.create())
        checked = self._readback(original, body="平台 v3 文案")
        self.assertEqual(checked["items"][0]["verification_state"], "deviated")
        workspace = service.workspace(self.conn, self.org, self.brand, self.campaign)
        target = next(t for t in workspace["targets"] if t["id"] == self.ad["id"])
        self.assertEqual(target["creative"]["fields"]["body"], "平台 v3 文案")
        self.assertIsNotNone(target["last_success_at"])
        self.assertEqual(target["native_id"], self.ad["native_id"])
        self.assertEqual(self.count("ads_external_entity"), 3)
        revised = self.create(supersedes_id=original["id"])
        self.assertEqual(revised["items"][0]["before"]["body"], "平台 v3 文案")
        self.assertEqual(revised["items"][0]["creative_snapshot"], target["creative"])
        self.assertEqual(self.approve(revised)["status"], "approved")
        retained = data.get(self.conn, self.org, self.brand, self.campaign, original["id"])
        self.assertEqual(retained["approval_id"], original["approval_id"])
        self.assertEqual(retained["content_hash"], original["content_hash"])
        self.assertEqual(retained["items"][0]["before"]["body"], "原文案")
        self.assertEqual(retained["items"][0]["creative_snapshot"], self.ad["creative"])
        binding = self.conn.execute(
            "SELECT * FROM ads_asset_binding WHERE id=%s",
            (binding_id,),
        ).fetchone()
        self.assertEqual(self.count("ads_asset_binding"), 1)
        self.assertEqual(binding["creative_snapshot"], self.ad["creative"])
        self.assertEqual(binding["native_id"], self.ad["native_id"])
        self.assertIsNotNone(binding["valid_to"])
        self.assertIn("creative", binding["stale_reason"])
        from app.main import app

        summary = TestClient(app).get(f"/api/ads/brands/{self.brand}/change-control-summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual([item["id"] for item in summary.json()["items"]], [revised["id"]])

    def _readback_with_concurrent_sync(self, approved, synced_node, **changes):
        outer = self
        proof_ad = copy.deepcopy(self.ad)
        proof_ad["creative"]["fields"]["body"] = "新文案"

        class Reader:
            def verify_native(self, *args, **kwargs):
                # A separate DB transaction commits while the HTTP response is outstanding.
                with db.connection() as sync_conn:
                    sync_conn.execute("SET LOCAL lock_timeout='2s'")
                    bindings.lock_native(sync_conn, synced_node)
                    external.upsert_entity(
                        sync_conn,
                        outer.org,
                        outer.brand,
                        outer.campaign,
                        {
                            key: synced_node[key]
                            for key in (
                                "platform",
                                "source_account",
                                "native_kind",
                                "native_id",
                                "parent_native_kind",
                                "parent_native_id",
                            )
                        }
                        | changes,
                    )
                    sync_conn.commit()
                return {"entity": proof_ad, "parents": [outer.group, outer.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            return verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )

    def test_later_creative_sync_is_not_overwritten_by_older_http_readback(self):
        approved = self.approve(self.create())
        creative = copy.deepcopy(self.ad["creative"])
        creative["fields"]["body"] = "較新同步 v4"
        checked = self._readback_with_concurrent_sync(approved, self.ad, creative=creative)
        self.assertEqual(checked["items"][0]["verification_state"], "stale")
        self.assertIsNone(checked["items"][0]["verified_at"])
        target = bindings.entity(self.conn, self.org, self.brand, self.campaign, self.ad["id"])
        self.assertEqual(target["creative"], creative)
        revised = self.create(supersedes_id=approved["id"])
        self.assertEqual(revised["items"][0]["before"]["body"], "較新同步 v4")

    def test_later_parent_budget_sync_prevents_entire_old_proof_from_overwriting_snapshot(self):
        approved = self.approve(self.create())
        checked = self._readback_with_concurrent_sync(
            approved,
            self.group,
            budget_amount=2000,
            budget_type="daily",
        )
        self.assertEqual(checked["items"][0]["verification_state"], "unknown")
        self.assertEqual(checked["approval_id"], approved["approval_id"])
        self.assertIn("無需重複核准", checked["items"][0]["evidence_json"]["message"])
        parent = bindings.entity(self.conn, self.org, self.brand, self.campaign, self.group["id"])
        target = bindings.entity(self.conn, self.org, self.brand, self.campaign, self.ad["id"])
        self.assertEqual(parent["budget_amount"], 2000)
        self.assertEqual(target["creative"], self.ad["creative"])

    def test_metadata_only_sync_during_readback_keeps_approval_and_confirms(self):
        approved = self.approve(self.create())
        checked = self._readback_with_concurrent_sync(
            approved, self.ad, last_attempt_at=db.now_utc(), last_success_at=db.now_utc(),
            sync_status="succeeded",
        )
        self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
        self.assertEqual(checked["approval_id"], approved["approval_id"])

    def test_readback_of_unperformed_action_allows_linked_revision_without_deleting_approval(self):
        first = self.approve(self.create())
        self.assertFalse(first["can_revise"])
        with self.assertRaises(ValueError):
            self.create(supersedes_id=first["id"])
        readback = self._readback(first, body="原文案")
        self.assertTrue(readback["can_revise"])
        second = self.create(supersedes_id=first["id"])
        original = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
        self.assertEqual(original["items"][0]["verification_state"], "stale")
        self.assertEqual(original["approval_id"], first["approval_id"])
        with patch.object(external_sync, "account_reader") as reader:
            retained = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                first["id"],
                first["items"][0]["id"],
                "test",
            )
            reader.assert_not_called()
        self.assertEqual(retained["items"][0]["verification_state"], "stale")
        self.assertEqual(retained["items"][0]["evidence_json"]["superseded_by"], second["id"])
        self.assertEqual(self.approve(second)["status"], "approved")

    def test_budget_matching_amount_does_not_override_changed_conditions(self):
        for field, value in (
            ("currency", "USD"),
            ("start_date", "2026-09-20"),
            ("end_date", "2026-09-25"),
            ("budget_type", "lifetime"),
        ):
            with self.subTest(field=field):
                created = self.create(
                    items=[
                        {
                            "kind": "budget",
                            "target_id": self.group["id"],
                            "after": {"daily_amount": 1500},
                            "reason": "test",
                        }
                    ]
                )
                with patch("app.ads.month_budget.preflight", return_value={}):
                    approved = self.approve(created)
                entity = {**self.group, "budget_amount": 1500, field: value}

                class Reader:
                    def verify_native(inner, *args, entity=entity, **kwargs):
                        return {"entity": entity, "parents": [self.root]}

                with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
                    result = verification.check(
                        self.conn,
                        self.org,
                        self.brand,
                        self.campaign,
                        approved["id"],
                        approved["items"][0]["id"],
                        "test",
                    )
                self.assertEqual(result["items"][0]["verification_state"], "stale")
                self.assertIsNone(result["items"][0]["verified_at"])

    def test_missing_budget_conditions_remain_unknown_even_when_amount_matches(self):
        created = self.create(
            items=[
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": 800},
                    "reason": "test",
                }
            ]
        )
        approved = self.approve(created)
        entity = {**self.group, "budget_amount": 800}
        entity.pop("currency")

        class Reader:
            def verify_native(inner, *args, **kwargs):
                return {"entity": entity, "parents": [self.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            result = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )
        self.assertEqual(result["items"][0]["verification_state"], "unknown")
        self.assertIsNone(result["items"][0]["verified_at"])

    def test_unknown_end_date_is_not_evidence_of_unlimited_budget_period(self):
        created = self.create(
            items=[
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": 800},
                    "reason": "test",
                }
            ]
        )
        approved = self.approve(created)
        entity = {**self.group, "budget_amount": 800, "availability": {"end_date": "unknown"}}

        class Reader:
            def verify_native(inner, *args, **kwargs):
                return {"entity": entity, "parents": [self.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            result = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )
        self.assertEqual(result["items"][0]["verification_state"], "unknown")
        self.assertIsNone(result["items"][0]["verified_at"])

    def test_meta_budget_conversion_flows_through_confirmed_readback(self):
        """F16-I02: the real per-currency amount from meta_read._entity, not a synthetic
        number, is what change_control_data.before()/check() compare against `after`."""
        from app.ads.adapters.meta_read import _entity

        raw = {"id": "2", "account_id": "account", "campaign_id": "1", "daily_budget": "1600"}
        resolved = _entity(raw, "adset", {"account_id": "account", "currency": "TWD"})
        self.assertEqual(resolved["budget_amount"], 1600.0)
        # Concrete start/end dates so budget_conditions' availability check is satisfied and the
        # scenario can reach "confirmed" rather than "unknown" for an unrelated missing field.
        self.entity(
            "2",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="1",
            budget_type="daily",
            budget_amount=1000,
            currency="TWD",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        self.conn.commit()
        created = self.create(
            items=[
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": resolved["budget_amount"]},
                    "reason": "核對讀回換算後的真實金額",
                }
            ]
        )
        with patch("app.ads.month_budget.preflight", return_value={}):
            approved = self.approve(created)
        entity = {
            **self.group,
            "budget_amount": resolved["budget_amount"],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }

        class Reader:
            def verify_native(inner, *args, **kwargs):
                return {"entity": entity, "parents": [self.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            result = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )
        self.assertEqual(result["items"][0]["verification_state"], "confirmed")
        self.assertTrue(result["items"][0]["evidence_json"]["setting_matches"])

    def test_meta_budget_conversion_flows_through_confirmed_readback_two_decimal_currency(self):
        """F16-I02: change_control_verify.check() compares read-back money with plain `==`,
        no tolerance. TWD (offset 1) is integer-valued and trivially safe; USD (offset 100)
        is the case that can actually break if both sides don't quantize identically."""
        from app.ads.adapters.meta_read import _entity

        raw = {"id": "2", "account_id": "account", "campaign_id": "1", "daily_budget": "123456"}
        resolved = _entity(raw, "adset", {"account_id": "account", "currency": "USD"})
        self.assertEqual(resolved["budget_amount"], 1234.56)
        self.group = self.entity(
            "2",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="1",
            budget_type="daily",
            budget_amount=1000,
            currency="USD",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        self.conn.commit()
        created = self.create(
            items=[
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": resolved["budget_amount"]},
                    "reason": "核對讀回換算後的真實金額（USD 兩位小數）",
                }
            ]
        )
        with patch("app.ads.month_budget.preflight", return_value={}):
            approved = self.approve(created)
        entity = {
            **self.group,
            "budget_amount": resolved["budget_amount"],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }

        class Reader:
            def verify_native(inner, *args, **kwargs):
                return {"entity": entity, "parents": [self.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            result = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )
        self.assertEqual(result["items"][0]["verification_state"], "confirmed")
        self.assertTrue(result["items"][0]["evidence_json"]["setting_matches"])

    def test_two_approval_requests_create_one_approval_and_action(self):
        first = self.create()
        self.conn.commit()

        def approve(_):
            with db.connection() as conn:
                return service.approve(
                    conn,
                    self.org,
                    self.brand,
                    self.campaign,
                    first["id"],
                    first["content_hash"],
                    "test",
                )["approval_id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(approve, range(2)))
        self.assertEqual(values[0], values[1])
        self.assertEqual(self.count("approval"), 1)
        self.assertEqual(self.count("ads_action"), 1)

    def test_superseded_draft_cannot_be_revived_or_approved(self):
        first = self.create()
        self.create(supersedes_id=first["id"])
        with self.assertRaises(ValueError):
            self.approve(first)
        with self.assertRaises(ValueError):
            service.decide(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                first["id"],
                "deferred",
                "try again",
                (db.now_utc() + timedelta(days=1)).isoformat(),
                "test",
            )

    def test_carousel_copy_is_rejected_but_original_creative_snapshot_is_retained(self):
        # Contract B (F27-I02): dynamic creatives are now SUPPORTED (see test_ads_copy_variants.py)
        # -- only carousel still refuses a single-copy edit outright.
        first = self.create()
        self.assertEqual(first["items"][0]["creative_snapshot"], self.ad["creative"])
        self.entity(
            "3",
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative={"kind": "carousel", "fields": {"body": "one variation"}},
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "輪播"):
            self.create()
        self.assertEqual(
            data.get(self.conn, self.org, self.brand, self.campaign, first["id"])["items"][0][
                "creative_snapshot"
            ],
            self.ad["creative"],
        )

    def test_goal_change_does_not_invalidate_pause_but_does_invalidate_copy(self):
        copy_set = self.create()
        pause_set = self.create(
            items=[
                {
                    "kind": "pause",
                    "target_id": self.ad["id"],
                    "after": {"status": "PAUSED"},
                    "reason": "停止風險",
                }
            ]
        )
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='changed purpose' WHERE id=%s", (self.campaign,)
        )
        self.conn.commit()
        self.assertEqual(self.approve(pause_set)["status"], "approved")
        with self.assertRaises(ValueError):
            self.approve(copy_set)

    def test_budget_increase_becomes_stale_after_approved_month(self):
        first = self.create(
            items=[
                {
                    "kind": "budget",
                    "target_id": self.group["id"],
                    "after": {"daily_amount": 1200},
                    "reason": "加碼",
                }
            ]
        )
        with patch("app.ads.month_budget.preflight", return_value={}):
            self.approve(first)
        later = db.now_utc().date().replace(day=1) + timedelta(days=40)
        with patch.object(data.settings, "today_for_org", return_value=later):
            current = data.get(self.conn, self.org, self.brand, self.campaign, first["id"])
            self.assertEqual(current["items"][0]["verification_state"], "stale")
            with self.assertRaises(ValueError):
                service.report(
                    self.conn,
                    self.org,
                    self.brand,
                    self.campaign,
                    first["id"],
                    first["items"][0]["id"],
                    "test",
                )

    def test_slow_old_readback_never_overwrites_later_confirmation(self):
        approved = self.approve(self.create())
        calls = 0
        outer = self

        class Reader:
            def verify_native(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                ad = copy.deepcopy(outer.ad)
                if calls == 1:
                    verification.check(
                        outer.conn,
                        outer.org,
                        outer.brand,
                        outer.campaign,
                        approved["id"],
                        approved["items"][0]["id"],
                        "test",
                    )
                    ad["creative"]["fields"]["body"] = "old response"
                else:
                    ad["creative"]["fields"]["body"] = "新文案"
                return {"entity": ad, "parents": [outer.group, outer.root]}

        with patch.object(external_sync, "account_reader", return_value=(Reader(), {})):
            result = verification.check(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                approved["id"],
                approved["items"][0]["id"],
                "test",
            )
        self.assertEqual(result["items"][0]["verification_state"], "confirmed")
        self.assertEqual(result["items"][0]["evidence_json"]["observed"]["body"], "新文案")
        target = bindings.entity(self.conn, self.org, self.brand, self.campaign, self.ad["id"])
        self.assertEqual(target["creative"]["fields"]["body"], "新文案")

    def test_normal_api_entry_submit_reopen_and_cross_brand_guard(self):
        from app.main import app

        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        self.assertEqual(client.get(base + "/change-control").status_code, 200)
        result = client.post(
            base + "/change-sets",
            json={
                "operation_id": "http-retry",
                "title": "HTTP清單",
                "month": self.month,
                "items": [
                    {
                        "kind": "copy",
                        "target_id": self.ad["id"],
                        "after": {"body": "新文案"},
                        "reason": "test",
                    }
                ],
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        created = result.json()["change_set"]
        result = client.post(
            base + f"/change-sets/{created['id']}/approve",
            json={"content_hash": created["content_hash"]},
        )
        self.assertEqual(result.status_code, 200, result.text)
        reopened = client.get(base + f"/change-sets/{created['id']}").json()["change_set"]
        self.assertEqual(reopened["status"], "approved")
        self.assertEqual(reopened["content_hash"], created["content_hash"])

    def test_source_cleanup_is_stored_and_matched_by_the_queue_proposal(self):
        """F27-I25 / Contract F: `POST .../change-sets` can now carry `source: "cleanup"`, which
        `triage._matching_cleanup_set` reads straight off `plan_json`."""
        from app.ads import triage

        created = self.create(
            items=[
                {
                    "kind": "pause",
                    "target_id": self.ad["id"],
                    "after": {"status": "PAUSED"},
                    "reason": "清理超量廣告",
                }
            ],
            source="cleanup",
        )
        self.assertEqual(created["plan_json"]["source"], "cleanup")
        change_set, pause_items = triage._matching_cleanup_set(
            {self.campaign: [created]}, self.campaign
        )
        self.assertEqual(change_set["id"], created["id"])
        self.assertEqual([i["id"] for i in pause_items], [created["items"][0]["id"]])

    def test_cleanup_draft_superseded_by_the_latest_proposal(self):
        """F28-I15: 「改用最新提議」 creates a new cleanup set with `supersedes_id` = an outdated
        *draft* (never approved). The draft becomes `superseded`, keeps its own hash, and the
        queue's cleanup proposal match moves to the new set."""
        from app.ads import triage

        other = self.entity(
            "4",
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative={"kind": "image", "fields": {"body": "另一則", "image_hash": "image-two"}},
        )
        self.conn.commit()

        def pause(target):
            return {
                "kind": "pause",
                "target_id": target,
                "after": {"status": "PAUSED"},
                "reason": "清理",
            }

        outdated = self.create(items=[pause(self.ad["id"])], source="cleanup")
        self.assertEqual(outdated["status"], "draft")
        latest = self.create(
            items=[pause(self.ad["id"]), pause(other["id"])],
            source="cleanup",
            supersedes_id=outdated["id"],
        )
        old = data.get(self.conn, self.org, self.brand, self.campaign, outdated["id"])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(old["content_hash"], outdated["content_hash"])
        self.assertEqual(latest["status"], "draft")
        self.assertEqual(latest["plan_json"]["supersedes_id"], outdated["id"])
        self.assertEqual(latest["plan_json"]["source"], "cleanup")
        self.assertEqual([i["target_id"] for i in latest["items"]], [self.ad["id"], other["id"]])
        sets = triage._brand_change_sets_by_campaign(self.conn, self.org, self.brand)
        change_set, pause_items = triage._matching_cleanup_set(sets, self.campaign)
        self.assertEqual(change_set["id"], latest["id"])
        self.assertEqual(len(pause_items), 2)
        with self.assertRaises(ValueError):
            self.approve(outdated)

    def test_source_cleanup_refuses_a_non_pause_item(self):
        with self.assertRaisesRegex(ValueError, "只能包含暫停項目"):
            self.create(source="cleanup")  # default create() item is a `copy`

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            self.create(source="not-cleanup")

    def test_omitted_and_explicit_none_source_keep_the_same_content_hash(self):
        """Existing sets without `source` must keep their exact hashes -- the key is only added
        to `frozen`/`plan_json` when actually present."""
        first = self.create(operation_id=db.new_id("op"))
        second = self.create(operation_id=db.new_id("op"), source=None)
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertNotIn("source", first["plan_json"])
        self.assertNotIn("source", second["plan_json"])

    def test_source_other_than_cleanup_is_422_over_http(self):
        from app.main import app

        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        result = client.post(
            base + "/change-sets",
            json={
                "operation_id": "bad-source",
                "title": "測試",
                "month": self.month,
                "items": [
                    {
                        "kind": "copy",
                        "target_id": self.ad["id"],
                        "after": {"body": "新文案"},
                        "reason": "test",
                    }
                ],
                "source": "not-cleanup",
            },
        )
        self.assertEqual(result.status_code, 422, result.text)

    def test_http_create_without_source_is_unaffected_by_the_new_optional_field(self):
        """The route dumps every `CreateRequest` field including unset ones; `source` must be
        popped when `None` so the payload shape -- and therefore the hash -- matches a direct
        `service.create()` call that never mentions `source` at all."""
        from app.main import app

        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        via_http = client.post(
            base + "/change-sets",
            json={
                "operation_id": "http-no-source",
                "title": "只改原 B 文案",
                "month": self.month,
                "items": [
                    {
                        "kind": "copy",
                        "target_id": self.ad["id"],
                        "after": {"body": "新文案"},
                        "reason": "驗證新訴求，未聲稱因果",
                    }
                ],
            },
        ).json()["change_set"]
        via_service = self.create(operation_id=db.new_id("op"))
        self.assertEqual(via_http["content_hash"], via_service["content_hash"])
        self.assertNotIn("source", via_http["plan_json"])


class ChangeControlPlatformUrlTest(unittest.TestCase):
    """F22-I01: `platform_url` on every item `data.get()` returns -- computed at read time from
    the item's own `target` through `app/ads/adapters::platform_url`, never written to
    `plan_json`, so an existing set's `content_hash` is unaffected."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="平台連結測試", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="活動一"
        )["id"]
        self.meta_ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {
                "platform": "meta", "source_account": "123456789", "native_kind": "ad",
                "native_id": "ad_1", "native_status": "ACTIVE",
                "creative": {"kind": "image", "fields": {"body": "文案", "title": "標題"}},
            },
        )
        self.fake_ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {
                "platform": "fake", "source_account": "account", "native_kind": "ad",
                "native_id": "ad_2", "native_status": "ACTIVE",
                "creative": {"kind": "image", "fields": {"body": "文案", "title": "標題"}},
            },
        )
        self.conn.commit()
        self.month = db.now_utc().strftime("%Y-%m")

    def _create(self, ad_id, operation_id):
        return service.create(
            self.conn, self.org, self.brand, self.campaign,
            {
                "operation_id": operation_id, "month": self.month, "title": "文案調整",
                "items": [
                    {
                        "kind": "copy", "target_id": ad_id, "after": {"body": "新文案"},
                        "reason": "驗證新訴求，未聲稱因果",
                    }
                ],
            },
            "test",
        )

    def test_meta_target_gets_a_deep_link(self):
        created = self._create(self.meta_ad["id"], "meta-op")
        self.assertEqual(
            created["items"][0]["platform_url"],
            "https://adsmanager.facebook.com/adsmanager/manage/ads"
            "?act=123456789&selected_ad_ids=ad_1",
        )

    def test_unknown_platform_target_is_none(self):
        created = self._create(self.fake_ad["id"], "fake-op")
        self.assertIsNone(created["items"][0]["platform_url"])

    def test_platform_url_never_changes_content_hash(self):
        created = self._create(self.meta_ad["id"], "hash-op")
        before_hash = created["content_hash"]
        reread = data.get(self.conn, self.org, self.brand, self.campaign, created["id"])
        self.assertEqual(reread["content_hash"], before_hash)
        self.assertIn("platform_url", reread["items"][0])
        self.assertNotIn("platform_url", reread["plan_json"]["items"][0])
