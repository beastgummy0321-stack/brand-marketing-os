"""Contract B (F27-I02): dynamic-creative copy as a set of variants, and the read-time
`copy_editable` field (audit problem 2). Real dev data (campaign adc_01M2T370NSGZDS0YXWTATKCN3T)
shows most `kind: "dynamic"` ads carry `asset_feed_spec` with no `titles`/`bodies` at all (only
`promotional_metadata`) -- several tests below guard that shape stays editable-but-empty, never
an error and never a false "catalog, no text" refusal.
"""

import copy
import unittest
from datetime import timedelta
from unittest.mock import patch

from app.ads import change_control as service
from app.ads import change_control_data as data
from app.ads import change_control_verify as verification
from app.ads import external_repository as external
from app.ads import external_sync, review_rounds
from app.ads.adapters.meta_read import creative_summary
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.llm import providers


class CreativeSummaryCopyVariantsTest(unittest.TestCase):
    def test_dynamic_creative_extracts_non_empty_titles_and_bodies_in_order(self):
        raw = {
            "asset_feed_spec": {
                "titles": [
                    {"text": "標題一"}, {"text": "   "}, {"text": "標題二"}, {"not_text": 1},
                ],
                "bodies": [{"text": "內文一"}, {"text": "內文二"}],
                "promotional_metadata": {"manual_coupon_codes": ["PRIME"]},
            }
        }
        result = creative_summary(raw)
        self.assertEqual(result["kind"], "dynamic")
        self.assertEqual(
            result["fields"]["copy_variants"],
            {"titles": ["標題一", "標題二"], "bodies": ["內文一", "內文二"]},
        )

    def test_dynamic_creative_with_only_promotional_metadata_is_empty_not_error(self):
        # Real dev data: `asset_feed_spec == {"promotional_metadata": {...}}`, no titles/bodies,
        # no product_set_id -- this must parse, never raise.
        raw = {"asset_feed_spec": {"promotional_metadata": {"manual_coupon_codes": ["PRIME"]}}}
        result = creative_summary(raw)
        self.assertEqual(result["kind"], "dynamic")
        self.assertEqual(result["fields"]["copy_variants"], {"titles": [], "bodies": []})

    def test_dynamic_creative_with_only_bodies_omits_titles_key_from_source(self):
        # Real dev data: some ads' `asset_feed_spec` has `bodies` + `message_extensions`, no
        # `titles` key at all.
        raw = {"asset_feed_spec": {"bodies": [{"text": "唯一內文"}], "message_extensions": {}}}
        result = creative_summary(raw)
        self.assertEqual(
            result["fields"]["copy_variants"], {"titles": [], "bodies": ["唯一內文"]}
        )

    def test_non_dynamic_creative_has_no_copy_variants_key(self):
        result = creative_summary({"image_hash": "x"})
        self.assertEqual(result["kind"], "image")
        self.assertNotIn("copy_variants", result["fields"])


class CopyEditableTest(unittest.TestCase):
    def test_image_and_video_are_single(self):
        self.assertEqual(
            data.copy_editable({"kind": "image", "fields": {}}),
            {"ok": True, "mode": "single", "reason": None},
        )
        self.assertEqual(
            data.copy_editable({"kind": "video", "fields": {}}),
            {"ok": True, "mode": "single", "reason": None},
        )

    def test_dynamic_with_variant_text_is_editable(self):
        creative = {
            "kind": "dynamic",
            "fields": {"copy_variants": {"titles": ["a"], "bodies": []}},
        }
        self.assertEqual(
            data.copy_editable(creative), {"ok": True, "mode": "variants", "reason": None}
        )

    def test_dynamic_with_empty_variants_and_no_product_set_id_is_still_editable(self):
        # The real "only promotional_metadata" shape -- editable, just starts empty.
        creative = {"kind": "dynamic", "fields": {"copy_variants": {"titles": [], "bodies": []}}}
        self.assertEqual(
            data.copy_editable(creative), {"ok": True, "mode": "variants", "reason": None}
        )

    def test_dynamic_catalog_with_only_product_set_id_is_refused(self):
        creative = {"kind": "dynamic", "fields": {"product_set_id": "123"}}
        result = data.copy_editable(creative)
        self.assertEqual(
            result, {"ok": False, "mode": None, "reason": "商品目錄素材沒有可改的文字。"}
        )

    def test_carousel_is_refused(self):
        result = data.copy_editable({"kind": "carousel", "fields": {}})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["mode"])
        self.assertIn("輪播", result["reason"])

    def test_unknown_or_missing_creative_is_refused(self):
        self.assertFalse(data.copy_editable({})["ok"])
        self.assertFalse(data.copy_editable(None)["ok"])


class DynamicCopyChangeControlTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="動態文案測試", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="動態活動"
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
                "kind": "dynamic",
                "fields": {
                    "copy_variants": {"titles": ["原標題一", "原標題二"], "bodies": ["原內文一"]},
                    "asset_feed_spec": {
                        "titles": [{"text": "原標題一"}, {"text": "原標題二"}],
                        "bodies": [{"text": "原內文一"}],
                    },
                },
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

    def create(self, after=None, **overrides):
        payload = {
            "operation_id": db.new_id("op"),
            "month": self.month,
            "title": "改動態文案",
            "items": [
                {
                    "kind": "copy",
                    "target_id": self.ad["id"],
                    "after": after or {"titles": ["新標題一", "新標題二"], "bodies": ["新內文一"]},
                    "reason": "測試多組文案變體，未聲稱因果",
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

    def test_build_item_accepts_variant_shape_and_before_matches_platform(self):
        created = self.create()
        item = created["items"][0]
        self.assertEqual(
            item["after"], {"titles": ["新標題一", "新標題二"], "bodies": ["新內文一"]}
        )
        self.assertEqual(
            item["before"], {"titles": ["原標題一", "原標題二"], "bodies": ["原內文一"]}
        )

    def test_single_copy_shape_is_rejected_for_dynamic_ad(self):
        with self.assertRaisesRegex(ValueError, "不支援的欄位"):
            self.create(after={"body": "舊格式"})

    def test_more_than_five_items_in_one_list_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "最多 5 則"):
            self.create(after={"titles": [f"標題{i}" for i in range(6)], "bodies": []})

    def test_all_empty_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少填寫一則"):
            self.create(after={"titles": [], "bodies": []})

    def test_blank_item_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "請填寫要修改的文案"):
            self.create(after={"titles": ["  "], "bodies": []})

    def _readback(self, approved, titles, bodies):
        ad = copy.deepcopy(self.ad)
        ad["creative"]["fields"]["copy_variants"] = {"titles": titles, "bodies": bodies}
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

    def test_verify_confirms_regardless_of_variant_order(self):
        approved = self.approve(self.create())
        # Same set, reordered -- contract B point 3: compare variant sets order-insensitively.
        checked = self._readback(approved, ["新標題二", "新標題一"], ["新內文一"])
        self.assertEqual(checked["items"][0]["verification_state"], "confirmed")
        self.assertIsNotNone(checked["items"][0]["verified_at"])

    def test_verify_pending_while_platform_still_shows_the_before_set(self):
        approved = self.approve(self.create())
        checked = self._readback(approved, ["原標題一", "原標題二"], ["原內文一"])
        self.assertEqual(checked["items"][0]["verification_state"], "pending")

    def test_verify_deviated_keeps_the_observed_variants(self):
        approved = self.approve(self.create())
        checked = self._readback(approved, ["別的標題"], ["別的內文"])
        item = checked["items"][0]
        self.assertEqual(item["verification_state"], "deviated")
        self.assertEqual(
            item["evidence_json"]["observed"], {"titles": ["別的標題"], "bodies": ["別的內文"]}
        )


class ReviewCopyEditableReadTimeTest(unittest.TestCase):
    """`evidence_json.conditions.copy_editable` is computed on every GET, not baked in at
    submit time -- a later re-sync of the ad's creative must change the answer without touching
    the stored evidence or its hash (the LLM input and dedup key)."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="讀取檢討品牌", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="持續活動"
        )["id"]
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='確認訊息是否吸引關注',"
            "objective='awareness' WHERE id=%s",
            (self.campaign,),
        )
        self.ad = external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "ad",
                "native_id": "copy-editable-ad",
                "native_status": "ACTIVE",
                "currency": "TWD",
                "creative": {"kind": "image", "fields": {"title": "原標題", "body": "原文案"}},
            },
        )
        self.end = settings.today_for_org(self.conn, org_id=self.org) - timedelta(days=1)
        self.start = self.end - timedelta(days=2)
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patch.object(review_rounds, "PROVIDER", self.fake).start()
        patch.object(providers, "resolve_model", return_value="claude-haiku-4-5").start()
        self.addCleanup(patch.stopall)
        self.conn.commit()

    def test_copy_editable_reflects_current_creative_kind_at_read_time(self):
        row = review_rounds.request(
            self.conn, self.org, self.brand, self.campaign, self.ad["id"], self.start, self.end
        )
        self.assertEqual(
            row["evidence_json"]["conditions"]["copy_editable"],
            {"ok": True, "mode": "single", "reason": None},
        )
        self.conn.execute(
            "UPDATE ads_external_entity SET creative=%s WHERE id=%s",
            (db.jsonb({"kind": "carousel", "fields": {}}), self.ad["id"]),
        )
        self.conn.commit()
        refreshed = review_rounds.get(self.conn, self.org, self.brand, self.campaign, row["id"])
        self.assertEqual(refreshed["evidence_hash"], row["evidence_hash"])
        editable = refreshed["evidence_json"]["conditions"]["copy_editable"]
        self.assertFalse(editable["ok"])
        self.assertIn("輪播", editable["reason"])


if __name__ == "__main__":
    unittest.main()
