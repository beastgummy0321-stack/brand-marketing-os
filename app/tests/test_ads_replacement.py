"""Contract E: a new-ad handoff may name the ACTIVE ad it replaces; the set tells the UI when
to pause the old one."""

from app.ads import change_control, change_control_data, handoff_new_ad
from app.core import db
from app.tests.test_ads_handoff import HandoffTest


class ReplacementTest(HandoffTest):
    def test_create_without_replaces_entity_id_leaves_replaces_and_follow_up_none(self):
        draft = self.new_ad()
        view = change_control_data.get(self.conn, self.org, self.brand, self.campaign, draft["id"])
        self.assertIsNone(view["replaces"])
        self.assertIsNone(view["follow_up"])

    def test_create_with_replaces_entity_id_exposes_replaces_but_not_follow_up_yet(self):
        draft = self.new_ad(replace_existing=True)
        view = change_control_data.get(self.conn, self.org, self.brand, self.campaign, draft["id"])
        self.assertEqual(view["replaces"], {"entity_id": self.existing_ad_id, "name": "B"})
        self.assertIsNone(view["follow_up"])

    def test_replaces_entity_id_must_be_an_active_ad_of_the_same_campaign(self):
        # Prepare native entities without going through `new_ad()`'s own idempotent-create flow so
        # each bad target can be tried against a fresh operation_id.
        from app.ads import external_repository

        external_repository.upsert_entity(self.conn, self.org, self.brand, self.campaign, self.root)
        parent = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, self.native_group
        )
        paused = self.node("B3", "ad", parent_native_kind="adset", parent_native_id="group")
        paused["native_status"] = "PAUSED"
        saved_paused = external_repository.upsert_entity(
            self.conn, self.org, self.brand, self.campaign, paused
        )
        placement = self.placement()

        def payload(replaces_entity_id, op_suffix):
            return {
                "operation_id": db.new_id("op") + op_suffix,
                "month": self.today.strftime("%Y-%m"),
                "title": "新增 B2",
                "placement_id": placement["id"],
                "revision": 1,
                "destination_entity_id": parent["id"],
                "reason": "下一個訊息假設",
                "replaces_entity_id": replaces_entity_id,
            }

        with self.assertRaisesRegex(ValueError, "正在投放中的廣告"):
            handoff_new_ad.create(
                self.conn, self.org, self.brand, self.campaign, payload(parent["id"], "-1"), "human"
            )
        with self.assertRaisesRegex(ValueError, "正在投放中的廣告"):
            handoff_new_ad.create(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                payload(saved_paused["id"], "-2"),
                "human",
            )
        with self.assertRaisesRegex(ValueError, "不屬於此品牌活動"):
            handoff_new_ad.create(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                payload("not-a-real-id", "-3"),
                "human",
            )

    def test_follow_up_appears_once_confirmed_and_disappears_once_a_pause_set_exists(self):
        draft = self.new_ad(replace_existing=True)
        _, item = self.approve(draft)
        self.check(item, "ad", "B2", user_verified=True)
        confirmed = change_control_data.get(
            self.conn, self.org, self.brand, self.campaign, draft["id"]
        )
        self.assertEqual(
            confirmed["follow_up"], {"kind": "pause_old", "entity_id": self.existing_ad_id}
        )

        change_control.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("op"),
                "title": "暫停舊廣告",
                "month": self.today.strftime("%Y-%m"),
                "items": [
                    {
                        "kind": "pause",
                        "target_id": self.existing_ad_id,
                        "after": {"status": "PAUSED"},
                        "reason": "以新版本取代",
                    }
                ],
            },
            "human",
        )

        after_pause_proposed = change_control_data.get(
            self.conn, self.org, self.brand, self.campaign, draft["id"]
        )
        self.assertIsNone(after_pause_proposed["follow_up"])
        self.assertEqual(
            after_pause_proposed["replaces"], {"entity_id": self.existing_ad_id, "name": "B"}
        )
