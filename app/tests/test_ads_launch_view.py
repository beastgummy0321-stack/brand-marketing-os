"""F30 Contract G: one launch view and the batch readback, unreport and per-field confirm. The
launch batch holds only ads whose material is ready; the rest wait in the plan for a later
version. Every platform read is faked; nothing here (or in the code under test) writes to a
platform."""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import (
    change_control_data,
    change_control_launch,
    channels,
    external_sync,
    handoff_assignment,
    handoff_check,
    handoff_data,
    launch_view,
    month_budget,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.ads.adapters.external import SourcePage
from app.brand_intelligence import repository as brands
from app.core import db, settings, vocab


class LaunchViewTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="上架檢視品牌", actor="test", client_name=None
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        # Platform objects belong to one campaign across the shared test database: every test
        # reads its own account.
        self.account = db.new_id("account")
        self.campaign = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "秋季預購",
                "goal_text": "賣出秋季禮盒",
                "objective": "awareness",
                "start_date": self.today,
                "end_date": self.today + timedelta(days=7),
            },
            created_by="test",
        )["id"]
        self.group, self.ad, self.waiting = db.new_id("adg"), db.new_id("ada"), db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture','新客',300,'new')",
            (self.group, self.org, self.brand, self.campaign),
        )
        for ad_id, name in ((self.ad, "禮盒主圖"), (self.waiting, "禮盒影片")):
            self.conn.execute(
                "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (ad_id, self.org, self.brand, self.campaign, self.group, name),
            )
        self.conn.commit()
        self.assign(self.ad)

        # The platform as the fake reader shows it: one campaign, its ad set, one ad.
        self.campaigns = [self.node("C1", "campaign", "秋季預購", objective="awareness")]
        self.structure = [
            self.node(
                "G1",
                "adset",
                "新客",
                parent_native_kind="campaign",
                parent_native_id="C1",
                budget_type="daily",
                budget_amount=300,
            ),
            self.node(
                "A1",
                "ad",
                "禮盒主圖",
                parent_native_kind="adset",
                parent_native_id="G1",
                creative={
                    "kind": "image",
                    "fields": {"title": "標題", "body": "文案", "description": "說明"},
                },
            ),
        ]
        self.reads = []
        outer = self

        class Reader:
            def accounts(self, conn, org, brand):
                return [{"account_id": outer.account}]

            def binding_kinds(self):
                return ("ad",)

            def list_existing(self, conn, org, brand, account, *, cursor=None, **kwargs):
                # Two pages: the matcher must follow the cursor.
                outer.reads.append(("list", cursor))
                items = copy.deepcopy(outer.campaigns)
                if cursor is None:
                    return SourcePage(items[:1], {"after": "2"})
                return SourcePage(items[1:])

            def read_structure(self, conn, org, brand, account, *, native_id, cursor=None, **kw):
                outer.reads.append(("structure", native_id))
                return SourcePage(copy.deepcopy(outer.structure))

            def verify_native(self, conn, org, brand, account, **kwargs):
                every = {n["native_id"]: n for n in [*outer.campaigns, *outer.structure]}
                node = copy.deepcopy(every[kwargs["native_id"]])
                parents = []
                parent = node.get("parent_native_id")
                while parent is not None:
                    parents.append(copy.deepcopy(every[parent]))
                    parent = every[parent].get("parent_native_id")
                return {"entity": node, "parents": parents, "timezone_name": "Asia/Taipei"}

        reader = Reader()
        patch.object(channels, "external_reader", return_value=reader).start()
        patch.object(
            external_sync, "account_reader", return_value=(reader, {"account_id": self.account})
        ).start()
        self.addCleanup(patch.stopall)
        self.client = TestClient(__import__("app.main", fromlist=["app"]).app)
        self.base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/launch"

    def node(self, native_id, kind, name, **extra):
        return {
            "platform": "fixture",
            "source_account": self.account,
            "native_kind": kind,
            "native_id": f"{self.account}-{native_id}",
            "name": name,
            "parent_native_kind": extra.pop("parent_native_kind", None),
            "parent_native_id": (
                f"{self.account}-{extra.pop('parent_native_id')}"
                if "parent_native_id" in extra
                else None
            ),
            "native_status": "ACTIVE",
            "currency": "TWD",
            "start_date": self.today,
            "end_date": self.today + timedelta(days=7),
            "last_success_at": db.now_utc(),
            **extra,
        }

    # -- helpers ---------------------------------------------------------------------------------

    def assign(self, ad_id):
        asset = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) "
            "VALUES(%s,%s,%s,%s,%s,'gift.png','image/png',1,'ready')",
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
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, ad_id, placement["id"], 1
        )

    def approve(self):
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            return change_control_launch.publish(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "human",
                db.new_id("op"),
                change_control_data.digest(frozen),
            )["change_set_id"]

    def view(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def items(self, view=None):
        return {i["name"]: i for i in (view or self.view())["items"]}

    def report_all(self):
        for item in self.view()["items"]:
            handoff_data.report(self.conn, self.org, self.brand, self.campaign, item["id"])

    def readback(self):
        response = self.client.post(self.base + "/readback")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, **body):
        return self.client.post(self.base + path, json=body or None)

    # -- tests -----------------------------------------------------------------------------------

    def test_before_approval_the_list_holds_only_ads_with_ready_material(self):
        view = self.view()
        self.assertEqual(view["step"], "list")
        self.assertIsNone(view["version"])
        self.assertEqual(
            [(i["kind"], i["name"], i["state"]) for i in view["items"]],
            [
                ("campaign", "秋季預購", "todo"),
                ("group", "新客", "todo"),
                ("ad", "禮盒主圖", "todo"),
            ],
        )
        self.assertEqual(
            view["deferred_ads"],
            [{"ad_id": self.waiting, "name": "禮盒影片", "group_name": "新客"}],
        )
        summary = view["summary"]
        self.assertEqual(
            {k: summary[k] for k in ("campaigns", "groups", "ads", "daily_total", "cap")},
            {"campaigns": 1, "groups": 1, "ads": 1, "daily_total": 300.0, "cap": None},
        )
        self.assertEqual((summary["slots_ready"], summary["slots_total"]), (1, 2))
        ad = self.items(view)["禮盒主圖"]
        fields = {f["key"]: f["value"] for f in ad["fields"]}
        self.assertEqual(fields["group"], "新客")
        self.assertEqual(fields["material"], "gift.png・第 1 版")
        self.assertEqual(fields["copy.body"], "文案")
        # One vocabulary with the readback's mismatch/unreadable keys. F46 Contract F: 「格式」
        # after 「素材」 -- the uploaded PNG is a single image (the ad has no planned format).
        self.assertEqual(
            list(fields),
            ["name", "group", "material", "format", "copy.title", "copy.body", "copy.description"],
        )
        self.assertEqual(fields["format"], "single_image")
        group = {f["key"]: f["value"] for f in self.items(view)["新客"]["fields"]}
        # F36-I07 Contract V: the audience hint sits after the date rows; the fixture ads carry
        # no audience key and the brief has no audience text, so the group's role and its fixed
        # exclusion sentence (F38) are the hint.
        self.assertEqual(
            list(group), ["name", "budget_amount", "start_date", "end_date", "audience_hint"]
        )
        self.assertEqual(group["budget_amount"], 300.0)
        self.assertEqual(group["audience_hint"], "新客・排除：已購買者")
        self.assertEqual(ad["parent_name"], "新客")
        self.assertIsNone(view["settings_readback"])

    # -- F36-I07 Contract V: the plan's audience as a read-only hint on the group row ------------

    def seed_audience(self, key, label):
        self.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'audience',%s,%s)",
            (db.new_id("crd"), self.org, self.brand, key, label),
        )

    def add_group(self, name, role, ads):
        """A second group of `role` with `ads` = [(name, audience_key)] in plan order."""
        group = db.new_id("adg")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture',%s,200,%s)",
            (group, self.org, self.brand, self.campaign, name, role),
        )
        ids = []
        for ad_name, audience_key in ads:
            ids.append(db.new_id("ada"))
            self.conn.execute(
                "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name,audience_key) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (ids[-1], self.org, self.brand, self.campaign, group, ad_name, audience_key),
            )
        self.conn.commit()
        return group, ids

    def hint_rows(self, item):
        return [(f["label"], f["value"]) for f in item["fields"] if f["key"] == "audience_hint"]

    def test_the_group_row_shows_the_plans_role_and_audience_labels_read_only(self):
        self.seed_audience("warm_engaged", "互動過的人")
        self.seed_audience("customer_repeat", "回購客")
        group, (first, second, third) = self.add_group(
            "再行銷",
            "retarget",
            [
                ("回購主圖", "warm_engaged"),
                ("回購影片", "customer_repeat"),
                ("回購輪播", "warm_engaged"),  # a repeated key is listed once
            ],
        )
        self.assign(first)

        view = self.view()
        item = self.items(view)["再行銷"]
        self.assertEqual(
            self.hint_rows(item),
            [("受眾提示", "再行銷・互動過的人、回購客・只投：互動過或買過的人")],
        )
        keys = [f["key"] for f in item["fields"]]
        self.assertEqual(keys.index("audience_hint"), keys.index("end_date") + 1)
        # Deferred ads still belong to the plan: the hint reads the plan, not the batch.
        self.assertEqual({d["ad_id"] for d in view["deferred_ads"]}, {self.waiting, second, third})

        # The approval freezes platform-shaped fields only: the hint is computed at view time and
        # never written into the item's expected values, so readback compares what it always did.
        self.approve()
        view = self.view()
        self.assertEqual(
            self.hint_rows(self.items(view)["再行銷"]),
            [("受眾提示", "再行銷・互動過的人、回購客・只投：互動過或買過的人")],
        )
        frozen = launch_view.launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        self.assertNotIn("role", frozen["plan_json"]["launch_snapshot"]["groups"][0])
        expected = self.conn.execute(
            "SELECT expected_json FROM ads_handoff_item WHERE campaign_id=%s AND planned_id=%s",
            (self.campaign, group),
        ).fetchone()["expected_json"]
        self.assertNotIn("audience_hint", expected)
        self.assertNotIn("受眾", str(expected))

    def test_an_audience_key_without_a_vocabulary_row_prints_itself(self):
        self.seed_audience("warm_engaged", "互動過的人")
        self.add_group(
            "探索", "explore", [("冷受眾", "cold_lookalike"), ("暖受眾", "warm_engaged")]
        )
        self.assertEqual(
            self.hint_rows(self.items()["探索"]),
            [("受眾提示", "探索・cold_lookalike、互動過的人・排除：已購買者")],
        )

    # -- F38 (decision 3): the brief's own audience text and the role's exclusion sentence -------

    def set_brief_audience(self, text):
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json || jsonb_build_object("
            "'audience_hint', %s::text) WHERE id = %s",
            (text, self.campaign),
        )
        self.conn.commit()

    def test_the_hint_carries_the_briefs_audience_and_the_roles_exclusion(self):
        self.seed_audience("warm_engaged", "互動過的人")
        self.add_group("再行銷", "retarget", [("回購主圖", "warm_engaged")])
        self.set_brief_audience("  25–40 歲上班族 ")

        items = self.items()
        self.assertEqual(
            self.hint_rows(items["再行銷"]),
            [("受眾提示", "再行銷・互動過的人・簡報受眾：25–40 歲上班族・只投：互動過或買過的人")],
        )
        # The fixture's `new` group has no audience keys: role, brief, exclusion.
        self.assertEqual(
            self.hint_rows(items["新客"]),
            [("受眾提示", "新客・簡報受眾：25–40 歲上班族・排除：已購買者")],
        )

    def test_a_new_group_without_a_brief_hint_prints_role_and_exclusion(self):
        self.seed_audience("cold_broad", "廣泛新客")
        self.add_group("新客二", "new", [("新客主圖", "cold_broad")])
        self.assertEqual(
            self.hint_rows(self.items()["新客二"]), [("受眾提示", "新客・廣泛新客・排除：已購買者")]
        )

    def test_an_empty_or_blank_brief_hint_adds_no_part(self):
        for text in ("", "   "):
            with self.subTest(text=text):
                self.set_brief_audience(text)
                self.assertEqual(
                    self.hint_rows(self.items()["新客"]), [("受眾提示", "新客・排除：已購買者")]
                )

    def test_a_group_with_neither_role_nor_audience_keys_has_no_hint_row(self):
        # `role` is NOT NULL in the table, so the helper is the seam that can be shown empty.
        detail = {
            "groups": [
                {"id": "g_bare", "role": None, "ads": [{"audience_key": None}, {}]},
                {"id": "g_keys", "role": None, "ads": [{"audience_key": "warm_engaged"}]},
            ]
        }
        self.assertEqual(
            launch_view.audience_hints(self.conn, self.org, self.brand, detail),
            {"g_keys": "warm_engaged"},
        )
        hints = launch_view.audience_hints(self.conn, self.org, self.brand, detail)
        node = {"id": "g_bare", "name": "無角色", "daily_budget": 100}
        fields = launch_view._fields("group", node, None, {"groups": [node]}, hints)
        self.assertNotIn("audience_hint", [f["key"] for f in fields])

    # -- F46 Contract F: the actual format row; F46 Contract A: the customer group in the hint ----

    def seed_format(self, key, label):
        self.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'format',%s,%s)",
            (db.new_id("crd"), self.org, self.brand, key, label),
        )
        self.conn.commit()

    def plan_format(self, ad_id, key):
        self.conn.execute("UPDATE ads_ad SET format_key=%s WHERE id=%s", (key, ad_id))
        self.conn.commit()

    def format_rows(self, item):
        return [(f["label"], f["value"]) for f in item["fields"] if f["key"] == "format"]

    def test_the_format_row_says_what_ships_and_what_was_planned_when_they_differ(self):
        self.seed_format("carousel", "輪播")
        self.seed_format("single_image", "單圖")
        self.plan_format(self.ad, "carousel")
        self.assertEqual(
            self.format_rows(self.items()["禮盒主圖"]), [("格式", "單圖（規劃是輪播）")]
        )
        self.plan_format(self.ad, "single_image")
        self.assertEqual(self.format_rows(self.items()["禮盒主圖"]), [("格式", "單圖")])

        # View-time only: the approval never freezes it, and changing the plan afterwards does
        # not make the approved list stale.
        self.approve()
        self.plan_format(self.ad, "carousel")
        view = self.view()
        self.assertEqual(view["step"], "platform")
        self.assertEqual(
            self.format_rows(self.items(view)["禮盒主圖"]), [("格式", "單圖（規劃是輪播）")]
        )
        expected = self.conn.execute(
            "SELECT expected_json FROM ads_handoff_item WHERE campaign_id=%s AND planned_id=%s",
            (self.campaign, self.ad),
        ).fetchone()["expected_json"]
        self.assertNotIn("format", expected)
        frozen = launch_view.launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        self.assertNotIn("輪播", str(frozen["plan_json"]["launch_snapshot"]))

    def test_an_ad_without_material_shows_its_planned_format(self):
        self.seed_format("video", "影片")
        node = {"id": "ad_plan", "name": "影片", "material_assignment": None}
        rows = launch_view.formats(
            self.conn, self.org, self.brand, self.campaign,
            {"groups": [{"ads": [node]}]},
            {"groups": [{"ads": [{"id": "ad_plan", "format_key": "video"}]}]},
        )
        self.assertEqual(rows, {"ad_plan": "影片"})
        fields = launch_view._fields("ad", node, "新客", {}, None, rows)
        self.assertEqual(
            [(f["key"], f["value"]) for f in fields][2:4],
            [("material", None), ("format", "影片")],
        )

    def test_the_hint_names_the_customer_group_when_the_groups_ads_share_one(self):
        product = brands.create_product(self.conn, self.brand, name="禮盒", actor="test")["id"]
        way = brands.save_sell_way(
            self.conn, self.brand, name="單盒", actor="test", product_id=product,
            economics={"selling_price": 500},
        )["id"]
        campaigns.update_campaign(
            self.conn, self.org, self.brand, self.campaign, {"product_ids": [way]}
        )
        self.conn.commit()
        group_row = brands.save_customer_groups(
            self.conn, self.brand, product,
            [{"who": "送禮的上班族", "pain_keys": [vocab.PAIN_KEYS[0]]}], actor="test",
        )[0]
        self.conn.execute(
            "UPDATE ads_ad SET customer_group_id=%s WHERE group_id=%s",
            (group_row["id"], self.group),
        )
        self.conn.commit()
        self.assertEqual(
            self.hint_rows(self.items()["新客"]),
            [("受眾提示", "新客・顧客群：送禮的上班族・排除：已購買者")],
        )
        # A group whose ads carry two customer groups, or a deleted one, names none.
        self.conn.execute(
            "UPDATE ads_ad SET customer_group_id='cgp_gone' WHERE id=%s", (self.waiting,)
        )
        self.conn.commit()
        self.assertEqual(
            self.hint_rows(self.items()["新客"]), [("受眾提示", "新客・排除：已購買者")]
        )
        self.conn.execute(
            "UPDATE ads_ad SET customer_group_id='cgp_gone' WHERE group_id=%s", (self.group,)
        )
        self.conn.commit()
        self.assertEqual(
            self.hint_rows(self.items()["新客"]), [("受眾提示", "新客・排除：已購買者")]
        )

    def test_the_manual_checklist_lists_only_the_ads_the_snapshot_carries(self):
        response = self.client.get(self.base.removesuffix("/launch") + "/publish")
        self.assertEqual(response.status_code, 200, response.text)
        ads = [n["id"] for n in response.json()["describe"]["checklist"] if n["level"] == "ad"]
        self.assertEqual(ads, [self.ad])

    def test_a_deferred_ad_takes_its_material_and_goes_out_with_the_next_version(self):
        self.approve()
        view = self.view()
        self.assertEqual((view["step"], view["version"]), ("platform", 1))
        self.assertIsNotNone(view["approved_at"])
        self.assertEqual(len(view["items"]), 3)
        self.assertEqual([d["ad_id"] for d in view["deferred_ads"]], [self.waiting])
        # The approval froze the ready ad only: the deferred one may still take its material.
        with self.assertRaisesRegex(ValueError, "首次投放清單已核准"):
            handoff_assignment.assign(
                self.conn, self.org, self.brand, self.campaign, self.ad, None, None
            )
        self.assign(self.waiting)
        stale = handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)[
            "launch_stale"
        ]
        self.assertEqual(
            [(d["field"], d["after"]) for d in stale["diff"]], [("presence", "禮盒影片")]
        )
        view = self.view()
        self.assertEqual(view["step"], "stale")
        self.assertEqual(view["deferred_ads"], [])
        self.assertEqual({i["state"] for i in view["items"]}, {"todo"})
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            change_control_launch.reapprove(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                stale["change_set_id"],
                stale["content_hash"],
                "human",
            )
        view = self.view()
        self.assertEqual((view["step"], view["version"]), ("platform", 2))
        # Parents first; the two ads keep the plan's order (same insert time here, so either).
        names = [i["name"] for i in view["items"]]
        self.assertEqual(names[:2], ["秋季預購", "新客"])
        self.assertEqual(sorted(names[2:]), sorted(["禮盒主圖", "禮盒影片"]))
        self.assertEqual(view["summary"]["ads"], 2)

    def test_readback_matches_by_exact_name_and_confirm_reaches_verified(self):
        self.approve()
        self.report_all()
        self.assertEqual({i["state"] for i in self.view()["items"]}, {"built"})
        view = self.readback()
        self.assertEqual(view["step"], "verify")
        self.assertIsNotNone(view["read_at"])
        # The campaign list was read across both pages, the structure once for the whole batch.
        self.assertEqual(
            self.reads,
            [("list", None), ("list", {"after": "2"}), ("structure", f"{self.account}-C1")],
        )
        items = self.items(view)
        self.assertEqual(items["秋季預購"]["state"], "verified")
        group, ad = items["新客"], items["禮盒主圖"]
        self.assertEqual(group["state"], "unknown")
        self.assertEqual(
            group["unreadable"],
            [{"key": "manual_settings.landing_url", "label": "落地頁網址", "confirmed": False}],
        )
        self.assertEqual(ad["state"], "unknown")
        self.assertEqual(
            ad["unreadable"], [{"key": "material", "label": "圖片或影片版本", "confirmed": False}]
        )

        # Only a field the read could not see can be confirmed.
        refused = self.post(f"/items/{group['id']}/confirm", key="budget_amount")
        self.assertEqual(refused.status_code, 409, refused.text)
        confirmed = self.post(f"/items/{group['id']}/confirm", key="manual_settings.landing_url")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        group = self.items(confirmed.json())["新客"]
        self.assertEqual(group["state"], "verified")
        self.assertEqual(group["unreadable"][0]["confirmed"], True)
        again = self.post(f"/items/{group['id']}/confirm", key="manual_settings.landing_url")
        self.assertEqual(again.status_code, 409, again.text)

        done = self.post(f"/items/{ad['id']}/confirm", key="material").json()
        self.assertEqual({i["state"] for i in done["items"]}, {"verified"})
        # Confirming the material by eye upgrades the binding, as the check path does.
        item = handoff_data.get(self.conn, self.org, self.brand, self.campaign, ad["id"])
        self.assertEqual(item["evidence_json"]["material_evidence"], "user_verified")
        binding = self.conn.execute(
            "SELECT evidence_level FROM ads_asset_binding WHERE brand_id=%s AND valid_to IS NULL",
            (self.brand,),
        ).fetchone()
        self.assertEqual(binding["evidence_level"], "user_verified")
        launch = change_control_launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        action = self.conn.execute(
            "SELECT verification_state FROM ads_action WHERE change_set_id=%s", (launch["id"],)
        ).fetchone()
        self.assertEqual(action["verification_state"], "confirmed")

    def test_confirming_material_by_eye_stands_when_the_platform_recheck_fails(self):
        self.approve()
        self.report_all()
        ad = self.items(self.readback())["禮盒主圖"]
        before = handoff_data.get(self.conn, self.org, self.brand, self.campaign, ad["id"])
        with patch.object(
            handoff_check.asset_binding, "verify", side_effect=ValueError("read failed")
        ):
            done = self.post(f"/items/{ad['id']}/confirm", key="material")
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(self.items(done.json())["禮盒主圖"]["unreadable"][0]["confirmed"])
        item = handoff_data.get(self.conn, self.org, self.brand, self.campaign, ad["id"])
        self.assertEqual(
            item["evidence_json"].get("material_evidence"),
            before["evidence_json"].get("material_evidence"),
        )

    def test_a_mismatch_keeps_observed_values_and_a_confirmation_outlives_a_fresh_read(self):
        self.approve()
        self.report_all()
        self.structure[0]["budget_amount"] = 400
        group = self.items(self.readback())["新客"]
        self.assertEqual(group["state"], "mismatch")
        self.assertIn("budget_amount", {f["key"] for f in group["fields"]})
        self.assertEqual(
            group["mismatches"],
            [{"key": "budget_amount", "label": "每日預算", "expected": 300, "observed": 400}],
        )
        # The unreadable landing URL may be confirmed while the budget still differs.
        view = self.post(f"/items/{group['id']}/confirm", key="manual_settings.landing_url").json()
        group = self.items(view)["新客"]
        self.assertEqual(group["state"], "mismatch")
        self.assertTrue(group["unreadable"][0]["confirmed"])
        # The user fixes the budget on the platform and reads again: the confirmation stays.
        self.structure[0]["budget_amount"] = 300
        group = self.items(self.readback())["新客"]
        self.assertEqual(group["state"], "verified")
        self.assertEqual(group["mismatches"], [])
        self.assertTrue(group["unreadable"][0]["confirmed"])

    def test_missing_or_ambiguous_names_leave_the_item_built_with_a_reason(self):
        self.approve()
        self.report_all()
        self.campaigns[0]["name"] = "秋季預購 "  # a trailing space is another name
        items = self.items(self.readback())
        campaign = items["秋季預購"]
        self.assertEqual(campaign["state"], "built")
        self.assertIn("找不到", campaign["reason"])
        self.assertEqual(items["新客"]["state"], "built")
        self.assertIn("上一層還沒讀回", items["新客"]["reason"])

        self.campaigns[0]["name"] = "秋季預購"
        self.campaigns.append(self.node("C2", "campaign", "秋季預購", objective="awareness"))
        campaign = self.items(self.readback())["秋季預購"]
        self.assertEqual(campaign["state"], "built")
        self.assertIn("2 個", campaign["reason"])

        # An ad set named alike under another campaign is never taken for this one.
        self.campaigns.pop()
        self.structure.append(
            self.node(
                "G9",
                "adset",
                "新客",
                parent_native_kind="campaign",
                parent_native_id="C9",
                budget_type="daily",
                budget_amount=300,
            )
        )
        items = self.items(self.readback())
        self.assertEqual(items["秋季預購"]["state"], "verified")
        self.assertEqual(items["新客"]["state"], "unknown")

    def test_unreport_clears_a_report_until_the_item_is_verified(self):
        self.approve()
        campaign = self.items()["秋季預購"]
        handoff_data.report(self.conn, self.org, self.brand, self.campaign, campaign["id"])
        self.assertEqual(self.items()["秋季預購"]["state"], "built")
        response = self.post(f"/items/{campaign['id']}/unreport")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.items(response.json())["秋季預購"]["state"], "todo")
        # Not reported: a readback leaves it alone.
        self.assertEqual(self.items(self.readback())["秋季預購"]["state"], "todo")

        handoff_data.report(self.conn, self.org, self.brand, self.campaign, campaign["id"])
        self.assertEqual(self.items(self.readback())["秋季預購"]["state"], "verified")
        refused = self.post(f"/items/{campaign['id']}/unreport")
        self.assertEqual(refused.status_code, 409, refused.text)

    def test_a_new_ad_handoff_is_not_counted(self):
        self.approve()
        set_id, action_id = db.new_id("acs"), db.new_id("adx")
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,plan_json,created_by,status,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,'h','h','新增廣告',%s,%s,'test','approved',now())",
            (
                set_id,
                self.org,
                self.brand,
                self.campaign,
                db.new_id("op"),
                self.today.strftime("%Y-%m"),
                db.jsonb({"items": []}),
            ),
        )
        self.conn.execute(
            "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,kind,"
            "change_set_id,verification_state) "
            "VALUES(%s,%s,%s,%s,'campaign',%s,'creative',%s,'pending')",
            (action_id, self.org, self.brand, self.campaign, self.campaign, set_id),
        )
        new_item = handoff_data.insert(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            set_id,
            action_id,
            "ad",
            db.new_id("ada"),
            "新測試廣告",
            {"copy_text": "新文案"},
        )
        handoff_data.report(self.conn, self.org, self.brand, self.campaign, new_item)
        view = self.view()
        self.assertEqual(len(view["items"]), 3)
        self.assertNotIn("新測試廣告", self.items(view))
        response = self.post(f"/items/{new_item}/unreport")
        self.assertEqual(response.status_code, 409, response.text)

    def test_a_plan_edit_after_approval_makes_the_view_stale(self):
        self.approve()
        self.report_all()
        self.conn.execute(
            "UPDATE ads_delivery_group SET daily_budget=500,updated_at=now() WHERE id=%s",
            (self.group,),
        )
        self.conn.commit()
        view = self.view()
        self.assertEqual(view["step"], "stale")
        states = {i["name"]: i["state"] for i in view["items"]}
        self.assertEqual(states, {"秋季預購": "built", "新客": "changed", "禮盒主圖": "built"})
        self.assertEqual(view["summary"]["daily_total"], 300.0, "the approved batch's total")
        refused = self.client.post(self.base + "/readback")
        self.assertEqual(refused.status_code, 409, refused.text)

    def test_a_launch_with_no_ready_ad_is_refused(self):
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, None, None
        )
        view = self.view()
        self.assertEqual(view["summary"]["slots_ready"], 0)
        self.assertEqual([i["kind"] for i in view["items"]], ["campaign", "group"])
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            response = self.client.post(
                self.base.removesuffix("/launch") + "/publish",
                json={
                    "adapter": "manual",
                    "operation_id": db.new_id("op"),
                    "content_hash": change_control_data.digest(frozen),
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "launch_no_ready_ads")
        self.assertIsNone(
            change_control_launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        )

    # -- F41-I03 (drill-8 #6): the list step carries the launch's month numbers ------------------

    def month_number(self):
        return self.today.month

    def set_month_budget(self, amount):
        month = self.today.strftime("%Y-%m")
        revision = month_budget.view(self.conn, self.org, self.brand, month)["revision"]
        month_budget.save(
            self.conn, self.org, self.brand, month=month, currency="TWD", amount=amount,
            expected_revision=revision, actor="test",
        )

    def publish_for_real(self):
        """Approve through the real month preflight (the `approve` helper stubs it)."""
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        return change_control_launch.publish(
            self.conn, self.org, self.brand, self.campaign, "human", db.new_id("op"),
            change_control_data.digest(frozen),
        )

    def refused(self):
        try:
            self.publish_for_real()
        except ValueError:
            return True
        return False

    def test_the_list_step_without_a_month_budget_is_unset_and_approve_refuses(self):
        fit = self.view()["month_budget"]
        self.assertEqual(fit["month"], self.today.strftime("%Y-%m"))
        self.assertIsNone(fit["amount"])
        self.assertEqual(fit["blocker"], "unset")
        self.assertEqual(fit["blocker_text"], f"要先設 {self.month_number()} 月月預算")
        self.assertTrue(self.refused())

    def test_the_list_step_month_fit_mirrors_the_approve_preflight(self):
        month = self.today.strftime("%Y-%m")
        clean = patch.object(month_budget, "_inventory", side_effect=lambda *a: ([], [], []))
        with clean:
            # Too small: the launch's 300/day does not fit.
            self.set_month_budget(100)
            fit = self.view()["month_budget"]
            self.assertEqual(fit["blocker"], "short")
            self.assertEqual(fit["blocker_text"], f"{self.month_number()} 月預算不夠這期花")
            # The money fields are the month before this launch; `extra` on top does not fit.
            self.assertEqual(fit["available"], 100.0)
            self.assertLess(fit["available"] - fit["extra"], 0)
            self.assertEqual(fit["amount"], 100.0)
            self.assertTrue(self.refused())
        # An unverified balance: the preflight's own sentence.
        with patch.object(
            month_budget, "_inventory", side_effect=lambda *a: ([], [], ["帳戶尚未核對"])
        ):
            fit = self.view()["month_budget"]
            self.assertEqual(fit["blocker"], "uncertain")
            self.assertEqual(
                fit["blocker_text"],
                "餘額尚不確定，暫不能核准新增花費；可補資料、檢視或核准降低風險的操作。",
            )
            self.assertTrue(self.refused())
        with clean:
            # Large enough: no blocker, and `extra` is exactly what the approval reserves.
            self.set_month_budget(10_000_000)
            fit = self.view()["month_budget"]
            self.assertIsNone(fit["blocker"])
            self.assertIsNone(fit["blocker_text"])
            self.assertGreater(fit["extra"], 0)
            # The month as it stands without this launch (what `getMonthlyBudget` reads); the card
            # stacks `extra` on top.
            before = month_budget.view(self.conn, self.org, self.brand, month)
            self.assertEqual(before["reserved_increases"], 0)
            self.assertEqual(fit["reserved_increases"], 0)
            self.assertEqual(fit["available"], before["available"])
            self.assertGreaterEqual(fit["available"] - fit["extra"], 0)
            self.assertFalse(self.refused())
            after = month_budget.view(self.conn, self.org, self.brand, month)
            self.assertEqual(after["reserved_increases"], fit["extra"])
            # Approved steps carry no card.
            view = self.view()
            self.assertEqual(view["step"], "platform")
            self.assertIsNone(view["month_budget"])

    def test_the_view_refuses_another_brands_campaign(self):
        other = brands.create_brand(
            self.conn, org_id=self.org, name="別的品牌", actor="test", client_name=None
        )["id"]
        with self.assertRaises(ValueError):
            launch_view.view(self.conn, self.org, other, self.campaign)


if __name__ == "__main__":
    unittest.main()
