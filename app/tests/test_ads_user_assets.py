"""Original bytes, retry boundaries, and immutable arrangements in isolated schemas."""

import asyncio
import hashlib
import threading
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.ads import external_repository as external
from app.ads import repository as campaigns
from app.ads import slots
from app.ads import user_assets as service
from app.ads import user_assets_repository as repo
from app.ads import user_assets_routes as routes
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.main import app

CONTENT = b"\x89PNG\r\n\x1a\noriginal-bytes"
OTHER_CONTENT = b"\x89PNG\r\n\x1a\nanother-original"
FULL_COPY = {"headline": "標題", "body": "文案", "description": "說明"}


class UserAssetsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="原檔", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="原生"
        )["id"]
        self.conn.commit()
        self.objects = {}
        self.put_patch = patch.object(service.storage, "put", side_effect=self.put).start()
        patch.object(
            service.storage, "get", side_effect=lambda **kw: self.objects[kw["key"]]
        ).start()
        patch.object(
            service.storage, "delete", side_effect=lambda **kw: self.objects.pop(kw["key"], None)
        ).start()
        patch.object(service, "enqueue_preview").start()
        self.addCleanup(patch.stopall)
        self.client = TestClient(app)
        self.prefix = f"/api/ads/brands/{self.brand}/user-assets"

    def put(self, **kw):
        self.objects[kw["key"]] = (kw["content"], kw["content_type"])

    def batch(self, copy=None, size=None):
        return repo.create_batch(
            self.conn,
            self.org,
            self.brand,
            [
                {
                    "filename": "misleading.mp4",
                    "size": len(CONTENT) if size is None else size,
                    "copy_fields": copy or {"body": " 原文\n保留 "},
                }
            ],
            "test",
        )["uploads"][0]

    def original(self, copy=None):
        item = self.batch(copy)
        service.begin_upload(self.conn, self.org, self.brand, item["id"])
        return service.accept_upload(self.conn, self.org, self.brand, item["id"], CONTENT)

    def test_original_download_dedup_history_and_brand_isolation(self):
        first = self.original()
        second = self.original({"body": "另一批文案"})
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertEqual(len(self.objects), 1)
        response = self.client.get(f"{self.prefix}/{first['asset_id']}/download")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, CONTENT)
        self.assertEqual(response.headers["content-type"], "image/png")
        rows = self.client.get(self.prefix).json()["uploads"]
        self.assertEqual({r["copy_fields"]["body"] for r in rows}, {" 原文\n保留 ", "另一批文案"})
        other = brands.create_brand(
            self.conn, org_id=self.org, name="隔離", actor="test", client_name=None
        )["id"]
        self.conn.commit()
        self.assertEqual(
            self.client.get(
                f"/api/ads/brands/{other}/user-assets/{first['asset_id']}/download"
            ).status_code,
            404,
        )

    def test_size_and_spoof_failures_remain_visible(self):
        too_big = self.batch(size=service.media_probe.MAX_BYTES + 1)
        self.assertEqual(too_big["status"], "failed")
        item = self.batch(size=3)
        response = self.client.put(f"{self.prefix}/uploads/{item['id']}/content", content=b"bad")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["upload"]["status"], "failed")
        self.assertEqual(self.objects, {})
        self.assertEqual(len(repo.list_assets(self.conn, self.org, self.brand)["uploads"]), 2)

    def test_storage_success_db_failure_reconciles_without_losing_original(self):
        item = self.batch()
        service.begin_upload(self.conn, self.org, self.brand, item["id"])
        with patch.object(repo, "finalize_original", side_effect=RuntimeError("db unavailable")):
            result = service.accept_upload(self.conn, self.org, self.brand, item["id"], CONTENT)
        self.assertEqual(result["status"], "reconcile_pending")
        self.assertEqual(len(self.objects), 1)
        final = service.reconcile_upload(self.conn, self.org, self.brand, item["id"])
        self.assertEqual(final["status"], "complete")
        service.fail_upload(self.conn, self.org, self.brand, item["id"], "late cancellation")
        self.assertEqual(
            repo.get_upload(self.conn, self.org, self.brand, item["id"])["status"], "complete"
        )

    def planned_ads(self, count):
        """Hand-made planned ads in one group -- the slot upload's `ad_id` targets."""
        group = db.new_id("adg")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture','新客',500,'new')",
            (group, self.org, self.brand, self.campaign),
        )
        ads = [db.new_id("ada") for _ in range(count)]
        for index, ad in enumerate(ads):
            self.conn.execute(
                "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (ad, self.org, self.brand, self.campaign, group, f"廣告 {index + 1}"),
            )
        self.conn.commit()
        return ads

    def internal_ad(self):
        """An app-built campaign with one planned ad -- the slot upload's target."""
        today = settings.today_for_org(self.conn, org_id=self.org)
        campaign = campaigns.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "預覽後就緒",
                "goal_text": "檢驗訊息",
                "objective": "awareness",
                "start_date": today,
                "end_date": today + timedelta(days=7),
            },
            created_by="test",
        )["id"]
        group = db.new_id("adg")
        ad = db.new_id("ada")
        self.conn.execute(
            "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
            "name,daily_budget,role) VALUES(%s,%s,%s,%s,'fixture','新客',500,'new')",
            (group, self.org, self.brand, campaign),
        )
        self.conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name) "
            "VALUES(%s,%s,%s,%s,%s,'晨光隨行杯・日常出發')",
            (ad, self.org, self.brand, campaign, group),
        )
        self.conn.commit()
        return campaign, ad

    def upload_bytes(self, content, copy):
        item = self.batch(copy, size=len(content))
        service.begin_upload(self.conn, self.org, self.brand, item["id"])
        return service.accept_upload(self.conn, self.org, self.brand, item["id"], content)

    def preview(self, asset_id):
        result = {
            "width": 1080, "height": 1080, "duration": None, "thumbnail": b"poster",
            "preview": b"preview", "preview_mime": "image/jpeg", "preview_duration": None,
        }
        with patch.object(service.media_probe, "preview", return_value=result):
            service.process_preview(self.org, self.brand, asset_id)

    def test_preview_done_confirms_and_assigns_the_slot_waiting_on_it(self):
        """Drill-8 #4: a file uploaded into a slot while its original was still pending reaches
        `ready` when the preview finishes -- no second call. A library placement (no ad points
        at it) of the same or another original still waits for the user's confirmation."""
        item = self.original(FULL_COPY)
        other = self.upload_bytes(OTHER_CONTENT, FULL_COPY)
        campaign, ad = self.internal_ad()
        uploaded = slots.upload(
            self.conn, self.org, self.brand, campaign, ad,
            {"asset_id": item["asset_id"], "copy_fields": FULL_COPY}, "human",
        )["placement"]
        self.assertIsNone(uploaded["confirmed_at"])  # the original is still pending
        library = repo.attach(
            self.conn, self.org, self.brand, campaign, item["asset_id"], FULL_COPY, "librarian"
        )
        other_library = repo.attach(
            self.conn, self.org, self.brand, campaign, other["asset_id"], FULL_COPY, "librarian"
        )
        self.conn.commit()

        self.preview(item["asset_id"])
        self.preview(other["asset_id"])

        self.assertEqual(
            repo.get_asset(self.conn, self.org, self.brand, item["asset_id"])["status"], "ready"
        )
        placement = repo.placement(self.conn, self.org, self.brand, campaign, uploaded["id"])
        self.assertIsNotNone(placement["confirmed_at"])
        self.assertEqual((placement["created_by"], placement["confirmed_by"]), ("human", "human"))
        row = campaigns.get_ad(self.conn, self.org, self.brand, ad)
        self.assertEqual(
            (row["material_placement_id"], row["material_placement_revision"]),
            (uploaded["id"], placement["revision"]),
        )
        self.assertIsNone(row["slot_placement_id"])
        for waiting in (library, other_library):
            self.assertIsNone(
                repo.placement(self.conn, self.org, self.brand, campaign, waiting["id"])[
                    "confirmed_at"
                ]
            )

    def test_a_failing_settle_after_the_preview_leaves_the_asset_ready(self):
        """The settle after the preview is best-effort: a failure there never turns the made
        preview into `error`/`retryable`; the slot keeps waiting and manual confirmation works."""
        item = self.original(FULL_COPY)
        campaign, ad = self.internal_ad()
        uploaded = slots.upload(
            self.conn, self.org, self.brand, campaign, ad,
            {"asset_id": item["asset_id"], "copy_fields": FULL_COPY}, "human",
        )["placement"]
        with patch.object(slots, "settle_ready_asset", side_effect=RuntimeError("boom")):
            self.preview(item["asset_id"])
        asset = repo.get_asset(self.conn, self.org, self.brand, item["asset_id"])
        self.assertEqual((asset["status"], asset["error"]), ("ready", None))
        self.assertIsNone(
            repo.placement(self.conn, self.org, self.brand, campaign, uploaded["id"])[
                "confirmed_at"
            ]
        )
        self.assertEqual(
            campaigns.get_ad(self.conn, self.org, self.brand, ad)["slot_placement_id"],
            uploaded["id"],
        )
        confirmed = self.client.post(
            f"/api/ads/brands/{self.brand}/campaigns/{campaign}/placements/{uploaded['id']}"
            "/confirm",
            json={"expected_revision": uploaded["revision"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(
            campaigns.get_ad(self.conn, self.org, self.brand, ad)["material_placement_id"],
            uploaded["id"],
        )

    def slot(self, campaign, ad):
        view = slots.read(self.conn, self.org, self.brand, campaign)
        return next(s for g in view["groups"] for s in g["slots"] if s["ad_id"] == ad)

    def test_preview_done_on_a_copy_the_program_refuses_blocks_the_slot_with_its_reason(self):
        """F44-I04: the settle after the preview runs the same confirmation; a refusal there is
        kept on the placement, so the slot stops reading `in_progress` once the wait is over."""
        partial = {"headline": "標題", "body": "文案"}
        item = self.original(partial)
        campaign, ad = self.internal_ad()
        uploaded = slots.upload(
            self.conn, self.org, self.brand, campaign, ad,
            {"asset_id": item["asset_id"], "copy_fields": partial}, "human",
        )["placement"]
        waiting = self.slot(campaign, ad)
        self.assertEqual((waiting["state"], waiting["blocked"]), ("in_progress", None))
        self.conn.commit()

        self.preview(item["asset_id"])

        placement = repo.placement(self.conn, self.org, self.brand, campaign, uploaded["id"])
        self.assertIsNone(placement["confirmed_at"])
        self.assertEqual([d["kind"] for d in placement["blocked_reasons"]], ["copy"])
        refused = self.slot(campaign, ad)
        self.assertEqual(refused["state"], "blocked")
        self.assertEqual(
            refused["blocked"],
            {
                "text": "請补齊標題、內文與說明，或補充可用品牌事實。", "terms": [],
                "fix": "copy", "more": 0,
            },
        )

    def test_a_preview_that_fails_for_good_blocks_the_slot_with_the_file_exit(self):
        """F44-I04: the failure `process_preview` writes (`error` + its sentence) is the slot's
        reason; a failure that is still retried keeps the slot `in_progress`."""
        item = self.original(FULL_COPY)
        campaign, ad = self.internal_ad()
        slots.upload(
            self.conn, self.org, self.brand, campaign, ad,
            {"asset_id": item["asset_id"], "copy_fields": FULL_COPY}, "human",
        )
        self.conn.commit()
        with patch.object(service.storage, "get", side_effect=RuntimeError("temporary")):
            service.process_preview(self.org, self.brand, item["asset_id"])
        asset = repo.get_asset(self.conn, self.org, self.brand, item["asset_id"])
        self.assertEqual(asset["status"], "retryable")
        retried = self.slot(campaign, ad)
        self.assertEqual((retried["state"], retried["blocked"]), ("in_progress", None))

        with patch.object(
            service.media_probe, "preview", side_effect=service.media_probe.MediaError("損毀")
        ):
            service.process_preview(self.org, self.brand, item["asset_id"])
        failed = self.slot(campaign, ad)
        self.assertEqual(failed["state"], "blocked")
        self.assertEqual(
            failed["blocked"],
            {"text": "這個檔案處理失敗：損毀", "terms": [], "fix": "file", "more": 0},
        )

    def test_same_ad_different_copy_is_still_a_conflict(self):
        """F40-I02: the current row is keyed by (campaign, asset, ad); the same ad uploading the
        same file with different copy still gets `PlacementConflict` with the current row."""
        item = self.original()
        (ad,) = self.planned_ads(1)
        first = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"],
            item["copy_fields"], "test", ad_id=ad,
        )
        self.conn.commit()
        same = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"],
            item["copy_fields"], "test", ad_id=ad,
        )
        self.assertEqual((same["id"], same["revision"], same["ad_id"]), (first["id"], 1, ad))
        with self.assertRaises(repo.PlacementConflict) as caught:
            repo.attach(
                self.conn, self.org, self.brand, self.campaign, item["asset_id"],
                {"body": "不同"}, "test", ad_id=ad,
            )
        self.assertEqual(caught.exception.current["id"], first["id"])
        # A library attach (no ad) of the same original is its own row, not this ad's conflict.
        library = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"], {"body": "不同"},
            "test",
        )
        self.assertIsNone(library["ad_id"])
        self.assertNotEqual(library["id"], first["id"])
        with self.assertRaises(repo.PlacementConflict):
            repo.attach(
                self.conn, self.org, self.brand, self.campaign, item["asset_id"],
                {"body": "再不同"}, "test",
            )

    def test_two_ads_share_one_original_with_their_own_copy(self):
        """F40-I02 (drill-7 #6, user ruling 2026-09-29): one photo backs two ads, each with its
        own copy -- two current placements, no conflict; a revision keeps its ad."""
        item = self.original()
        first_ad, second_ad = self.planned_ads(2)
        first = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"],
            {"body": "第一則文案"}, "test", ad_id=first_ad,
        )
        self.conn.commit()
        second = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"],
            {"body": "第二則文案"}, "test", ad_id=second_ad,
        )
        self.conn.commit()
        self.assertNotEqual(first["id"], second["id"])
        current = [
            (row["asset_id"], row["ad_id"], row["is_current"], row["copy_fields"]["body"])
            for row in repo.list_placements(self.conn, self.org, self.brand, self.campaign)
        ]
        self.assertEqual(
            current,
            [
                (item["asset_id"], first_ad, True, "第一則文案"),
                (item["asset_id"], second_ad, True, "第二則文案"),
            ],
        )
        revised = repo.revise(
            self.conn, self.org, self.brand, self.campaign, second["id"], 1,
            {"copy_fields": {"body": "第二則改稿"}}, "test",
        )
        self.assertEqual((revised["revision"], revised["ad_id"]), (2, second_ad))
        self.conn.commit()
        with self.assertRaises(repo.PlacementConflict) as caught:
            repo.attach(
                self.conn, self.org, self.brand, self.campaign, item["asset_id"],
                {"body": "第二則文案"}, "test", ad_id=second_ad,
            )
        self.assertEqual(caught.exception.current["revision"], 2)

    def test_apply_copy_keeps_current_text_for_blank_fields_and_refuses_all_blank(self):
        """F47-I06 (Contract A, drill-10 Q6): 「套用到全部待處理」 with blank fields never wipes the
        current copy; three blank fields are refused with one sentence and nothing is written."""
        item = self.original()
        placed = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"],
            {"headline": "原標題", "body": "原內文", "description": "原說明", "caption": "留著"},
            "test",
        )
        self.conn.commit()
        with self.assertRaises(ValueError) as caught:
            repo.revise(
                self.conn, self.org, self.brand, self.campaign, placed["id"], 1,
                {"apply_copy": {"headline": "", "body": "  ", "description": ""}}, "test",
            )
        self.assertEqual(str(caught.exception), "三欄都是空的，沒有可以套用的內容。")
        self.conn.rollback()
        current = repo.placement(self.conn, self.org, self.brand, self.campaign, placed["id"])
        self.assertEqual(current["revision"], 1)

        revised = repo.revise(
            self.conn, self.org, self.brand, self.campaign, placed["id"], 1,
            {"apply_copy": {"headline": "", "body": "新內文", "description": ""}}, "test",
        )
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["copy_fields"], {
            "headline": "原標題", "body": "新內文", "description": "原說明", "caption": "留著",
        })

    def test_revision_conflict_preserves_current_and_confirmation_history(self):
        item = self.original()
        first = repo.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            item["asset_id"],
            item["copy_fields"],
            "test",
        )
        self.conn.commit()
        same = repo.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            item["asset_id"],
            item["copy_fields"],
            "test",
        )
        self.assertEqual(same["revision"], 1)
        with self.assertRaises(repo.PlacementConflict) as caught:
            repo.attach(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                item["asset_id"],
                {"body": "不同"},
                "test",
            )
        self.assertEqual(caught.exception.current["revision"], 1)
        self.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_by='human',confirmed_at=now() WHERE id=%s",
            (first["id"],),
        )
        updated = repo.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            first["id"],
            1,
            {"copy_fields": {"body": "新原文"}},
            "test",
        )
        self.assertEqual(updated["revision"], 2)
        self.assertIsNone(updated["confirmed_at"])
        self.assertEqual(
            repo.placement(self.conn, self.org, self.brand, self.campaign, first["id"], 1)[
                "confirmed_by"
            ],
            "human",
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            repo.revise(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                first["id"],
                1,
                {"required": False},
                "test",
            )
        self.conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s", (self.campaign,))
        with self.assertRaises(ValueError):
            repo.attach(
                self.conn, self.org, self.brand, self.campaign, item["asset_id"], {}, "test"
            )
        with self.assertRaises(ValueError):
            repo.revise(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                first["id"],
                2,
                {"required": False},
                "test",
            )

    def test_patch_rejects_invalid_types_and_cross_campaign_destination(self):
        item = self.original()
        p = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"], {}, "test"
        )
        self.conn.commit()
        url = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/placements/{p['id']}"
        for payload in [
            {"expected_revision": True},
            {"expected_revision": 1, "purpose": {}},
            {"expected_revision": 1, "destination_entity_id": {}},
            {"expected_revision": 1, "start_date": 4},
            {"expected_revision": 1, "start_date": "wrong"},
            {"expected_revision": 1, "start_date": "2026-12-01", "end_date": "2026-01-01"},
        ]:
            self.assertEqual(self.client.patch(url, json=payload).status_code, 409)
        other = external.create_imported_campaign(self.conn, self.org, self.brand, name="other")[
            "id"
        ]
        entity = external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            other,
            {
                "platform": "fake",
                "source_account": "a",
                "native_kind": "campaign",
                "native_id": "b",
            },
        )
        with self.assertRaises(ValueError):
            repo.revise(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                p["id"],
                1,
                {"destination_entity_id": entity["id"]},
                "test",
            )

    def test_item_lock_excludes_second_attempt_and_retry(self):
        item = self.batch()
        slot, key = routes._lock_upload(self.conn, self.org, self.brand, item["id"])
        try:
            with db.connection() as other:
                with self.assertRaises(ValueError):
                    routes._lock_upload(other, self.org, self.brand, item["id"])
        finally:
            service.release_slot(self.conn, key)
            service.release_slot(self.conn, slot)
        with db.connection() as other:
            lane, item_key = routes._lock_upload(other, self.org, self.brand, item["id"])
            service.release_slot(other, item_key)
            service.release_slot(other, lane)

    def test_permanent_decode_failure_stops_and_storage_retry_is_bounded(self):
        item = self.original()
        asset_id = item["asset_id"]
        with patch.object(
            service.media_probe, "preview", side_effect=service.media_probe.MediaError("損毀")
        ) as probe:
            service.process_preview(self.org, self.brand, asset_id)
            service.process_preview(self.org, self.brand, asset_id)
            self.assertEqual(probe.call_count, 1)
        self.assertEqual(
            repo.get_asset(self.conn, self.org, self.brand, asset_id)["status"], "error"
        )
        service.retry_preview(self.conn, self.org, self.brand, asset_id)
        with patch.object(service.storage, "get", side_effect=RuntimeError("temporary")):
            for _ in range(5):
                service.process_preview(self.org, self.brand, asset_id)
        asset = repo.get_asset(self.conn, self.org, self.brand, asset_id)
        self.assertEqual(asset["preview_attempts"], 3)
        self.assertEqual(asset["status"], "error")
        self.assertEqual(self.objects[asset["storage_key"]][0], CONTENT)

    def test_cancel_during_storage_waits_before_unlock_and_preserves_complete(self):
        item = self.batch()
        entered = threading.Event()
        proceed = threading.Event()
        original_accept = service.accept_upload

        def slow(*args):
            entered.set()
            proceed.wait(5)
            return original_accept(*args)

        async def scenario():
            sent = False

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": CONTENT, "more_body": False}
                return {"type": "http.disconnect"}

            request = Request({"type": "http", "headers": []}, receive)
            from types import SimpleNamespace

            actor = SimpleNamespace(org_id=self.org, user_id="test")
            with (
                patch.object(routes.web, "require_actor", return_value=actor),
                patch.object(service, "accept_upload", side_effect=slow),
            ):
                task = asyncio.create_task(routes.upload(request, self.brand, item["id"]))
                await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                proceed.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        asyncio.run(scenario())
        final = repo.get_upload(self.conn, self.org, self.brand, item["id"])
        self.assertEqual(final["status"], "complete")
        asset = repo.get_asset(self.conn, self.org, self.brand, final["asset_id"])
        self.assertEqual(asset["sha256"], hashlib.sha256(CONTENT).hexdigest())
        with db.connection() as other:
            lane, key = routes._lock_upload(other, self.org, self.brand, item["id"])
            service.release_slot(other, key)
            service.release_slot(other, lane)

    def test_history_pagination_does_not_hide_failed_or_completed_rows(self):
        self.original()
        for _ in range(10):
            repo.create_batch(
                self.conn,
                self.org,
                self.brand,
                [
                    {"filename": str(i), "size": service.media_probe.MAX_BYTES + 1}
                    for i in range(10)
                ],
                "test",
            )
        first = repo.list_assets(self.conn, self.org, self.brand)
        self.assertEqual(len(first["uploads"]), 100)
        self.assertIsNotNone(first["next_upload_cursor"])
        second = repo.list_assets(
            self.conn, self.org, self.brand, upload_after=first["next_upload_cursor"]
        )
        self.assertEqual(len(second["uploads"]), 1)
        self.assertIsNone(second["next_upload_cursor"])
        combined = first["uploads"] + second["uploads"]
        self.assertEqual(len({u["id"] for u in combined}), 101)
        self.assertEqual(sum(u["status"] == "complete" for u in combined), 1)

    def test_concurrent_duplicate_uploads_keep_one_canonical_original(self):
        from concurrent.futures import ThreadPoolExecutor

        first, second = self.batch(), self.batch()
        barrier = threading.Barrier(2)

        def send(item):
            with db.connection() as conn:
                service.begin_upload(conn, self.org, self.brand, item["id"])
                barrier.wait(5)
                return service.accept_upload(conn, self.org, self.brand, item["id"], CONTENT)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, [first, second]))
        self.assertEqual({r["status"] for r in results}, {"complete"})
        self.assertEqual(len({r["asset_id"] for r in results}), 1)
        self.assertEqual(len(self.objects), 1)
        asset = repo.get_asset(self.conn, self.org, self.brand, results[0]["asset_id"])
        self.assertEqual(self.objects[asset["storage_key"]][0], CONTENT)

    def test_upload_attach_conflict_returns_current_revision(self):
        first = self.original()
        second = self.original({"body": "changed"})
        url = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/placements"
        created = self.client.post(url, json={"upload_id": first["id"]})
        self.assertEqual(created.status_code, 200, created.text)
        conflict = self.client.post(url, json={"upload_id": second["id"]})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertIn("placement_copy_conflict", conflict.text)
        self.assertEqual(
            repo.list_placements(self.conn, self.org, self.brand, self.campaign)[0]["revision"], 1
        )

    def test_attach_purpose_is_a_program_keyword_never_a_request_field(self):
        """F35 Contract T: `attach(..., purpose=)` stores the purpose on revision 1 (the slot
        upload fills it with the ad's name); `POST …/placements` never takes it from the body."""
        item = self.original()
        placed = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"], {}, "test",
            purpose="晨光隨行杯・日常出發",
        )
        self.conn.commit()
        self.assertEqual((placed["revision"], placed["purpose"]), (1, "晨光隨行杯・日常出發"))
        self.assertEqual(
            repo.placement(self.conn, self.org, self.brand, self.campaign, placed["id"])["purpose"],
            "晨光隨行杯・日常出發",
        )
        with self.assertRaises(ValueError):
            repo.attach(
                self.conn, self.org, self.brand, self.campaign, item["asset_id"], {}, "test",
                purpose="x" * 4001,
            )
        with self.assertRaises(ValueError):
            repo.attach_selected(
                self.conn, self.org, self.brand, self.campaign, {"asset_id": item["asset_id"]},
                "test", purpose={"not": "text"},
            )

        # The same original placed in another campaign through the route: `purpose` in the body
        # is not a request field and never reaches the row.
        other_campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="另一個"
        )["id"]
        self.conn.commit()
        url = f"/api/ads/brands/{self.brand}/campaigns/{other_campaign}/placements"
        created = self.client.post(url, json={"upload_id": item["id"], "purpose": "偷帶的用途"})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertIsNone(created.json()["placement"]["purpose"])

    def test_statutory_warning_is_listed_per_placement_and_never_blocks_confirm(self):
        """F34 Contract S + ruling 2B: a `food_tw` brand sees the reminder on the placement
        list with the ads closing clause; confirming the same copy still succeeds. A brand
        without a regime carries `statutory_warning: None`."""
        copy = {"headline": "下午不用撐", "body": "十分鐘內治療你的疲勞", "description": "隨身補給"}
        item = self.original(copy)
        self.conn.execute(
            "UPDATE ads_user_asset SET status='ready' WHERE id=%s", (item["asset_id"],)
        )
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='認識品牌',objective='awareness' WHERE id=%s",
            (self.campaign,),
        )
        placed = repo.attach(
            self.conn, self.org, self.brand, self.campaign, item["asset_id"], copy, "test"
        )
        placed = repo.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            placed["id"],
            1,
            {"purpose": "品牌介紹"},
            "test",
        )
        self.conn.commit()
        url = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/placements"
        listed = self.client.get(url)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIsNone(listed.json()["placements"][0]["statutory_warning"])

        brands.set_regulatory_regime(self.conn, self.brand, "food_tw", actor="test")
        self.conn.commit()
        warned = self.client.get(url).json()["placements"][0]["statutory_warning"]
        self.assertIsNotNone(warned)
        self.assertIn("治療", [t["term"] for t in warned["terms"]])
        self.assertTrue(all(t["tier_label"] for t in warned["terms"]))
        self.assertTrue(warned["sentence"].endswith("確認無誤仍可確認安排。"))
        self.assertNotIn("選定", warned["sentence"])
        self.assertTrue(warned["href"].startswith("https://"))
        confirmed = self.client.post(
            f"{url}/{placed['id']}/confirm", json={"expected_revision": placed["revision"]}
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["placement"]["status"], "manual_ready")
