"""Manual handoffs preserve plan/native identities and distinguish existence from settings."""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from app.ads import (
    change_control,
    change_control_data,
    change_control_launch,
    external_repository,
    external_sync,
    handoff_check,
    handoff_data,
    handoff_new_ad,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db, settings


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="人工交接品牌", actor="test", client_name=None
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        self.account = db.new_id("account")
        self.campaign = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "既有內部計畫",
                "goal_text": "檢驗訊息",
                "objective": "awareness",
                "start_date": self.today,
                "end_date": self.today + timedelta(days=7),
            },
            created_by="test",
        )["id"]
        self.group, self.ad = db.new_id("adg"), db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,%s,%s,100,'new')",
            (self.group, self.org, self.brand, self.campaign, "fixture", "計畫投放組"),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (self.ad, self.org, self.brand, self.campaign, self.group, "原廣告"),
        )
        self.root = self.node("root", "campaign", objective="awareness")
        self.native_group = self.node(
            "group",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="root",
            budget_type="daily",
            budget_amount=100,
        )
        self.native_ad = self.node(
            "B2",
            "ad",
            parent_native_kind="adset",
            parent_native_id="group",
            creative={
                "kind": "image",
                "fields": {
                    "title": "標題",
                    "body": "文案",
                    "description": "說明",
                    "image_hash": "new-image",
                },
            },
        )
        outer = self

        class Reader:
            def binding_kinds(self):
                return ("ad",)

            def verify_native(self, conn, org, brand, account, **kwargs):
                if kwargs["native_kind"] == "campaign":
                    return {"entity": copy.deepcopy(outer.root), "parents": []}
                if kwargs["native_kind"] == "adset":
                    return {
                        "entity": copy.deepcopy(outer.native_group),
                        "parents": [copy.deepcopy(outer.root)],
                    }
                return {
                    "entity": copy.deepcopy(outer.native_ad),
                    "parents": [copy.deepcopy(outer.native_group), copy.deepcopy(outer.root)],
                    "timezone_name": "Asia/Taipei",
                }

        self.reader = Reader()
        patch.object(
            external_sync,
            "account_reader",
            return_value=(self.reader, {"account_id": self.account}),
        ).start()
        self.addCleanup(patch.stopall)
        self.conn.commit()

    def node(self, native_id, kind, **extra):
        return {
            "platform": "fixture",
            "source_account": self.account,
            "native_kind": kind,
            "native_id": native_id,
            "name": native_id,
            "parent_native_kind": None,
            "parent_native_id": None,
            "native_status": "ACTIVE",
            "currency": "TWD",
            "start_date": self.today,
            "end_date": self.today + timedelta(days=7),
            "last_success_at": db.now_utc(),
            **extra,
        }

    def launch(self):
        # Only an ad with ready material is in a launch batch (F30 Unresolved 1).
        ad = campaigns.get_ad(self.conn, self.org, self.brand, self.ad)
        if ad["material_placement_id"] is None:
            from app.ads import handoff_assignment

            handoff_assignment.assign(
                self.conn, self.org, self.brand, self.campaign, self.ad, self.placement()["id"], 1
            )
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            result = change_control_launch.publish(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "human",
                db.new_id("op"),
                change_control_data.digest(frozen),
            )
        return result, {
            r["planned_kind"]: r
            for r in handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)["items"]
        }

    def check(self, item, kind, native_id, **extra):
        return handoff_check.check(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            item["id"],
            {
                "platform": "fixture",
                "source_account": self.account,
                "native_kind": kind,
                "native_id": native_id,
                "user_verified": False,
                **extra,
            },
            "human",
        )

    def placement(self):
        asset = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) "
            "VALUES(%s,%s,%s,%s,%s,'new.png','image/png',1,'ready')",
            (asset, self.org, self.brand, asset, f"{self.org}/{asset}"),
        )
        placement = assets.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            asset,
            {"headline": "標題", "body": "文案", "description": "說明"},
            "human",
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            (placement["id"],),
        )
        self.conn.commit()
        return placement

    def new_ad(self, replace_existing=False):
        external_repository.upsert_entity(self.conn, self.org, self.brand, self.campaign, self.root)
        parent = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_group
        )
        existing = self.node("B", "ad", parent_native_kind="adset", parent_native_id="group")
        saved_existing = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, existing
        )
        self.existing_ad_id = saved_existing["id"]
        placement = self.placement()
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.today.strftime("%Y-%m"),
            "title": "新增 B2",
            "placement_id": placement["id"],
            "revision": 1,
            "destination_entity_id": parent["id"],
            "reason": "下一個訊息假設",
        }
        if replace_existing:
            payload["replaces_entity_id"] = self.existing_ad_id
        draft = handoff_new_ad.create(
            self.conn, self.org, self.brand, self.campaign, payload, "human"
        )
        self.assertEqual(
            handoff_new_ad.create(self.conn, self.org, self.brand, self.campaign, payload, "human")[
                "id"
            ],
            draft["id"],
        )
        return draft

    def approve(self, draft):
        with patch(
            "app.ads.month_budget.preflight", return_value={"can_increase": True}
        ) as preflight:
            approved = change_control.approve(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                draft["id"],
                draft["content_hash"],
                "human",
            )
        self.assertEqual(preflight.call_args.args[4][0]["kind"], "new_ad")
        return approved, handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)[
            "items"
        ][0]

    def test_launch_hierarchy_preserves_internal_ids_and_unknown_required_settings(self):
        result, nodes = self.launch()
        self.assertEqual(len(nodes), 3)
        root = self.check(nodes["campaign"], "campaign", "root")
        self.assertTrue(root["entity_exists"], root["evidence_json"])
        self.assertEqual(root["status"], "confirmed")
        group = self.check(nodes["group"], "adset", "group")
        self.assertTrue(group["entity_exists"], group["evidence_json"])
        self.assertEqual(group["status"], "unknown")
        self.assertTrue(group["evidence_json"]["unknown_fields"])
        ad = self.check(nodes["ad"], "ad", "B2", user_verified=True)
        self.assertTrue(ad["entity_exists"], ad["evidence_json"])
        self.assertEqual(ad["status"], "confirmed", ad["evidence_json"])
        current = campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(current["id"], self.campaign)
        self.assertEqual(current["origin"], "internal")
        self.assertEqual(current["groups"][0]["id"], self.group)
        self.assertEqual(current["groups"][0]["ads"][0]["id"], self.ad)
        self.assertNotEqual(current["status"], "live")
        action = change_control_data.get(
            self.conn, self.org, self.brand, self.campaign, result["change_set_id"]
        )["items"][0]
        self.assertFalse(action["evidence_json"]["delivery_confirmed"])

    def _status(self):
        return campaigns.get_campaign(self.conn, self.org, self.brand, self.campaign)["status"]

    def _client(self):
        from fastapi.testclient import TestClient

        from app.ads import handoff_routes
        from app.main import app

        if not any(getattr(route, "path", "").endswith("/confirm-all") for route in app.routes):
            app.include_router(handoff_routes.router)
        return TestClient(app), f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"

    def _read_back_with_unreadable_fields(self):
        """A read-back launch whose ad set cannot see 2 launch settings and whose items cannot see
        3 fields: the group's landing URL, the ad's description and its material."""
        _, nodes = self.launch()
        frozen = nodes["group"]["expected_json"]["launch_settings"]
        audience = frozen["audience"]

        def read(value):
            return {"state": "read", "value": value}

        self.native_group["launch_settings"] = {
            "optimization_event": read(frozen["optimization_event"]),
            "bid_strategy": read(frozen["bid_strategy"]),
            "age": read({"age_min": audience["age_min"], "age_max": audience["age_max"]}),
            "gender": read(audience["gender"]),
            "countries": read({"countries": audience["countries"]}),
            "pixel_id": {"state": "unreadable", "reason": "沒有權限讀取像素。"},
            "placement": {"state": "unreadable", "reason": "平台沒有回傳版位。"},
        }
        self.native_ad["launch_settings"] = {
            "utm": read(nodes["ad"]["expected_json"]["launch_settings"]["utm"])
        }
        del self.native_ad["creative"]["fields"]["description"]
        self.check(nodes["campaign"], "campaign", "root")
        group = self.check(nodes["group"], "adset", "group")
        ad = self.check(nodes["ad"], "ad", "B2")
        self.assertEqual(group["status"], "unknown", group["evidence_json"])
        self.assertEqual(ad["status"], "unknown", ad["evidence_json"])
        return group, ad

    def test_confirm_all_marks_every_unreadable_field_in_one_call(self):
        """Drill-7 #18: one request confirms every unreadable setting and item field; a second
        call has nothing left; readable fields are untouched."""
        group, ad = self._read_back_with_unreadable_fields()
        client, base = self._client()

        def readback(view):
            return {f["key"]: f["state"] for f in view["settings_readback"]["fields"]}

        def unreadable(view):
            return {
                (i["name"], u["key"]): u["confirmed"]
                for i in view["items"]
                for u in i["unreadable"]
            }

        before = client.get(base + "/launch").json()
        self.assertEqual(
            {k: s for k, s in readback(before).items() if s != "match"},
            {"pixel_id": "unreadable", "placement": "unreadable"},
        )
        self.assertEqual(
            unreadable(before),
            {
                ("計畫投放組", "manual_settings.landing_url"): False,
                ("原廣告", "copy.description"): False,
                ("原廣告", "material"): False,
            },
        )

        first = client.post(base + "/handoff/launch/confirm-all")
        self.assertEqual(first.status_code, 200, first.text)
        result = first.json()
        self.assertEqual(result["confirmed_items"], 3)
        self.assertEqual(result["confirmed_settings"], 2)
        view = result["view"]
        self.assertEqual(set(view), set(before), "the same payload GET …/launch returns")
        self.assertEqual(
            readback(view),
            readback(before) | {"pixel_id": "self_confirmed", "placement": "self_confirmed"},
        )
        self.assertTrue(all(unreadable(view).values()), unreadable(view))
        self.assertEqual({i["state"] for i in view["items"]}, {"verified"})
        # A readable field is untouched: only the unreadable keys are recorded as confirmed.
        item = handoff_data.get(self.conn, self.org, self.brand, self.campaign, ad["id"])
        self.assertEqual(set(item["evidence_json"]["confirmed"]), {"copy.description", "material"})
        self.assertEqual(item["evidence_json"]["material_evidence"], "user_verified")
        item = handoff_data.get(self.conn, self.org, self.brand, self.campaign, group["id"])
        self.assertEqual(set(item["evidence_json"]["confirmed"]), {"manual_settings.landing_url"})
        launch = change_control_launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(set(launch["plan_json"]["settings_confirmed"]), {"pixel_id", "placement"})

        second = client.post(base + "/handoff/launch/confirm-all")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(
            (second.json()["confirmed_items"], second.json()["confirmed_settings"]), (0, 0)
        )
        self.assertEqual(second.json()["view"]["items"], view["items"])

    def test_confirm_all_with_nothing_unreadable_answers_zeros_and_the_view(self):
        client, base = self._client()
        # Before any launch is approved there is nothing to confirm: still 200, not a refusal.
        response = client.post(base + "/handoff/launch/confirm-all")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "confirmed_items": 0,
                "confirmed_settings": 0,
                "view": client.get(base + "/launch").json(),
            },
        )

    def test_campaign_readback_binds_ready_campaign_to_live(self):
        # F32-I01: `live` means "bound to a platform object by readback" (2026-09-26 ruling).
        # A hand-launched campaign left `ready` could never reach the close-out entry.
        _, nodes = self.launch()
        campaigns.set_campaign_status(self.conn, self.org, self.brand, self.campaign, "ready")
        self.conn.commit()
        root = self.check(nodes["campaign"], "campaign", "root")
        self.assertEqual(root["status"], "confirmed", root["evidence_json"])
        self.assertEqual(self._status(), "live")
        # A second readback of the same campaign node keeps `live`; it does not bounce.
        again = self.check(nodes["campaign"], "campaign", "root")
        self.assertEqual(again["status"], "confirmed", again["evidence_json"])
        self.assertEqual(self._status(), "live")

    def test_group_only_binding_leaves_campaign_ready(self):
        # Readback binds children through `bind_group`/`bind_ad` (handoff_check `_finish`);
        # only the campaign node's own binding moves the status.
        self.launch()
        campaigns.set_campaign_status(self.conn, self.org, self.brand, self.campaign, "ready")
        campaigns.bind_group(
            self.conn,
            self.org,
            self.brand,
            self.group,
            external_id="group",
            external_name="group",
            external_status="ACTIVE",
        )
        self.conn.commit()
        self.assertEqual(self._status(), "ready")

    def test_platform_objective_code_matches_the_planned_objective(self):
        # Drill 5: the plan says 購買, Meta says OUTCOME_SALES -- comparing the raw strings made
        # every real campaign read back as deviated.
        self.conn.execute("UPDATE ads_campaign SET objective='購買' WHERE id=%s", (self.campaign,))
        self.root["platform"] = "meta"
        self.root["objective"] = "OUTCOME_SALES"
        self.conn.commit()
        _result, nodes = self.launch()
        root = self.check(nodes["campaign"], "campaign", "root", platform="meta")
        self.assertEqual(root["status"], "confirmed", root["evidence_json"])
        self.assertIn("objective", root["evidence_json"]["matched_fields"])

    def test_platform_objective_of_another_family_is_a_deviation(self):
        self.conn.execute("UPDATE ads_campaign SET objective='購買' WHERE id=%s", (self.campaign,))
        self.root["platform"] = "meta"
        self.root["objective"] = "OUTCOME_TRAFFIC"
        self.conn.commit()
        _result, nodes = self.launch()
        root = self.check(nodes["campaign"], "campaign", "root", platform="meta")
        self.assertEqual(root["status"], "deviated", root["evidence_json"])
        self.assertIn("objective", root["evidence_json"]["deviated_fields"])

    def test_report_does_not_confirm_and_child_requires_parent(self):
        _, nodes = self.launch()
        reported = handoff_data.report(
            self.conn, self.org, self.brand, self.campaign, nodes["campaign"]["id"]
        )
        self.assertEqual(reported["status"], "reported")
        self.assertFalse(reported["entity_exists"])
        with self.assertRaisesRegex(ValueError, "上一層"):
            self.check(nodes["group"], "adset", "group")

    def test_new_ad_is_separate_and_binding_does_not_claim_platform_media_equivalence(self):
        draft = self.new_ad()
        _, item = self.approve(draft)
        with self.assertRaisesRegex(ValueError, "獨立身分"):
            self.check(item, "ad", "B")
        observed = self.check(item, "ad", "B2")
        self.assertTrue(observed["entity_exists"], observed["evidence_json"])
        self.assertEqual(observed["material_evidence"], "unknown")
        self.assertEqual(observed["status"], "unknown")
        verified = self.check(item, "ad", "B2", user_verified=True)
        self.assertEqual(verified["status"], "confirmed", verified["evidence_json"])
        self.assertEqual(verified["material_evidence"], "user_verified")
        self.assertFalse(verified["evidence_json"]["delivery_confirmed"])
        old = self.conn.execute(
            "SELECT native_status FROM ads_external_entity WHERE campaign_id=%s AND native_id='B'",
            (self.campaign,),
        ).fetchone()
        self.assertEqual(old["native_status"], "ACTIVE")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM ads_action WHERE campaign_id=%s AND kind='pause'",
                (self.campaign,),
            ).fetchone()["n"],
            0,
        )

    def test_wrong_parent_or_existing_other_brand_does_not_attach(self):
        _, nodes = self.launch()
        other = brands.create_brand(
            self.conn, org_id=self.org, name="其他品牌", actor="test", client_name=None
        )["id"]
        foreign = external_repository.create_imported_campaign(
            self.conn, self.org, other, name="別人的來源"
        )["id"]
        external_repository.upsert_entity(self.conn, self.org, other, foreign, self.root)
        self.conn.commit()
        failed = self.check(nodes["campaign"], "campaign", "root")
        self.assertEqual(failed["status"], "unknown")
        self.assertIsNone(failed["entity_id"])
        self.assertIsNone(
            campaigns.get_campaign(self.conn, self.org, self.brand, self.campaign)["external_id"]
        )

    def test_changed_approved_plan_is_stale(self):
        _, nodes = self.launch()
        self.conn.execute(
            "UPDATE ads_delivery_group SET daily_budget=200 WHERE id=%s", (self.group,)
        )
        self.conn.commit()
        stale = self.check(nodes["campaign"], "campaign", "root")
        self.assertEqual(stale["status"], "stale", stale["evidence_json"])
        self.assertIsNone(stale["entity_id"])

    def test_budget_unknown_still_prevents_new_ad_approval(self):
        draft = self.new_ad()
        with self.assertRaisesRegex(ValueError, "餘額尚不確定"):
            change_control.approve(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                draft["id"],
                draft["content_hash"],
                "human",
            )
        self.assertEqual(
            handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)["items"], []
        )

    def test_late_readback_does_not_overwrite_newer_attempt(self):
        _, nodes = self.launch()
        original = self.reader.verify_native
        calls = 0

        def late(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.check(nodes["campaign"], "campaign", "root")
                result = original(*args, **kwargs)
                result["entity"]["objective"] = "old-objective"
                return result
            return original(*args, **kwargs)

        with patch.object(self.reader, "verify_native", side_effect=late):
            result = self.check(nodes["campaign"], "campaign", "root")
        self.assertEqual(result["status"], "confirmed", result["evidence_json"])
        native = self.conn.execute(
            "SELECT objective FROM ads_external_entity WHERE id=%s", (result["entity_id"],)
        ).fetchone()
        self.assertEqual(native["objective"], "awareness")

    def test_reconsider_requires_fresh_stopped_ad_then_allows_new_draft(self):
        from app.ads import handoff_reconsider

        draft = self.new_ad()
        _, item = self.approve(draft)
        with self.assertRaisesRegex(ValueError, "確定身分"):
            handoff_reconsider.reconsider(
                self.conn, self.org, self.brand, self.campaign, item["id"], "修訂成品"
            )
        self.check(item, "ad", "B2", user_verified=True)
        with self.assertRaisesRegex(ValueError, "尚未證明已停止"):
            handoff_reconsider.reconsider(
                self.conn, self.org, self.brand, self.campaign, item["id"], "修訂成品"
            )
        self.native_ad["native_status"] = "PAUSED"
        released = handoff_reconsider.reconsider(
            self.conn, self.org, self.brand, self.campaign, item["id"], "停止後測試另一版本"
        )
        self.assertEqual(released["status"], "stale")
        self.assertEqual(
            released["entity_id"],
            handoff_data.get(self.conn, self.org, self.brand, self.campaign, item["id"])[
                "entity_id"
            ],
        )
        again = handoff_new_ad.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "title": "新版本",
                "month": self.today.strftime("%Y-%m"),
                "placement_id": item["placement_id"],
                "revision": item["placement_revision"],
                "destination_entity_id": item["expected_json"]["destination_entity_id"],
                "reason": "原廣告停止後重看",
            },
            "human",
        )
        self.assertNotEqual(again["id"], draft["id"])
        self.assertIn("B2", again["items"][0]["existing_native_ids"])

    def test_http_create_approve_check_reopen_new_ad(self):
        from fastapi.testclient import TestClient

        from app.ads import handoff_routes
        from app.main import app

        if not any(getattr(route, "path", "").endswith("/new-ad-handoffs") for route in app.routes):
            app.include_router(handoff_routes.router)
        client = TestClient(app)
        draft = self.new_ad()
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        with patch("app.ads.month_budget.preflight", return_value={"can_increase": True}):
            response = client.post(
                base + "/change-sets/" + draft["id"] + "/approve",
                json={"content_hash": draft["content_hash"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        item = client.get(base + "/handoff").json()["items"][0]
        reported = client.post(base + "/handoff/" + item["id"] + "/report")
        self.assertEqual(reported.json()["item"]["status"], "reported")
        checked = client.post(
            base + "/handoff/" + item["id"] + "/check",
            json={
                "platform": "fixture",
                "source_account": self.account,
                "native_kind": "ad",
                "native_id": "B2",
                "user_verified": True,
            },
        )
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.json()["item"]["status"], "confirmed", checked.text)
        reopened = client.get(base + "/handoff").json()["items"][0]
        self.assertTrue(reopened["entity_exists"])
        self.assertEqual(reopened["material_evidence"], "user_verified")

    def test_material_copy_reference_is_persisted_and_revision_revalidated(self):
        from app.ads import material_tasks

        root = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.root
        )
        parent = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_group
        )
        ad = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_ad
        )
        self.assertTrue(root["id"] and parent["id"])
        task = material_tasks.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "mode": "copy",
                "title": "獨立文案",
                "copy_fields": {"headline": "新標題", "body": "新文案"},
            },
            "human",
        )
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.today.strftime("%Y-%m"),
            "title": "採用選定素材文案",
            "material_task_id": task["id"],
            "material_revision": task["revision"],
            "items": [
                {
                    "kind": "copy",
                    "target_id": ad["id"],
                    "after": {"body": "新文案"},
                    "reason": "檢驗文案",
                }
            ],
        }
        draft = change_control.create(
            self.conn, self.org, self.brand, self.campaign, payload, "human"
        )
        self.assertEqual(draft["material_task_id"], task["id"])
        self.assertEqual(draft["plan_json"]["material_content_hash"], task["content_hash"])
        self.assertIsNone(draft["review_id"])
        # Import metadata does not invalidate the selected immutable material revision.
        self.conn.execute(
            "UPDATE ads_external_entity SET updated_at=now() WHERE id=%s", (ad["id"],)
        )
        approved = change_control.approve(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            draft["id"],
            draft["content_hash"],
            "human",
        )
        self.assertEqual(approved["status"], "approved")
        pending_payload = {**payload, "operation_id": db.new_id("op")}
        pending = change_control.create(
            self.conn, self.org, self.brand, self.campaign, pending_payload, "human"
        )
        material_tasks.mutate(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            task["id"],
            {
                "operation_id": db.new_id("op"),
                "expected_revision": task["revision"],
                "copy_fields": {"headline": "更新標題", "body": "更新文案"},
            },
            "update",
            "human",
        )
        payload["operation_id"] = db.new_id("op")
        with self.assertRaisesRegex(ValueError, "版本已變更"):
            change_control.create(self.conn, self.org, self.brand, self.campaign, payload, "human")
        with self.assertRaisesRegex(ValueError, "版本已變更"):
            change_control.approve(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                pending["id"],
                pending["content_hash"],
                "human",
            )

    def test_new_ad_resolves_selected_material_and_revalidates_before_approval(self):
        from app.ads import material_tasks

        seed = self.new_ad()
        placement = assets.placement(
            self.conn, self.org, self.brand, self.campaign, seed["items"][0]["target_id"]
        )
        task = material_tasks.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "mode": "existing",
                "title": "新測試成品",
                "copy_fields": placement["copy_fields"],
            },
            "human",
        )

        def mutate(current, action, **values):
            return material_tasks.mutate(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                task["id"],
                {
                    "operation_id": db.new_id("op"),
                    "expected_revision": current["revision"],
                    **values,
                },
                action,
                "human",
            )

        gathered = mutate(
            task,
            "candidates",
            asset_ids=[placement["asset_id"]],
            prompt={"source": "manual", "text": "原始成圖提示詞"},
            reference_asset_ids=[placement["asset_id"]],
        )
        selected = mutate(
            gathered,
            "select",
            candidate_id=gathered["candidates"][0]["id"],
            content_hash=gathered["content_hash"],
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            (selected["placement_id"],),
        )
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.today.strftime("%Y-%m"),
            "title": "採用成品",
            "reason": "比較訊息",
            "placement_id": selected["placement_id"],
            "revision": selected["placement_revision"],
            "destination_entity_id": seed["items"][0]["after"]["destination_entity_id"],
        }
        draft = handoff_new_ad.create(
            self.conn, self.org, self.brand, self.campaign, payload, "human"
        )
        self.assertEqual(draft["material_task_id"], task["id"])
        self.assertEqual(draft["material_revision"], selected["revision"])
        self.assertEqual(draft["plan_json"]["material_content_hash"], selected["content_hash"])
        handoff_new_ad.validate_reference(self.conn, self.org, self.brand, self.campaign, draft)
        revised = assets.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            selected["placement_id"],
            selected["placement_revision"],
            {"purpose": "補充投放用途", "copy_fields": {"body": "人工修訂的投放文案"}},
            "human",
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' "
            "WHERE id=%s AND revision=%s",
            (revised["id"], revised["revision"]),
        )
        derived = handoff_new_ad.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {**payload, "operation_id": db.new_id("op"), "revision": revised["revision"]},
            "human",
        )
        provenance = derived["plan_json"]["material_placement_source"]
        self.assertEqual(derived["material_task_id"], task["id"])
        self.assertEqual(derived["material_revision"], selected["revision"])
        self.assertEqual(provenance["selected_revision"], selected["placement_revision"])
        self.assertEqual(provenance["applied_revision"], revised["revision"])
        self.assertEqual(provenance["relation"], "revised_placement")
        self.assertNotEqual(provenance["selected_copy_hash"], provenance["applied_copy_hash"])
        handoff_new_ad.validate_reference(self.conn, self.org, self.brand, self.campaign, derived)
        saved_source = material_tasks.get(
            self.conn, self.org, self.brand, self.campaign, task["id"], selected["revision"]
        )["candidates"][0]
        self.assertEqual(saved_source["prompt"]["text"], "原始成圖提示詞")
        self.assertEqual(saved_source["reference_asset_ids"], [placement["asset_id"]])
        mutate(selected, "update", instruction="換下一個方向")
        with self.assertRaisesRegex(ValueError, "素材任務已修訂"):
            self.approve(draft)

    def replace_task_placement(self, seed, entity_id):
        """A "replace this ad" request carried through to a selected, confirmed placement."""
        from app.ads import material_tasks

        image = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) "
            "VALUES(%s,%s,%s,%s,%s,'replace.png','image/png',1,'ready')",
            (image, self.org, self.brand, image, f"{self.org}/{image}"),
        )
        self.conn.commit()
        task = material_tasks.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {"operation_id": db.new_id("op"), "replaces_entity_id": entity_id},
            "human",
        )

        def mutate(current, action, **values):
            return material_tasks.mutate(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                task["id"],
                {
                    "operation_id": db.new_id("op"),
                    "expected_revision": current["revision"],
                    **values,
                },
                action,
                "human",
            )

        gathered = mutate(task, "candidates", asset_ids=[image])
        selected = mutate(
            gathered,
            "select",
            candidate_id=gathered["candidates"][0]["id"],
            content_hash=gathered["content_hash"],
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            (selected["placement_id"],),
        )
        self.conn.commit()
        return task, {
            "operation_id": db.new_id("op"),
            "month": self.today.strftime("%Y-%m"),
            "title": "換掉舊廣告",
            "reason": "舊廣告偏貴",
            "placement_id": selected["placement_id"],
            "revision": selected["placement_revision"],
            "destination_entity_id": seed["items"][0]["after"]["destination_entity_id"],
        }

    def test_new_ad_from_replace_request_inherits_the_ad_and_locks_cancel_after_approval(self):
        from app.ads import material_tasks

        seed = self.new_ad()
        task, payload = self.replace_task_placement(seed, self.existing_ad_id)
        draft = handoff_new_ad.create(
            self.conn, self.org, self.brand, self.campaign, payload, "human"
        )
        self.assertEqual(draft["material_task_id"], task["id"])
        self.assertEqual(draft["items"][0]["replaces_entity_id"], self.existing_ad_id)
        self.assertEqual(draft["replaces"]["entity_id"], self.existing_ad_id)
        # A draft does not hold the request; approval does.
        self.approve(draft)
        with self.assertRaises(material_tasks.InUse):
            material_tasks.cancel(
                self.conn, self.org, self.brand, self.campaign, task["id"], "human"
            )
        self.assertIsNone(
            material_tasks.get(self.conn, self.org, self.brand, self.campaign, task["id"])[
                "cancelled_at"
            ]
        )

    def test_explicit_replacement_wins_and_a_cancelled_request_cannot_hand_off(self):
        from app.ads import material_tasks

        seed = self.new_ad()
        other = external_repository.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            self.node("C", "ad", parent_native_kind="adset", parent_native_id="group"),
        )
        self.conn.commit()
        task, payload = self.replace_task_placement(seed, self.existing_ad_id)
        explicit = handoff_new_ad.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {**payload, "replaces_entity_id": other["id"]},
            "human",
        )
        self.assertEqual(explicit["items"][0]["replaces_entity_id"], other["id"])
        # The inherited ad is no longer running: nothing left to replace, the default drops.
        self.conn.execute(
            "UPDATE ads_external_entity SET native_status='PAUSED' WHERE id=%s",
            (self.existing_ad_id,),
        )
        self.conn.commit()
        plain = handoff_new_ad.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {**payload, "operation_id": db.new_id("op")},
            "human",
        )
        self.assertIsNone(plain["items"][0]["replaces_entity_id"])
        material_tasks.cancel(self.conn, self.org, self.brand, self.campaign, task["id"], "human")
        with self.assertRaisesRegex(ValueError, "已取消"):
            handoff_new_ad.create(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                {**payload, "operation_id": db.new_id("op")},
                "human",
            )
        with self.assertRaisesRegex(ValueError, "已取消"):
            handoff_new_ad.validate_reference(
                self.conn, self.org, self.brand, self.campaign, explicit
            )

    def test_new_ad_review_reference_checks_live_premise_and_age(self):
        from app.ads import review_evidence

        external_repository.upsert_entity(self.conn, self.org, self.brand, self.campaign, self.root)
        external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_group
        )
        source = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_ad
        )
        premise = review_evidence.premise(
            source, change_control_data.campaign(self.conn, self.org, self.brand, self.campaign)
        )
        review = {
            "status": "ready",
            "entity_id": source["id"],
            "window_end": self.today,
            "evidence_hash": "evidence",
            "evidence_json": {"premise": premise},
            "result_json": {
                "recommendations": [
                    {"id": "rec", "recommendation": "new_test", "target_id": source["id"]}
                ]
            },
        }
        with patch("app.ads.handoff_new_ad.review_rounds.get", return_value=review):
            ref = handoff_new_ad._review(
                self.conn, self.org, self.brand, self.campaign, "review", "rec"
            )
            self.assertEqual(ref["source_entity_id"], source["id"])
            review["window_end"] = self.today - timedelta(days=31)
            with self.assertRaisesRegex(ValueError, "超過三十日"):
                handoff_new_ad._review(
                    self.conn, self.org, self.brand, self.campaign, "review", "rec"
                )
            review["window_end"] = self.today
            self.conn.execute(
                "UPDATE ads_campaign SET goal_text='改過的目標' WHERE id=%s", (self.campaign,)
            )
            with self.assertRaisesRegex(ValueError, "目標已變更"):
                handoff_new_ad._review(
                    self.conn, self.org, self.brand, self.campaign, "review", "rec"
                )

    def test_failed_read_does_not_create_or_advance_observation_time(self):
        draft = self.new_ad()
        _, item = self.approve(draft)
        with patch.object(self.reader, "verify_native", side_effect=ValueError("unavailable")):
            failed = self.check(item, "ad", "B2")
        self.assertIsNone(failed["observed_at"])
        self.assertIn("attempted_at", failed["evidence_json"])
        first = self.conn.execute(
            "SELECT first_observed_at FROM ads_action WHERE id=%s", (item["action_id"],)
        ).fetchone()
        self.assertIsNone(first["first_observed_at"])
        observed = self.check(item, "ad", "B2")
        self.assertIsNotNone(observed["observed_at"])
        with patch.object(self.reader, "verify_native", side_effect=ValueError("unavailable")):
            failed_again = self.check(item, "ad", "B2")
        self.assertEqual(failed_again["observed_at"], observed["observed_at"])

    def test_material_copy_rejects_different_after_text(self):
        from app.ads import handoff_material, material_tasks

        task = material_tasks.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "mode": "copy",
                "title": "選定文案",
                "copy_fields": {"body": "選定文字"},
            },
            "human",
        )
        with self.assertRaisesRegex(ValueError, "與選定素材文案不同"):
            handoff_material.reference(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                task["id"],
                task["revision"],
                [{"kind": "copy", "target_id": "any", "after": {"body": "別的文字"}}],
            )

    def test_cancelled_copy_request_cannot_be_cited_or_approved(self):
        from app.ads import handoff_material, material_tasks

        task = material_tasks.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "mode": "copy",
                "title": "選定文案",
                "copy_fields": {"body": "選定文字"},
            },
            "human",
        )
        items = [{"kind": "copy", "target_id": "any", "after": {"body": "選定文字"}}]
        cited = handoff_material.reference(
            self.conn, self.org, self.brand, self.campaign, task["id"], task["revision"], items
        )
        self.assertEqual(cited["material_task_id"], task["id"])
        material_tasks.cancel(self.conn, self.org, self.brand, self.campaign, task["id"], "human")
        with self.assertRaisesRegex(ValueError, "已取消"):
            handoff_material.reference(
                self.conn, self.org, self.brand, self.campaign, task["id"], task["revision"], items
            )
        # A draft cut before the cancel cannot be approved afterwards.
        with self.assertRaisesRegex(ValueError, "已取消"):
            handoff_material.validate_approval(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                {"items": items, "plan_json": cited},
            )

    def test_planned_material_http_assignment_changes_hash_and_launch_readback_uses_copy(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/launch-materials"
        before = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        placement = self.placement()
        workspace = client.get(base)
        self.assertEqual(workspace.status_code, 200, workspace.text)
        self.assertEqual(workspace.json()["planned_ads"][0]["assignment_status"], "unassigned")
        assigned = client.put(
            base + "/" + self.ad, json={"placement_id": placement["id"], "revision": 1}
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["planned_ads"][0]["copy_fields"]["body"], "文案")
        description = client.get(base.removesuffix("/launch-materials") + "/publish").json()[
            "describe"
        ]
        node = next(row for row in description["checklist"] if row["id"] == self.ad)
        fields = {row["label"]: row["value"] for row in node["fields"]}
        self.assertEqual(fields["指定素材檔案"], "new.png")
        self.assertEqual(fields["文案"], "文案")
        self.assertEqual(fields["標題"], "標題")
        after = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        self.assertNotEqual(change_control_data.digest(before), change_control_data.digest(after))
        self.assertEqual(
            after["groups"][0]["ads"][0]["material_assignment"]["placement_id"], placement["id"]
        )
        with self.assertRaisesRegex(ValueError, "已改變"):
            change_control_launch.publish(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "human",
                db.new_id("op"),
                change_control_data.digest(before),
            )
        _, items = self.launch()
        self.assertEqual(items["ad"]["placement_id"], placement["id"])
        self.assertEqual(items["ad"]["expected_json"]["copy"]["title"], "標題")
        self.check(items["campaign"], "campaign", "root")
        self.check(items["group"], "adset", "group")
        checked = self.check(items["ad"], "ad", "B2", user_verified=True)
        self.assertEqual(checked["status"], "confirmed", checked["evidence_json"])
        self.assertEqual(checked["material_evidence"], "user_verified")
        self.assertEqual(checked["planned_id"], self.ad)
        blocked = client.put(base + "/" + self.ad, json={"placement_id": None, "revision": None})
        self.assertEqual(blocked.status_code, 409)

    def test_planned_material_stale_revision_is_visible_and_defers_the_ad(self):
        from app.ads import handoff_assignment

        placement = self.placement()
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, placement["id"], 1
        )
        old = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        assets.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            placement["id"],
            1,
            {"copy_fields": {"body": "新版本"}},
            "human",
        )
        self.conn.commit()
        workspace = handoff_assignment.workspace(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(workspace["planned_ads"][0]["assignment_status"], "stale")
        self.assertFalse(any(p["id"] == placement["id"] for p in workspace["ready_placements"]))
        handoff = handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)
        self.assertFalse(any(p["id"] == placement["id"] for p in handoff["ready_placements"]))
        # Never approved, the revised material is not ready: the ad now waits outside the batch
        # (F30 Unresolved 1), which leaves no ready ad -- not a launch.
        with self.assertRaisesRegex(ValueError, "launch_no_ready_ads"):
            change_control_launch.publish(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "human",
                db.new_id("op"),
                change_control_data.digest(old),
            )
        deferred = []
        change_control_launch.snapshot(
            self.conn, self.org, self.brand, self.campaign, deferred=deferred
        )
        self.assertEqual([d["ad_id"] for d in deferred], [self.ad])
        cleared = handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, None, None
        )
        self.assertEqual(cleared["planned_ads"][0]["assignment_status"], "unassigned")

    def test_planned_material_scope_and_confirmation_are_required(self):
        from app.ads import handoff_assignment

        placement = self.placement()
        with self.assertRaisesRegex(ValueError, "找不到此品牌活動"):
            handoff_assignment.assign(
                self.conn, self.org, self.brand, self.campaign, "foreign-ad", placement["id"], 1
            )
        self.conn.rollback()
        other = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "另一計畫",
                "goal_text": "比較",
                "objective": "awareness",
            },
            created_by="test",
        )["id"]
        foreign = assets.attach(
            self.conn,
            self.org,
            self.brand,
            other,
            placement["asset_id"],
            {"body": "其他活动"},
            "human",
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "找不到素材安排"):
            handoff_assignment.assign(
                self.conn, self.org, self.brand, self.campaign, self.ad, foreign["id"], 1
            )
        self.conn.rollback()
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=NULL WHERE id=%s", (placement["id"],)
        )
        with self.assertRaisesRegex(ValueError, "尚未確認"):
            handoff_assignment.assign(
                self.conn, self.org, self.brand, self.campaign, self.ad, placement["id"], 1
            )
        self.conn.rollback()
        self.assertNotEqual(other, self.campaign)

    def test_launch_hash_ignores_unused_placements(self):
        from app.ads import handoff_assignment

        selected = self.placement()
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, selected["id"], 1
        )
        before = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        unused = self.placement()
        assets.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            unused["id"],
            1,
            {"copy_fields": {"body": "沒有指派的候選文案"}},
            "human",
        )
        self.conn.commit()
        after = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(change_control_data.digest(before), change_control_data.digest(after))

    def test_an_ad_without_ready_material_is_deferred_from_the_batch(self):
        # F30 Unresolved 1: no workbench output or copy stands in for the material any more.
        deferred = []
        frozen = change_control_launch.snapshot(
            self.conn, self.org, self.brand, self.campaign, deferred=deferred
        )
        self.assertEqual(frozen["groups"][0]["ads"], [])
        self.assertEqual(frozen["outputs"], [])
        self.assertEqual(
            deferred, [{"ad_id": self.ad, "name": "原廣告", "group_name": "計畫投放組"}]
        )
