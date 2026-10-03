"""app/tests/test_ads_learning_flow.py — Contract D (F27-I04): a confirmed `pause` change item
that carries an `angle` writes exactly one brand learning; promoted by counting earlier
same-text `source_track="ads"` learnings of the brand; idempotent per change ITEM id, so the
automatic runtime re-check (`app/ads/runtime.py`, which calls `check` again on actions that are
already `confirmed`) never duplicates it."""

import copy
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import ads_learnings, external_sync
from app.ads import change_control as service
from app.ads import change_control_verify as verification
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings


class AdsLearningFlowTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="學習流程測試", actor="test", client_name=None
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
        self.conn.commit()
        self.month = coresettings.today_for_org(self.conn, org_id=self.org).strftime("%Y-%m")
        self._ad_seq = 2

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

    def ad(self):
        self._ad_seq += 1
        return self.entity(
            str(self._ad_seq),
            "ad",
            parent_native_kind="adset",
            parent_native_id="2",
            creative={
                "kind": "image",
                "fields": {"body": "文案", "title": "標題", "image_hash": "img"},
            },
        )

    def create_pause(self, target_id, angle=None):
        item = {
            "kind": "pause",
            "target_id": target_id,
            "after": {"status": "PAUSED"},
            "reason": "停止風險",
        }
        if angle is not None:
            item["angle"] = angle
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.month,
            "title": "暫停廣告",
            "items": [item],
        }
        created = service.create(self.conn, self.org, self.brand, self.campaign, payload, "test")
        return service.approve(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            created["id"],
            created["content_hash"],
            "test",
        )

    def confirm(self, approved, target_entity):
        ad = copy.deepcopy(target_entity)
        ad["native_status"] = "PAUSED"
        proof = {"entity": ad, "parents": [self.group, self.root]}

        class Reader:
            def verify_native(self, *args, **kwargs):
                return proof

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

    def learnings(self):
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM learning_ledger WHERE brand_id=%s AND source_track='ads' "
                "ORDER BY learned_at",
                (self.brand,),
            ).fetchall()
        ]

    def test_no_angle_writes_no_learning(self):
        ad = self.ad()
        approved = self.create_pause(ad["id"])
        checked = self.confirm(approved, ad)
        self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
        self.assertEqual(
            checked["items"][0]["learning"], {"recorded": False, "confidence": None, "count": 0}
        )
        self.assertEqual(self.learnings(), [])

    def test_first_second_third_same_angle_promote_confidence(self):
        expected = [("observed", 1), ("likely", 2), ("validated", 3)]
        for confidence, count in expected:
            ad = self.ad()
            approved = self.create_pause(ad["id"], angle="沒興趣的舊客")
            checked = self.confirm(approved, ad)
            self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
            self.assertEqual(
                checked["items"][0]["learning"],
                {"recorded": True, "confidence": confidence, "count": count},
            )
        rows = self.learnings()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["learning_text"] == "「沒興趣的舊客」對這群受眾無效" for r in rows))
        self.assertEqual([r["confidence"] for r in rows], ["observed", "likely", "validated"])
        # F48 Contract W: an imported campaign has no sell-way, so its rows are brand level.
        self.assertEqual({r["product_id"] for r in rows}, {None})

    def test_automatic_recheck_does_not_duplicate(self):
        ad = self.ad()
        approved = self.create_pause(ad["id"], angle="週末促購族")
        self.confirm(approved, ad)
        self.assertEqual(len(self.learnings()), 1)
        # `app/ads/runtime.py`'s automatic re-check calls `check` again (actor "system") on an
        # action that is already `confirmed` -- must not write a second learning row.
        again = self.confirm(approved, ad)
        self.assertEqual(again["items"][0]["verification_state"], "confirmed")
        rows = self.learnings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            again["items"][0]["learning"], {"recorded": True, "confidence": "observed", "count": 1}
        )

    def sell(self) -> str:
        """Give the campaign a sell-way (`context_json.product_ids`, `sell_way.of_campaign`)."""
        product = brands.create_product(self.conn, self.brand, name="保溫瓶單入", actor="test")
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json || %s::jsonb WHERE id = %s",
            (json.dumps({"product_ids": [product["id"]]}), self.campaign),
        )
        self.conn.commit()
        return product["id"]

    def test_pause_learning_carries_the_campaigns_sell_way(self):
        """F48 Contract W: the confirmed pause's learning is stored with the campaign's sell-way."""
        product_id = self.sell()
        ad = self.ad()
        self.confirm(self.create_pause(ad["id"], angle="早鳥族"), ad)
        rows = self.learnings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["product_id"], product_id)

    def test_ab_learning_carries_the_campaigns_sell_way(self):
        product_id = self.sell()
        ab = {"dimension_label": "開場", "winner": {"value_label": "甲"},
              "loser": {"value_label": "乙"}}
        row = ads_learnings.record_for_ab_item(
            self.conn, self.org, self.brand, self.campaign,
            {"plan_json": {"source": "ab", "ab": ab}}, {"id": "adx-ab", "kind": "pause"},
        )
        assert row is not None
        self.assertEqual(row["product_id"], product_id)
        self.assertEqual([r["product_id"] for r in self.learnings()], [product_id])

    def test_record_for_item_is_a_noop_off_pause_or_without_angle(self):
        self.assertIsNone(
            ads_learnings.record_for_item(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "set",
                {"id": "adx-x", "kind": "copy", "angle": "無關"},
            )
        )
        self.assertIsNone(
            ads_learnings.record_for_item(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                "set",
                {"id": "adx-y", "kind": "pause", "angle": None},
            )
        )
        self.assertEqual(self.learnings(), [])

    def test_record_for_ab_item_is_a_noop_outside_an_ab_pause(self):
        """F29-I04 Contract F: only the pause item of a `source: "ab"` set writes the A/B text."""
        ab = {"dimension_label": "開場", "winner": {"value_label": "甲"},
              "loser": {"value_label": "乙"}}
        pause = {"id": "adx-p", "kind": "pause"}
        for change_set, item in (
            ({"plan_json": {"source": "cleanup", "ab": ab}}, pause),
            ({"plan_json": {"source": "ab"}}, pause),
            ({"plan_json": {"source": "ab", "ab": ab}}, {"id": "adx-c", "kind": "copy"}),
        ):
            self.assertIsNone(ads_learnings.record_for_ab_item(
                self.conn, self.org, self.brand, self.campaign, change_set, item,
            ))
        self.assertEqual(self.learnings(), [])
        self.assertEqual(ads_learnings.ab_text(ab), "「開場」用「甲」比「乙」划算")

    def test_learnings_endpoint_lists_newest_first_with_campaign(self):
        from app.main import app

        ad_a = self.ad()
        approved_a = self.create_pause(ad_a["id"], angle="早鳥族")
        self.confirm(approved_a, ad_a)
        ad_b = self.ad()
        approved_b = self.create_pause(ad_b["id"], angle="晚鳥族")
        self.confirm(approved_b, ad_b)

        response = TestClient(app).get(f"/api/ads/brands/{self.brand}/learnings")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()["learnings"]
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["text"], "「晚鳥族」對這群受眾無效")
        self.assertEqual(body[1]["text"], "「早鳥族」對這群受眾無效")
        for row in body:
            self.assertEqual(row["campaign_id"], self.campaign)
            self.assertIsNotNone(row["campaign_name"])
            self.assertEqual(row["confidence"], "observed")
            self.assertEqual(row["count"], 1)
            # F27-I27: same `repository.campaign_objective_family` rule the month summary and
            # `CampaignChip` elsewhere already use -- this fixture's root entity is platform
            # "fake" (never "meta"), so the family always falls back to "other", never a guess.
            self.assertEqual(row["campaign_objective"], "other")

    def test_settle_learning_lists_its_ads_campaign(self):
        # F29-I03: a period-settle learning names its ad entity (`settle:<month>:<entity_id>`),
        # not a change item -- its campaign comes from that entity. An unknown entity stays null.
        ad = self.ad()
        for source in (f"settle:2026-08:{ad['id']}", "settle:2026-08:ent_gone"):
            brands.record_learning(
                self.conn, self.brand, actor="user_1", learning_text="「早鳥族」對這群受眾有效",
                applicability_scope=f"ads;campaign={self.campaign}", confidence="observed",
                sample_size="12", source_cycle_id=source, source_track="ads",
            )
        rows = {row["id"]: row for row in ads_learnings.list_for_brand(self.conn, self.brand)}
        by_source = {
            learning["source_cycle_id"]: rows[learning["id"]]
            for learning in brands.list_learnings(self.conn, self.brand, source_track="ads")
        }
        known = by_source[f"settle:2026-08:{ad['id']}"]
        self.assertEqual((known["campaign_id"], known["campaign_name"]),
                         (self.campaign, "持續活動"))
        self.assertIsNone(by_source["settle:2026-08:ent_gone"]["campaign_id"])


if __name__ == "__main__":
    unittest.main()
