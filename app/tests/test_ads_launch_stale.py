"""F28-I04: an approved launch whose plan changed has an exit -- see the diff, re-approve the
current plan as the next version, or write the approved values back. Nothing writes a platform."""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import (
    change_control_data,
    change_control_launch,
    external_sync,
    handoff_assignment,
    handoff_check,
    handoff_data,
    month_budget,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db, settings


class LaunchStaleTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="核准失效品牌", actor="test", client_name=None
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        self.account = db.new_id("account")
        self.campaign = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "秋季上架",
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
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,%s,%s,500,'new')",
            (self.group, self.org, self.brand, self.campaign, "fixture", "新客廣告組"),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (self.ad, self.org, self.brand, self.campaign, self.group, "秋季主打（圖）"),
        )
        self.root = self.node("root", "campaign", objective="awareness")
        self.native_group = self.node(
            "group",
            "adset",
            parent_native_kind="campaign",
            parent_native_id="root",
            budget_type="daily",
            budget_amount=500,
        )
        outer = self

        class Reader:
            def binding_kinds(self):
                return ("ad",)

            def verify_native(self, conn, org, brand, account, **kwargs):
                if kwargs["native_kind"] == "campaign":
                    return {"entity": copy.deepcopy(outer.root), "parents": []}
                return {
                    "entity": copy.deepcopy(outer.native_group),
                    "parents": [copy.deepcopy(outer.root)],
                }

        patch.object(
            external_sync, "account_reader", return_value=(Reader(), {"account_id": self.account})
        ).start()
        self.addCleanup(patch.stopall)
        self.conn.commit()
        self.base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/handoff"

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

    # -- helpers ---------------------------------------------------------------------------------

    def launch(self):
        # Only an ad with ready material is in a launch batch (F30 Unresolved 1).
        ad = campaigns.get_ad(self.conn, self.org, self.brand, self.ad)
        if ad["material_placement_id"] is None:
            self.assigned_material()
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
        return result["change_set_id"]

    def workspace(self):
        return handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)

    def items(self):
        return {r["planned_kind"]: r for r in self.workspace()["items"]}

    def check(self, item, kind, native_id):
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
            },
            "human",
        )

    def sql(self, statement, *params):
        self.conn.execute(statement, params)
        self.conn.commit()

    def change_set(self, set_id):
        return self.conn.execute("SELECT * FROM ads_change_set WHERE id=%s", (set_id,)).fetchone()

    def reapprove(self, stale, **kwargs):
        return change_control_launch.reapprove(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            kwargs.get("set_id", stale["change_set_id"]),
            kwargs.get("content_hash", stale["content_hash"]),
            "human",
        )

    def revert(self, stale, **kwargs):
        return change_control_launch.revert(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            stale["change_set_id"],
            kwargs.get("content_hash", stale["content_hash"]),
            "human",
        )

    # -- tests -----------------------------------------------------------------------------------

    def test_budget_raised_after_approval_is_reported_on_read_and_reapproves(self):
        set_id = self.launch()
        self.assertIsNone(self.workspace()["launch_stale"])
        self.sql(
            "UPDATE ads_delivery_group SET daily_budget=600,updated_at=now() WHERE id=%s",
            self.group,
        )

        stale = self.workspace()["launch_stale"]
        self.assertIsNotNone(stale, "computed on read, without any check")
        self.assertEqual(stale["change_set_id"], set_id)
        self.assertEqual(len(stale["diff"]), 1, stale["diff"])
        row = stale["diff"][0]
        items = self.items()
        self.assertEqual(
            {k: row[k] for k in ("kind", "item_id", "name", "field", "field_label")},
            {
                "kind": "group",
                "item_id": items["group"]["id"],
                "name": "新客廣告組",
                "field": "daily_budget",
                "field_label": "每日預算",
            },
        )
        self.assertEqual((row["before"], row["after"]), (500.0, 600.0))
        self.assertEqual(stale["unchanged_count"], 2)
        self.assertTrue(stale["revertible"])
        self.assertIsNone(stale["revert_blocker"])
        self.assertIsNotNone(stale["changed_at"])
        self.assertGreater(stale["changed_at"], stale["approved_at"])

        seen = {}

        def preflight(conn, org, brand, month, items):
            # The superseded launch no longer counts against the month; only the new one does.
            seen["pending"] = month_budget._pending(conn, org, brand, month)
            seen["items"] = items
            return {"can_increase": True}

        with patch.object(change_control_launch.month_budget, "preflight", side_effect=preflight):
            result = self.reapprove(stale)
        new_id = result["change_set_id"]
        self.assertNotEqual(new_id, set_id)
        self.assertEqual(seen["pending"], [])
        self.assertEqual(seen["items"][0]["after"]["daily_amount"], 600.0)
        self.assertEqual(self.change_set(set_id)["status"], "superseded")
        new = self.change_set(new_id)
        self.assertEqual(new["status"], "approved")
        self.assertEqual(new["plan_json"]["supersedes_id"], set_id)
        self.assertEqual(new["plan_json"]["version"], 2)
        workspace = self.workspace()
        self.assertIsNone(workspace["launch_stale"])
        self.assertEqual({i["change_set_id"] for i in workspace["items"]}, {new_id})
        old_action = self.conn.execute(
            "SELECT * FROM ads_action WHERE change_set_id=%s", (set_id,)
        ).fetchone()
        self.assertEqual(old_action["verification_state"], "stale")
        self.assertEqual(old_action["evidence_json"]["superseded_by"], new_id)

        # A retry of the same decision answers with the same new version.
        with patch.object(change_control_launch.month_budget, "preflight") as again:
            self.assertEqual(self.reapprove(stale)["change_set_id"], new_id)
            again.assert_not_called()

    def test_reapprove_that_fails_the_month_budget_changes_nothing(self):
        set_id = self.launch()
        self.sql("UPDATE ads_delivery_group SET daily_budget=900 WHERE id=%s", self.group)
        stale = self.workspace()["launch_stale"]
        with (
            patch.object(
                change_control_launch.month_budget,
                "preflight",
                side_effect=ValueError("這份變更超過本月總額；尚未讀回完成的降額不能先釋放額度。"),
            ),
            self.assertRaisesRegex(ValueError, "超過本月總額"),
        ):
            self.reapprove(stale)
        self.assertEqual(self.change_set(set_id)["status"], "approved")
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) AS n FROM ads_change_set WHERE campaign_id=%s", (self.campaign,)
            ).fetchone()["n"],
            1,
        )
        self.assertEqual(self.workspace()["launch_stale"]["change_set_id"], set_id)

    def test_renamed_ad_reverts_and_the_original_approval_stands(self):
        set_id = self.launch()
        approval_id = self.change_set(set_id)["approval_id"]
        self.sql("UPDATE ads_ad SET name='秋季主打（圖）・限量' WHERE id=%s", self.ad)
        # A readback in the meantime marks the item stale, as today.
        stale_item = self.check(self.items()["campaign"], "campaign", "root")
        self.assertEqual(stale_item["status"], "stale")

        stale = self.workspace()["launch_stale"]
        row = stale["diff"][0]
        self.assertEqual(
            (row["kind"], row["field"], row["field_label"], row["before"], row["after"]),
            ("ad", "name", "廣告名稱", "秋季主打（圖）", "秋季主打（圖）・限量"),
        )
        self.assertEqual(row["item_id"], self.items()["ad"]["id"])
        self.assertTrue(stale["revertible"])

        self.revert(stale)
        self.assertEqual(
            campaigns.get_ad(self.conn, self.org, self.brand, self.ad)["name"], "秋季主打（圖）"
        )
        self.assertIsNone(self.workspace()["launch_stale"])
        current = self.change_set(set_id)
        self.assertEqual((current["status"], current["approval_id"]), ("approved", approval_id))
        self.assertEqual(self.items()["campaign"]["status"], "pending")
        audit = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_id=%s AND action='revert_plan'", (set_id,)
        ).fetchone()
        self.assertIsNotNone(audit)
        # The launch can be checked again against the original approval.
        again = self.check(self.items()["campaign"], "campaign", "root")
        self.assertEqual(again["status"], "confirmed", again["evidence_json"])

    def test_manual_settings_revert_keeps_post_build_records(self):
        self.launch()
        campaigns_row = self.conn.execute(
            "SELECT context_json FROM ads_campaign WHERE id=%s", (self.campaign,)
        ).fetchone()
        context = dict(campaigns_row["context_json"] or {})
        context["manual_delivery"] = {
            self.group: {
                "values": {"landing_url": "https://example.test/new", "execution_notes": "已建好"}
            }
        }
        self.sql(
            "UPDATE ads_campaign SET context_json=%s WHERE id=%s", db.jsonb(context), self.campaign
        )
        stale = self.workspace()["launch_stale"]
        self.assertEqual(
            [(r["field"], r["field_label"]) for r in stale["diff"]],
            [("manual_settings.landing_url", "落地頁網址")],
            "a post-build record is not plan content and never makes a launch stale",
        )
        self.revert(stale)
        values = self.conn.execute(
            "SELECT context_json FROM ads_campaign WHERE id=%s", (self.campaign,)
        ).fetchone()["context_json"]["manual_delivery"][self.group]["values"]
        self.assertEqual(values, {"execution_notes": "已建好"})
        self.assertIsNone(self.workspace()["launch_stale"])

    def test_verified_item_keeps_its_result_and_binding_after_reapproval(self):
        old_set = self.launch()
        items = self.items()
        root = self.check(items["campaign"], "campaign", "root")
        self.assertEqual(root["status"], "confirmed", root["evidence_json"])
        group = self.check(items["group"], "adset", "group")
        self.assertIsNotNone(group["entity_id"])
        self.sql("UPDATE ads_delivery_group SET daily_budget=600 WHERE id=%s", self.group)

        stale = self.workspace()["launch_stale"]
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            new_set = self.reapprove(stale)["change_set_id"]

        now = self.items()
        self.assertEqual(now["campaign"]["change_set_id"], new_set)
        self.assertEqual(now["campaign"]["status"], "confirmed")
        self.assertEqual(now["campaign"]["entity_id"], root["entity_id"])
        self.assertEqual(now["campaign"]["evidence_json"], root["evidence_json"])
        self.assertEqual(now["group"]["status"], "pending")
        self.assertIsNone(now["group"]["entity_id"])
        self.assertEqual(now["ad"]["status"], "pending")
        released = handoff_data.get(
            self.conn, self.org, self.brand, self.campaign, items["group"]["id"]
        )
        self.assertIsNone(released["entity_id"])
        self.assertEqual(released["evidence_json"]["superseded_by"], new_set)
        self.assertEqual(released["evidence_json"]["entity_id"], group["entity_id"])
        self.assertEqual(self.change_set(old_set)["status"], "superseded")

        # The changed group is checked afresh against the same platform object (its parent's
        # binding was carried) and now reads back the new budget as a deviation.
        rechecked = self.check(now["group"], "adset", "group")
        self.assertEqual(rechecked["entity_id"], group["entity_id"])
        self.assertEqual(rechecked["status"], "deviated", rechecked["evidence_json"])
        self.assertIn("budget_amount", rechecked["evidence_json"]["deviated_fields"])

    def test_concurrent_edit_after_viewing_is_refused_with_409(self):
        set_id = self.launch()
        self.sql("UPDATE ads_ad SET name='第一次改名' WHERE id=%s", self.ad)
        stale = self.workspace()["launch_stale"]
        self.sql("UPDATE ads_ad SET name='第二次改名' WHERE id=%s", self.ad)
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        body = {"change_set_id": stale["change_set_id"], "content_hash": stale["content_hash"]}
        for route in ("reapprove", "revert"):
            with patch.object(
                change_control_launch.month_budget, "preflight", return_value={"can_increase": 1}
            ):
                response = client.post(f"{self.base}/launch/{route}", json=body)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.change_set(set_id)["status"], "approved")
        self.assertEqual(
            campaigns.get_ad(self.conn, self.org, self.brand, self.ad)["name"], "第二次改名"
        )
        fresh = self.workspace()["launch_stale"]
        self.assertNotEqual(fresh["content_hash"], stale["content_hash"])
        response = client.post(
            f"{self.base}/launch/revert",
            json={"change_set_id": fresh["change_set_id"], "content_hash": fresh["content_hash"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["launch_stale"])

    def assigned_material(self, ad_id=None):
        """Assign a confirmed material (revision 1) to a planned ad (the fixture's by default)."""
        asset = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) "
            "VALUES(%s,%s,%s,%s,%s,'fall.png','image/png',1,'ready')",
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
        self.sql(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            placement["id"],
        )
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, ad_id or self.ad, placement["id"], 1
        )
        return placement

    def revise(self, placement):
        """Revise the approved material after the launch; the new revision is confirmed."""
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
        self.sql(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' "
            "WHERE id=%s AND is_current",
            placement["id"],
        )
        return self.conn.execute(
            "SELECT revision FROM ads_asset_placement WHERE id=%s AND is_current",
            (placement["id"],),
        ).fetchone()["revision"]

    def assign(self, placement_id, revision):
        return handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, placement_id, revision
        )

    def test_revert_refuses_when_the_approved_material_revision_is_gone(self):
        placement = self.assigned_material()
        set_id = self.launch()
        self.revise(placement)

        stale = self.workspace()["launch_stale"]
        row = next(r for r in stale["diff"] if r["field"] == "material")
        self.assertEqual((row["kind"], row["field_label"]), ("ad", "素材"))
        self.assertEqual(row["before"], "fall.png・第 1 版")
        self.assertFalse(stale["revertible"])
        self.assertIn("素材版本已修訂或不存在", stale["revert_blocker"])
        with self.assertRaisesRegex(ValueError, "素材版本已修訂或不存在"):
            self.revert(stale)
        self.assertEqual(self.change_set(set_id)["status"], "approved")

    def test_fresh_approved_launch_still_freezes_its_materials(self):
        placement = self.assigned_material()
        self.launch()
        self.assertIsNone(self.workspace()["launch_stale"])
        with self.assertRaisesRegex(ValueError, "首次投放清單已核准"):
            self.assign(None, None)
        with self.assertRaisesRegex(ValueError, "首次投放清單已核准"):
            self.assign(placement["id"], 1)
        ad = campaigns.get_ad(self.conn, self.org, self.brand, self.ad)
        self.assertEqual(
            (ad["material_placement_id"], ad["material_placement_revision"]), (placement["id"], 1)
        )

    def test_revised_material_is_repointed_then_reapproved(self):
        placement = self.assigned_material()
        old_set = self.launch()
        revision = self.revise(placement)
        self.assertEqual(revision, 2)
        stale = self.workspace()["launch_stale"]
        self.assertFalse(stale["revertible"])
        # An ad an approved version already handed off never leaves the batch (F30 Unresolved 1
        # defers only never-approved ads): its revised material shows in the diff ...
        row = next(r for r in stale["diff"] if r["field"] == "material")
        self.assertEqual(row["before"], "fall.png・第 1 版")
        self.assertIn("需重新指派素材", row["after"])
        # ... and re-approving the revised-but-unassigned material is refused as before ...
        with (
            patch.object(
                change_control_launch.month_budget,
                "preflight",
                return_value={"can_increase": True},
            ),
            self.assertRaisesRegex(ValueError, "尚未確認或已修訂"),
        ):
            self.reapprove(stale)
        # ... but the stale launch no longer freezes the assignment, so it can be re-pointed.
        planned = self.assign(placement["id"], revision)["planned_ads"][0]
        self.assertEqual(
            (planned["placement_revision"], planned["assignment_status"]), (revision, "confirmed")
        )
        stale = self.workspace()["launch_stale"]
        row = next(r for r in stale["diff"] if r["field"] == "material")
        self.assertEqual((row["before"], row["after"]), ("fall.png・第 1 版", "fall.png・第 2 版"))
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            new_set = self.reapprove(stale)["change_set_id"]
        self.assertEqual(self.change_set(old_set)["status"], "superseded")
        self.assertIsNone(self.workspace()["launch_stale"])
        ad_item = self.items()["ad"]
        self.assertEqual(ad_item["change_set_id"], new_set)
        self.assertEqual((ad_item["placement_revision"], ad_item["status"]), (revision, "pending"))
        # The new approval freezes the materials again.
        with self.assertRaisesRegex(ValueError, "首次投放清單已核准"):
            self.assign(None, None)

    def test_a_never_approved_ad_with_a_revised_material_waits_outside_the_batch(self):
        self.assigned_material()
        extra = db.new_id("ada")
        self.sql(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,'第二則廣告')",
            extra,
            self.org,
            self.brand,
            self.campaign,
            self.group,
        )
        self.revise(self.assigned_material(extra))
        deferred = []
        frozen = change_control_launch.snapshot(
            self.conn, self.org, self.brand, self.campaign, deferred=deferred
        )
        self.assertEqual([d["ad_id"] for d in deferred], [extra])
        self.assertEqual([a["id"] for a in frozen["groups"][0]["ads"]], [self.ad])
        # The approval goes ahead without it; the ad is not in the handed-off batch.
        self.launch()
        self.assertEqual(set(self.items()), {"campaign", "group", "ad"})
        self.assertEqual(self.items()["ad"]["planned_id"], self.ad)
        self.assertIsNone(self.workspace()["launch_stale"])

    def test_added_ad_is_listed_and_blocks_revert(self):
        self.launch()
        extra = db.new_id("ada")
        self.sql(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,'新加的廣告')",
            extra,
            self.org,
            self.brand,
            self.campaign,
            self.group,
        )
        # Without material it stays out of the batch: the approved launch is still current.
        self.assertIsNone(self.workspace()["launch_stale"])
        # A deferred ad is not frozen by the approval: it takes its material, and the launch goes
        # stale so the next version can take it out (F30 Unresolved 1).
        self.assertFalse(
            change_control_launch.material_frozen(
                self.conn, self.org, self.brand, self.campaign, extra
            )
        )
        self.assertTrue(
            change_control_launch.material_frozen(
                self.conn, self.org, self.brand, self.campaign, self.ad
            )
        )
        self.assigned_material(extra)
        stale = self.workspace()["launch_stale"]
        row = stale["diff"][0]
        self.assertEqual(
            (row["kind"], row["item_id"], row["field"], row["before"], row["after"]),
            ("ad", None, "presence", None, "新加的廣告"),
        )
        self.assertEqual(stale["unchanged_count"], 3)
        self.assertFalse(stale["revertible"])
        with self.assertRaisesRegex(ValueError, "新增或移除"):
            self.revert(stale)

    def test_set_that_is_not_stale_refuses_both_routes(self):
        set_id = self.launch()
        self.assertIsNone(self.workspace()["launch_stale"])
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        body = {"change_set_id": set_id, "content_hash": change_control_data.digest(frozen)}
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        for route in ("reapprove", "revert"):
            with patch.object(
                change_control_launch.month_budget, "preflight", return_value={"can_increase": 1}
            ):
                response = client.post(f"{self.base}/launch/{route}", json=body)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("沒有改變", response.text)
        self.assertEqual(self.change_set(set_id)["status"], "approved")
        # No approved launch at all: nothing to report either.
        other = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {"name": "未核准", "goal_text": "x", "objective": "awareness"},
            created_by="test",
        )["id"]
        self.assertIsNone(
            handoff_data.workspace(self.conn, self.org, self.brand, other)["launch_stale"]
        )


if __name__ == "__main__":
    unittest.main()
