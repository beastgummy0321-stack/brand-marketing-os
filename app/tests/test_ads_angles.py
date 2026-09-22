"""Contract C (F27): per-ad AI angle candidates, cached per (entity, copy hash)."""

import json
import unittest
from unittest.mock import patch

from app.ads import angles
from app.ads import change_control_data as change_data
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db
from app.llm import providers


class AnglesTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="主打品牌", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="native"
        )["id"]
        self.ad = external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "ad",
                "native_id": "ad-1",
                "native_status": "ACTIVE",
                "currency": "TWD",
                "creative": {
                    "kind": "image",
                    "fields": {"title": "省時省力", "body": "一鍵完成家事", "image_hash": "pic"},
                },
            },
        )
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patch.object(angles, "PROVIDER", self.fake).start()
        self.enqueue = patch.object(angles, "enqueue").start()
        patch.object(providers, "resolve_model", return_value="claude-haiku-4-5").start()
        self.addCleanup(patch.stopall)
        self.conn.commit()

    def reply(self, values=None):
        data = {"angles": values if values is not None else ["省時", "省力", "一鍵完成"]}
        self.fake.response = providers.ProviderResponse(
            output_text=json.dumps(data, ensure_ascii=False),
            structured=data,
            usage=providers.Usage(input_tokens=10, output_tokens=10),
            stop_reason="end_turn",
        )
        return data

    def get(self):
        return angles.get(self.conn, self.org, self.brand, self.campaign, self.ad["id"])

    def run_job(self):
        """Replays exactly the args the (mocked) first `enqueue()` call received."""
        org, brand, campaign, entity_id, copy_hash = self.enqueue.call_args.args
        angles.run(org, brand, campaign, entity_id, copy_hash)

    def test_pending_then_ready_and_cache_hit(self):
        first = self.get()
        self.assertEqual(first, {"status": "pending", "candidates": [], "error": None})
        self.enqueue.assert_called_once()
        self.reply()
        self.run_job()
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0]["max_tokens"], 256)
        ready = self.get()
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["candidates"], ["省時", "省力", "一鍵完成"])
        self.assertIsNone(ready["error"])
        # Cache hit: a second GET after the task succeeded must not enqueue or call the model again.
        again = self.get()
        self.assertEqual(again, ready)
        self.enqueue.assert_called_once()
        self.assertEqual(len(self.fake.calls), 1)

    def test_invalid_model_output_is_failed(self):
        self.get()
        self.reply(["太長太長太長太長太長太長太長超過十二字了", "短一", "短二"])
        self.run_job()
        result = self.get()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["error"])

    def test_wrong_count_is_failed(self):
        self.get()
        self.reply(["只有兩個", "候選"])
        self.run_job()
        result = self.get()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"])

    def test_angle_accepted_and_refused_by_length(self):
        self.assertIsNone(change_data.angle("pause", None))
        self.assertIsNone(change_data.angle("pause", "   "))
        self.assertEqual(change_data.angle("pause", "  省時省力  "), "省時省力")
        self.assertEqual(change_data.angle("pause", "x" * 40), "x" * 40)
        with self.assertRaises(ValueError):
            change_data.angle("pause", "x" * 41)
        with self.assertRaises(ValueError):
            change_data.angle("copy", "省時")


if __name__ == "__main__":
    unittest.main()
