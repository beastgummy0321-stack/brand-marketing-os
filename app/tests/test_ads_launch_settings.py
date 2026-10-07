"""F29 Contract I: launch settings are choice fields with program-recommended values, frozen into
the launch approval, and read back against a Meta READ. Every platform call is faked; nothing here
(or in the code under test) writes to a platform."""

import copy
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.ads import (
    change_control_data,
    change_control_launch,
    external_sync,
    handoff_assignment,
    handoff_check,
    handoff_data,
    launch_settings,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as assets
from app.ads.adapters import meta_read
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.meta import repository as meta_repo


class LaunchSettingsTest(unittest.TestCase):
    def setUp(self):
        # Platform objects are owned by one campaign across the shared test database: every test
        # reads its own account.
        self.account = str(uuid.uuid4().int % 10**12)
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="投放設定品牌", actor="test", client_name=None
        )["id"]
        self.today = settings.today_for_org(self.conn, org_id=self.org)
        self.campaign = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "秋季預購",
                "goal_text": "賣出秋季禮盒",
                "objective": "購買",
                "start_date": self.today,
                "end_date": self.today + timedelta(days=7),
            },
            created_by="test",
        )["id"]
        self.group, self.ad = db.new_id("adg"), db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'meta','新客',300,'new')",
            (self.group, self.org, self.brand, self.campaign),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,'禮盒主圖')",
            (self.ad, self.org, self.brand, self.campaign, self.group),
        )
        self.conn.commit()
        self.pixels = [{"id": "px1", "name": "官網像素"}]
        self.pixel_error = None
        account = {"account_id": self.account, "currency": "TWD", "timezone_name": "Asia/Taipei"}
        outer = self

        def read_pixels(conn, org, brand, account_id):
            assert account_id == self.account
            if outer.pixel_error:
                raise meta_repo.ExternalReadError(
                    "平台無法讀取此資料（代碼 200）。", outer.pixel_error
                )
            return copy.deepcopy(outer.pixels)

        # Raw Graph shapes as the single-object reads return them (CBO campaign: the bid strategy
        # lives on the campaign, the ad set carries none).
        self.raw = {
            "campaign": {
                "id": "101",
                "account_id": self.account,
                "name": "秋季預購",
                "objective": "OUTCOME_SALES",
                "effective_status": "ACTIVE",
                "daily_budget": "300",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            },
            "adset": {
                "id": "201",
                "account_id": self.account,
                "campaign_id": "101",
                "name": "新客",
                "effective_status": "ACTIVE",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "promoted_object": {"pixel_id": "px1", "custom_event_type": "PURCHASE"},
                # Advantage+ audience: Meta answers 18-65 whatever the suggestion was.
                "targeting": {
                    "age_min": 18,
                    "age_max": 65,
                    "genders": [1, 2],
                    "geo_locations": {"countries": ["TW"], "location_types": ["home"]},
                    "targeting_automation": {"advantage_audience": 1},
                },
            },
            "ad": {
                "id": "301",
                "account_id": self.account,
                "campaign_id": "101",
                "adset_id": "201",
                "name": "禮盒主圖",
                "effective_status": "ACTIVE",
                "creative": {
                    "id": "401",
                    "body": "文案",
                    "url_tags": f"utm_source=meta&utm_medium=paid&utm_campaign={self.campaign}",
                },
            },
        }

        def read_object(conn, org, brand, account_id, kind, native_id):
            return copy.deepcopy(outer.raw[kind])

        patch.object(meta_repo, "read_external_pixels", side_effect=read_pixels).start()
        patch.object(meta_repo, "read_external_object", side_effect=read_object).start()
        patch.object(
            meta_repo, "external_bound_accounts", side_effect=lambda *a: [dict(account)]
        ).start()
        patch.object(
            external_sync, "account_reader", return_value=(meta_read.MetaReader(), account)
        ).start()
        self.addCleanup(patch.stopall)
        self.client = TestClient(main.app)
        self.base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"

    # -- helpers ---------------------------------------------------------------------------------

    def view(self):
        response = self.client.get(self.base + "/launch-settings")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def put(self, **changes):
        values = copy.deepcopy(self.view()["values"])
        for key, value in changes.items():
            if key in ("age_min", "age_max", "gender", "countries"):
                values["audience"][key] = value
            else:
                values[key] = value
        return self.client.put(self.base + "/launch-settings", json=values)

    def material(self):
        """A confirmed material on the planned ad: only such an ad is in a launch batch (F30)."""
        asset = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) "
            "VALUES(%s,%s,%s,%s,%s,'gift.png','image/png',1,'ready')",
            (asset, self.org, self.brand, asset, f"{self.org}/{asset}"),
        )
        placement = assets.attach(
            self.conn, self.org, self.brand, self.campaign, asset, {"body": "文案"}, "human"
        )
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
            (placement["id"],),
        )
        self.conn.commit()
        handoff_assignment.assign(
            self.conn, self.org, self.brand, self.campaign, self.ad, placement["id"], 1
        )

    def launch(self):
        ad = campaigns.get_ad(self.conn, self.org, self.brand, self.ad)
        if ad["material_placement_id"] is None:
            self.material()
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
            )

    def items(self):
        rows = handoff_data.workspace(self.conn, self.org, self.brand, self.campaign)["items"]
        return {r["planned_kind"]: r for r in rows}

    def check(self, kind, native_kind, native_id):
        return handoff_check.check(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            self.items()[kind]["id"],
            {
                "platform": "meta",
                "source_account": self.account,
                "native_kind": native_kind,
                "native_id": native_id,
                "user_verified": False,
            },
            "human",
        )

    def readback(self):
        response = self.client.get(self.base + "/handoff")
        self.assertEqual(response.status_code, 200, response.text)
        readback = response.json()["settings_readback"]
        return readback and {f["key"]: f for f in readback["fields"]}

    def read_all(self):
        self.launch()
        self.check("campaign", "campaign", "101")
        group = self.check("group", "adset", "201")
        ad = self.check("ad", "ad", "301")
        return group, ad

    # -- choices and recommendation --------------------------------------------------------------

    def test_f52_no_edit_settings_get_cannot_move_the_displayed_approval_hash(self):
        self.material()
        first = self.client.get(self.base + "/publish?adapter=manual")
        self.assertEqual(first.status_code, 200, first.text)
        before = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        settings_view = self.view()
        after = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(before["launch_settings"], after["launch_settings"],
                         f"no-edit snapshot component: {before['launch_settings']} -> "
                         f"{after['launch_settings']}; "
                         f"displayed settings={settings_view['values']}")
        self.assertEqual(first.json()["describe"]["content_hash"],
                         change_control_data.digest(after))
        self.assertEqual(after["launch_settings"]["pixel_id"], "px1")
        described = first.json()["describe"]
        self.assertEqual(described["launch_settings"], settings_view["values"])
        operation = db.new_id("op")
        body = {"adapter": "manual", "operation_id": operation,
                "content_hash": described["content_hash"]}
        with patch.object(change_control_launch.month_budget, "preflight",
                          return_value={"can_increase": True}) as preflight:
            approved = self.client.post(self.base + "/publish", json=body)
            repeated = self.client.post(self.base + "/publish", json=body)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(preflight.call_count, 1)
        rows = self.conn.execute(
            "SELECT id FROM ads_change_set WHERE campaign_id=%s AND operation_id=%s",
            (self.campaign, operation),
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_f52_reversed_reads_and_later_pixel_cache_do_not_change_effective_values(self):
        self.material()
        initial = self.view()["values"]
        first = self.client.get(self.base + "/publish?adapter=manual").json()["describe"]
        self.pixels = [{"id": "px2", "name": "另一個像素"}]
        later = self.view()
        self.assertEqual(later["options"]["pixels"], self.pixels)
        self.assertEqual(later["values"], initial)
        self.assertEqual(first["content_hash"], change_control_data.digest(
            change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)))
        self.assertEqual(later["errors"][0]["code"], "pixel_unknown")

    def test_f52_initial_pixel_read_preserves_a_successful_interleaved_put(self):
        values = launch_settings.recommended(self.conn, self.brand,
                    campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign), None)
        values["utm"] = "utm_source=manual&utm_medium=paid&utm_campaign=chosen"
        entered = False

        def delayed_read(*args):
            nonlocal entered
            if not entered:
                entered = True
                response = self.client.put(self.base + "/launch-settings", json=values)
                self.assertEqual(response.status_code, 200, response.text)
            return self.pixels, None

        with patch.object(launch_settings, "read_pixels", side_effect=delayed_read):
            read = self.view()
        self.assertTrue(entered)
        self.assertEqual(read["values"], values)
        stored = campaigns.get_campaign(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(stored["context_json"]["launch_settings"]["values"], values)

    def test_f52_conditional_initialization_cannot_overwrite_a_saved_put(self):
        stale = campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign)
        values = launch_settings.recommended(self.conn, self.brand, stale, None)
        values["utm"] = "utm_source=chosen&utm_campaign=keep"
        response = self.client.put(self.base + "/launch-settings", json=values)
        self.assertEqual(response.status_code, 200, response.text)
        launch_settings._initialize_values(self.conn, self.org, self.brand, stale)
        fresh = campaigns.get_campaign(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(fresh["context_json"]["launch_settings"]["values"], values)
        self.assertNotIn("initialized_values", fresh["context_json"]["launch_settings"])

    def test_f52_failed_pixel_read_keeps_unknown_and_later_cache_requires_explicit_choice(self):
        self.pixel_error = "permission_denied"
        first = self.view()
        self.assertIsNone(first["options"]["pixels"])
        self.assertIsNotNone(first["options"]["pixels_error"])
        self.assertIsNone(first["values"]["pixel_id"])
        self.pixel_error = None
        later = self.view()
        self.assertEqual(later["recommended"]["pixel_id"], "px1")
        self.assertIsNone(later["values"]["pixel_id"])
        reset = self.client.put(self.base + "/launch-settings", json=later["recommended"])
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.json()["values"], later["recommended"])

    def test_recommended_values_are_program_rules_and_preselected(self):
        view = self.view()
        self.assertEqual(
            view["recommended"],
            {
                "optimization_event": "purchase",
                "bid_strategy": "lowest_cost",
                "placement": {"mode": "auto", "positions": []},
                "audience": {"age_min": 18, "age_max": 65, "gender": "all", "countries": ["TW"]},
                "pixel_id": "px1",  # the account has exactly one pixel
                "utm": f"utm_source=meta&utm_medium=paid&utm_campaign={self.campaign}",
            },
        )
        self.assertEqual(view["values"], view["recommended"])
        self.assertEqual(view["edited"], [])
        self.assertEqual(view["errors"], [])
        options = view["options"]
        self.assertEqual(options["pixels"], self.pixels)
        self.assertIsNone(options["pixels_error"])
        self.assertEqual(
            [o["value"] for o in options["optimization_event"]],
            ["purchase", "add_to_cart", "initiate_checkout", "view_content"],
        )
        self.assertTrue(all(o["note"] for o in options["bid_strategy"]))
        # The channel's display label fills the note; no placeholder reaches the screen.
        self.assertEqual(options["bid_strategy"][0]["note"], "讓 Meta 用最少的錢買到結果")
        self.assertNotIn("{platform}", str(options))
        self.assertIn(
            {"value": "TW", "label": "台灣", "note": "整個台灣都看得到"}, options["countries"]
        )

    def test_two_pixels_preselect_none_and_an_unknown_pixel_is_an_error(self):
        self.pixels = [{"id": "px1", "name": "官網像素"}, {"id": "px2", "name": "舊官網像素"}]
        self.assertIsNone(self.view()["recommended"]["pixel_id"])
        saved = self.put(pixel_id="px9", bid_strategy="cost_cap", bid_amount=450)
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["edited"], ["bid_strategy", "bid_amount", "pixel_id"])
        self.assertEqual([e["code"] for e in body["errors"]], ["pixel_unknown"])

    def test_pixel_permission_denied_is_a_reason_never_an_empty_list(self):
        self.pixel_error = "permission_denied"
        view = self.view()
        self.assertIsNone(view["options"]["pixels"])
        self.assertIn("權限", view["options"]["pixels_error"])
        self.assertIsNone(view["values"]["pixel_id"])
        # Unreadable list: a typed pixel is checked by the platform adapter's own format rule
        # (F47-I06, drill-10 V5: 「abc」 was saved as a pixel), never against a guessed list.
        body = self.put(pixel_id="abc").json()
        self.assertEqual(body["values"]["pixel_id"], "abc")  # kept as typed, flagged
        self.assertEqual(
            body["errors"],
            [{"field": "pixel_id", "code": "pixel_format",
              "message": "Meta 的像素 ID 是 10～20 位數字，請到事件管理工具複製。"}],
        )
        self.assertEqual(self.put(pixel_id="1234567890123").json()["errors"], [])

    def test_capped_bid_needs_an_amount_and_other_strategies_clear_it(self):
        """F47-I06 (Contract A bid, drill-10 V6): 成本上限／出價上限 carry one amount > 0;
        it blocks approval while missing and is dropped for 最低成本."""
        for strategy in ("cost_cap", "bid_cap"):
            with self.subTest(strategy=strategy):
                body = self.put(bid_strategy=strategy, bid_amount=None).json()
                self.assertEqual([e["code"] for e in body["errors"]], ["bid_amount_missing"])
                self.assertEqual(
                    self.put(bid_strategy=strategy, bid_amount=-5).json()["errors"][0]["message"],
                    "出價金額要大於 0",
                )
                saved = self.put(bid_strategy=strategy, bid_amount=450.5).json()
                self.assertEqual(saved["errors"], [])
                self.assertEqual(saved["values"]["bid_amount"], 450.5)
        cleared = self.put(bid_strategy="lowest_cost", bid_amount=450).json()
        self.assertNotIn("bid_amount", cleared["values"])
        self.assertEqual(self.put(bid_amount="450").status_code, 400)  # not a number at all
        self.assertEqual(launch_settings.value_label("bid_amount", {"bid_amount": 1500}), "1,500")
        self.assertEqual(launch_settings.value_label("bid_amount", {"bid_amount": 12.5}), "12.50")
        self.assertNotIn("bid_amount", dict(launch_settings.READBACK_FIELDS))

    def test_approval_refuses_a_capped_bid_without_an_amount(self):
        self.assertEqual(self.put(bid_strategy="cost_cap").status_code, 200)
        with self.assertRaisesRegex(ValueError, "launch_settings_invalid"):
            self.launch()

    def test_approval_checks_a_hand_typed_pixel_with_the_platform_rule(self):
        """F47-I06: with no cached pixel list the approval gate applies the campaign channel's
        own pixel-id format (the same rule the card shows), so 「abc」 cannot be approved."""
        self.pixel_error = "permission_denied"  # the list was never read: nothing cached
        self.assertEqual(self.put(pixel_id="abc").status_code, 200)
        with self.assertRaisesRegex(ValueError, "launch_settings_invalid"):
            self.launch()
        self.assertEqual(self.put(pixel_id="1234567890123").status_code, 200)
        self.assertIsNotNone(self.launch())  # a well-formed id passes the same gate

    def test_utm_with_a_space_and_other_semantic_errors_are_saved_and_listed(self):
        response = self.put(
            utm="utm_source=meta&utm_campaign=秋季 預購",
            age_min=45,
            age_max=25,
            placement={"mode": "manual", "positions": []},
        )
        self.assertEqual(response.status_code, 200, response.text)
        codes = {e["field"]: e["code"] for e in response.json()["errors"]}
        self.assertEqual(
            codes,
            {
                "utm": "utm_format",
                "audience.age": "age_range",
                "placement.positions": "positions_empty",
            },
        )
        missing_source = self.put(utm="utm_medium=paid&utm_campaign=fall").json()["errors"]
        self.assertEqual(
            [e["code"] for e in missing_source if e["field"] == "utm"], ["utm_source_missing"]
        )

    def test_malformed_body_is_refused(self):
        for bad in (
            {"optimization_event": "lead"},
            {"age_min": 17},
            {"countries": ["XX"]},
            {"placement": {"mode": "manual", "positions": ["right_column"]}},
        ):
            with self.subTest(bad=bad):
                response = self.put(**bad)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "launch_settings_malformed")

    def test_moved_free_text_keys_leave_the_manual_fields_but_saved_values_stay(self):
        from app.ads import manual_settings

        keys = {f["key"] for f in manual_settings.FIELDS}
        self.assertFalse(keys & {"placements", "bidding", "optimization_event", "tracking", "utm"})
        required = {f["key"] for f in manual_settings.FIELDS if f["required"]}
        self.assertEqual(required, {"landing_url"})
        url = f"{self.base}/groups/{self.group}/manual-settings"
        saved = self.client.put(
            url, json={"values": {"placements": "動態版位", "landing_url": "https://x.test/a"}}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        record = campaigns.campaign_detail(self.conn, self.org, self.brand, self.campaign)[
            "manual_handoff"
        ]["groups"][0]
        self.assertEqual(record["values"]["placements"], "動態版位")
        self.assertEqual(record["missing"], [])

    # -- approval --------------------------------------------------------------------------------

    def test_approval_refuses_invalid_settings_with_409(self):
        self.assertEqual(self.put(utm="utm_source=meta&utm_campaign=有 空格").status_code, 200)
        with self.assertRaisesRegex(ValueError, "launch_settings_invalid"):
            self.launch()
        with patch.object(
            change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
        ):
            described = self.client.get(self.base + "/publish").json()["describe"]
            response = self.client.post(
                self.base + "/publish",
                json={
                    "adapter": "manual",
                    "operation_id": db.new_id("op"),
                    "content_hash": described["content_hash"],
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "launch_settings_invalid")
        self.assertIn("投放設定", response.json()["error"]["message"])
        self.assertIsNone(
            change_control_launch.launch_set(self.conn, self.org, self.brand, self.campaign)
        )

    def test_approval_freezes_the_recommendation_and_an_edit_makes_it_stale(self):
        self.view()  # caches the one pixel, so the recommendation preselects it
        self.launch()
        change_set = change_control_launch.launch_set(
            self.conn, self.org, self.brand, self.campaign
        )
        self.assertEqual(
            change_set["plan_json"]["launch_snapshot"]["launch_settings"]["pixel_id"], "px1"
        )
        # A second pixel appearing later changes the recommendation, not the approved launch.
        self.pixels.append({"id": "px2", "name": "第二個像素"})
        self.view()
        self.assertIsNone(
            change_control_launch.stale(self.conn, self.org, self.brand, self.campaign)
        )
        self.assertEqual(self.put(bid_strategy="cost_cap").status_code, 200)
        stale = change_control_launch.stale(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(
            [(r["field"], r["field_label"], r["before"], r["after"]) for r in stale["diff"]],
            [("launch_settings.bid_strategy", "出價方式", "最低成本", "單次成果成本上限")],
        )
        self.assertTrue(stale["revertible"])
        change_control_launch.revert(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            stale["change_set_id"],
            stale["content_hash"],
            "human",
        )
        self.assertIsNone(
            change_control_launch.stale(self.conn, self.org, self.brand, self.campaign)
        )
        self.assertEqual(self.view()["values"]["bid_strategy"], "lowest_cost")

    def test_launch_approved_before_launch_settings_is_not_stale(self):
        self.launch()
        change_set = change_control_launch.launch_set(
            self.conn, self.org, self.brand, self.campaign
        )
        plan = change_set["plan_json"]
        del plan["launch_snapshot"]["launch_settings"]
        self.conn.execute(
            "UPDATE ads_change_set SET plan_json=%s WHERE id=%s", (db.jsonb(plan), change_set["id"])
        )
        self.conn.commit()
        self.assertEqual(self.put(bid_strategy="bid_cap").status_code, 200)
        self.assertIsNone(
            change_control_launch.stale(self.conn, self.org, self.brand, self.campaign)
        )

    # -- readback ---------------------------------------------------------------------------------

    def test_readback_matches_advantage_audience_gender_all_and_cbo_bid(self):
        self.view()
        self.assertIsNone(self.readback())
        group, ad = self.read_all()
        fields = self.readback()
        self.assertEqual(
            {k: f["state"] for k, f in fields.items()},
            {
                "optimization_event": "match",
                "bid_strategy": "match",
                "placement": "match",
                "age": "match",
                "gender": "match",
                "countries": "match",
                "pixel_id": "match",
                "utm": "match",
            },
        )
        self.assertEqual(fields["age"]["observed_label"], "18–65+ 歲")
        self.assertEqual(fields["gender"]["observed_label"], "不限")
        self.assertEqual(fields["bid_strategy"]["observed_label"], "最低成本")
        self.assertEqual(fields["pixel_id"]["expected_label"], "官網像素（px1）")
        self.assertNotIn("投放設定", str(group["evidence_json"]["deviated_fields"]))

    def test_region_level_geo_differs_and_shows_the_platform_value(self):
        self.raw["adset"]["targeting"]["geo_locations"] = {
            "regions": [{"key": "3847", "name": "Taipei City", "country": "TW"}]
        }
        self.raw["adset"]["targeting"]["age_min"] = 25
        self.view()
        group, _ = self.read_all()
        self.assertEqual(group["status"], "deviated", group["evidence_json"])
        self.assertIn("投放設定：地區", group["evidence_json"]["deviated_fields"])
        fields = self.readback()
        self.assertEqual(fields["countries"]["state"], "differ")
        self.assertEqual(fields["countries"]["observed_label"], "Taipei City（區域）")
        self.assertEqual(fields["countries"]["expected_label"], "台灣")
        self.assertEqual(fields["age"]["state"], "differ")
        self.assertEqual(fields["age"]["observed_label"], "25–65+ 歲")
        action = self.conn.execute(
            "SELECT verification_state FROM ads_action WHERE campaign_id=%s AND kind='publish'",
            (self.campaign,),
        ).fetchone()
        self.assertNotEqual(action["verification_state"], "confirmed")

    def test_manual_placement_and_single_gender_are_translated(self):
        targeting = self.raw["adset"]["targeting"]
        targeting.update(
            genders=[2],
            publisher_platforms=["facebook", "instagram"],
            facebook_positions=["feed"],
            instagram_positions=["stream", "story"],
        )
        self.view()
        self.assertEqual(
            self.put(
                gender="female",
                placement={
                    "mode": "manual",
                    "positions": ["facebook_feed", "instagram_feed", "stories"],
                },
            ).status_code,
            200,
        )
        self.read_all()
        fields = self.readback()
        self.assertEqual(fields["gender"]["state"], "match")
        self.assertEqual(fields["placement"]["state"], "match", fields["placement"])
        self.assertEqual(
            fields["placement"]["observed_label"], "手動：Facebook 動態、Instagram 動態、限時動態"
        )

    def test_pixel_unreadable_can_be_self_confirmed_but_a_match_cannot(self):
        del self.raw["adset"]["promoted_object"]
        self.view()
        self.read_all()
        fields = self.readback()
        self.assertEqual(fields["pixel_id"]["state"], "unreadable")
        self.assertIn("權限", fields["pixel_id"]["reason"])
        refused = self.client.post(
            self.base + "/handoff/launch/settings-confirm", json={"key": "gender"}
        )
        self.assertEqual(refused.status_code, 409, refused.text)
        confirmed = self.client.post(
            self.base + "/handoff/launch/settings-confirm", json={"key": "pixel_id"}
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        states = {f["key"]: f["state"] for f in confirmed.json()["settings_readback"]["fields"]}
        self.assertEqual(states["pixel_id"], "self_confirmed")
        self.assertEqual(states["gender"], "match")

    def test_utm_is_read_from_each_ad_and_a_missing_one_differs(self):
        del self.raw["ad"]["creative"]["url_tags"]
        self.view()
        _, ad = self.read_all()
        self.assertIn("投放設定：UTM", ad["evidence_json"]["deviated_fields"])
        self.assertEqual(self.readback()["utm"]["observed_label"], "沒有設定")


class MetaLaunchSettingsTranslationTest(unittest.TestCase):
    """The adapter's own Meta -> shared vocabulary table, without a database."""

    def test_unreturned_fields_are_unreadable_never_guessed(self):
        observed = meta_read.launch_settings_observed({"id": "1"}, None)
        self.assertEqual({v["state"] for v in observed.values()}, {"unreadable"})
        self.assertEqual(
            launch_settings.compare_item(
                {
                    "optimization_event": "purchase",
                    "bid_strategy": "lowest_cost",
                    "placement": {"mode": "auto", "positions": []},
                    "audience": {
                        "age_min": 18,
                        "age_max": 65,
                        "gender": "all",
                        "countries": ["TW"],
                    },
                    "pixel_id": None,
                },
                observed,
            )["age"]["state"],
            "unreadable",
        )

    def test_non_conversion_goal_and_unknown_bid_differ_with_the_raw_value(self):
        observed = meta_read.launch_settings_observed(
            {"optimization_goal": "LINK_CLICKS", "bid_strategy": "LOWEST_COST_WITH_MIN_ROAS"}
        )
        result = launch_settings.compare_item(
            {"optimization_event": "purchase", "bid_strategy": "lowest_cost"}, observed
        )
        self.assertEqual(result["optimization_event"]["state"], "differ")
        self.assertEqual(result["optimization_event"]["observed_label"], "LINK_CLICKS")
        self.assertEqual(result["bid_strategy"]["observed_label"], "LOWEST_COST_WITH_MIN_ROAS")
