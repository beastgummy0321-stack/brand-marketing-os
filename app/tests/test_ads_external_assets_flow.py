"""Cross-service HTTP/DB flow; Storage and remote providers are explicit fakes.

This suite uses the existing per-file PostgreSQL schema fixture. It is not evidence
of real Storage, platform permission, browser rendering or the separate runtime.
"""

import copy
import json
import struct
import unittest
import zlib
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ads import asset_suggestions, external_repository, external_sync, user_assets
from app.ads.adapters.external import SourcePage
from app.brand_intelligence import repository as brands
from app.core import db
from app.llm import providers
from app.main import app


class FlowReader:
    """Third native hierarchy, deliberately no media equivalence/history claim."""

    def __init__(self, org, brand):
        self.org, self.brand = org, brand
        self.fail_page = False
        self.creative_id = "creative-one"
        self.calls = []

    def accounts(self, conn, org, brand):
        if (org, brand) != (self.org, self.brand):
            return []
        return [
            {
                "account_id": account,
                "name": "同名帳號",
                "currency": "TWD",
                "timezone_name": "Asia/Taipei",
            }
            for account in ("101", "202")
        ]

    def node(self, account, native_id, kind="portfolio", **extra):
        return {
            "platform": "meta",
            "source_account": account,
            "native_kind": kind,
            "native_id": native_id,
            "name": "同名活動",
            "native_status": "PAUSED",
            **extra,
        }

    def list_existing(self, conn, org, brand, account, *, cursor=None, **kwargs):
        self.calls.append(("GET", "list", account["account_id"], cursor))
        if cursor and self.fail_page:
            raise ValueError("private source diagnostic must not leak")
        return SourcePage(
            [
                self.node(
                    account["account_id"],
                    "later" if cursor else "root",
                    budget_type="lifetime",
                    budget_raw={"values": {"lifetime_budget": "4000"}},
                    currency="TWD",
                )
            ],
            None if cursor else {"after": "page2"},
        )

    def read_structure(self, conn, org, brand, account, *, native_id, **kwargs):
        a = account["account_id"]
        self.calls.append(("GET", "structure", a, native_id))
        return SourcePage(
            [
                self.node(
                    a,
                    native_id,
                    budget_type="lifetime",
                    budget_raw={"values": {"lifetime_budget": "4000"}},
                ),
                self.node(
                    a, "line", "line", parent_native_kind="portfolio", parent_native_id=native_id
                ),
                self.node(a, "unit", "unit", parent_native_kind="line", parent_native_id="line"),
            ]
        )

    def creative(self):
        return {
            "kind": "video",
            "fields": {"id": self.creative_id, "video_id": "video-remote"},
            "video_original": None,
            "video_original_availability": "unavailable",
        }

    def read_creatives(self, conn, org, brand, account, **kwargs):
        self.calls.append(("GET", "creative", account["account_id"], None))
        return SourcePage(
            [
                {
                    k: v
                    for k, v in self.node(account["account_id"], "unit", "unit").items()
                    if k in {"platform", "source_account", "native_kind", "native_id"}
                }
                | {"creative": self.creative()}
            ]
        )

    def read_observations(self, conn, org, brand, account, *, start, **kwargs):
        self.calls.append(("GET", "observations", account["account_id"], None))
        return SourcePage(
            [
                {
                    "native_kind": "unit",
                    "native_id": "unit",
                    "day": start,
                    "metric_scope": "unit",
                    "attribution_key": "fixture-window",
                    "currency": "TWD",
                    "source": "fixture",
                    "spend": 0,
                    "purchases": None,
                    "revenue": None,
                }
            ]
        )

    def read_monthly(self, conn, org, brand, account, *, start, end, **kwargs):
        self.calls.append(("GET", "monthly", account["account_id"], None))
        # This paused fixture has no account spend; the zero row set is explicitly
        # scoped, not an assumption that a missing reader means a complete month.
        return SourcePage([], coverage={
            "scope": "account_campaign_day", "start": str(start), "end": str(end),
            "account_id": account["account_id"], "currency": account["currency"],
            "timezone_name": account["timezone_name"],
        })

    def binding_kinds(self):
        return ("unit",)

    def verify_native(self, conn, org, brand, account, **kwargs):
        a = account["account_id"]
        self.calls.append(("GET", "verify", a, kwargs["native_id"]))
        return {
            "entity": self.node(
                a,
                "unit",
                "unit",
                parent_native_kind="line",
                parent_native_id="line",
                creative=self.creative(),
            ),
            "parents": [
                self.node(
                    a,
                    "line",
                    "line",
                    parent_native_kind="portfolio",
                    parent_native_id=kwargs["root_id"],
                ),
                self.node(a, kwargs["root_id"]),
            ],
            "timezone_name": "Asia/Taipei",
            "media_equivalence": None,
            "continuous_intervals": [],
        }


class ExternalAssetsFlowTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="整合流程", actor="test", client_name=None
        )["id"]
        self.other = brands.create_brand(
            self.conn, org_id=self.org, name="隔離品牌", actor="test", client_name=None
        )["id"]
        self.conn.commit()
        self.reader = FlowReader(self.org, self.brand)
        self.objects = {}
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patches = [
            patch.object(external_sync.channels, "external_reader", return_value=self.reader),
            patch.object(external_sync.background, "enqueue", return_value=True),
            patch.object(external_sync.background, "is_active", return_value=False),
            patch.object(asset_suggestions, "PROVIDER", self.fake),
            patch.object(providers, "resolve_model", return_value="claude-haiku-4-5"),
            patch.object(providers, "select_provider", side_effect=lambda provider, **kw: provider),
            patch.object(user_assets.storage, "put", side_effect=self.put),
            patch.object(
                user_assets.storage, "get", side_effect=lambda **kw: self.objects[kw["key"]]
            ),
            patch.object(
                user_assets.storage,
                "delete",
                side_effect=lambda **kw: self.objects.pop(kw["key"], None),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.base = f"/api/ads/brands/{self.brand}"
        self.day = (db.now_utc().date() - timedelta(days=2)).isoformat()

    def put(self, **kw):
        self.assertTrue(kw["key"].startswith(self.org + "/"))
        self.objects[kw["key"]] = (kw["content"], kw["content_type"])
        return kw["key"]

    def ok(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def drain(self, job):
        for _ in range(20):
            external_sync.run_sync(self.org, self.brand, job["id"])
            job = external_repository.get_job(self.conn, self.org, self.brand, job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
        self.fail("bounded fake source did not terminate")

    def refresh(self, account="101"):
        job = self.ok(
            "POST",
            self.base + "/existing-campaigns/refresh",
            json={
                "platform": "meta",
                "source_account": account,
                "start": self.day,
                "end": self.day,
            },
        )["job"]
        return self.drain(job)

    def imported(self, account="101"):
        self.refresh(account)
        result = self.ok(
            "POST",
            self.base + "/imports",
            json={
                "platform": "meta",
                "source_account": account,
                "native_kind": "portfolio",
                "native_id": "root",
                "start": self.day,
                "end": self.day,
            },
        )
        self.assertEqual(self.drain(result["job"])["status"], "succeeded")
        return result["campaign"]["id"]

    def test_partial_listing_resume_same_name_accounts_and_repeat_import(self):
        self.reader.fail_page = True
        failed = self.refresh()
        self.assertEqual(failed["status"], "partial")
        self.assertNotIn("private source diagnostic", json.dumps(failed, default=str))
        cached = self.ok("GET", self.base + "/existing-campaigns?platform=meta&source_account=101")
        self.assertEqual(len(cached["items"]), 1)
        self.assertEqual(cached["items"][0]["snapshot"]["native_status"], "PAUSED")
        self.reader.fail_page = False
        self.assertEqual(self.refresh()["status"], "succeeded")
        first = self.imported()
        again = self.imported()
        second = self.imported("202")
        self.assertEqual(first, again)
        self.assertNotEqual(first, second)
        detail = self.ok("GET", self.base + f"/campaigns/{first}")["campaign"]
        self.assertEqual(detail["groups"], [])
        self.assertEqual(detail["origin"], "imported")
        raw = self.ok(
            "GET", self.base + f"/campaigns/{first}/external?start={self.day}&end={self.day}"
        )
        self.assertEqual({e["native_kind"] for e in raw["entities"]}, {"portfolio", "line", "unit"})
        root = next(e for e in raw["entities"] if e["native_kind"] == "portfolio")
        self.assertEqual(root["budget_type"], "lifetime")
        self.assertIsNone(root["budget_amount"])
        self.assertEqual(len(raw["observations"]), 1)
        self.assertEqual(raw["observations"][0]["spend"], 0)
        self.assertIsNone(raw["observations"][0]["purchases"])
        self.assertIsNone(raw["observations"][0]["revenue"])
        forbidden = self.client.get(f"/api/ads/brands/{self.other}/campaigns/{first}/external")
        self.assertNotEqual(forbidden.status_code, 200)
        self.assertTrue(all(call[0] == "GET" for call in self.reader.calls))

    def test_upload_suggest_confirm_handoff_revise_and_source_change_preserve_evidence(self):
        campaign = self.imported()
        path = self.base + f"/campaigns/{campaign}"
        self.ok("PATCH", path, json={"goal_text": "認識品牌", "objective": "awareness"})
        original = {"headline": " 原標題 ", "body": "", "description": " 原說明\n照留 "}

        def chunk(kind, data):
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data))
            )

        content = b"\x89PNG\r\n\x1a\n" + chunk(
            b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
        )
        content += chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 8) * 8)) + chunk(
            b"IEND", b""
        )
        upload = self.ok(
            "POST",
            self.base + "/user-assets/batches",
            json={
                "files": [
                    {"filename": "original.png", "size": len(content), "copy_fields": original}
                ]
            },
        )["batch"]["uploads"][0]
        upload = self.ok(
            "PUT", self.base + f"/user-assets/uploads/{upload['id']}/content", content=content
        )["upload"]
        self.assertEqual(upload["status"], "complete")
        user_assets.process_preview(self.org, self.brand, upload["asset_id"])
        placement = self.ok("POST", path + "/placements", json={"upload_id": upload["id"]})[
            "placement"
        ]
        ppath = path + f"/placements/{placement['id']}"
        reply = {
            "items": [
                {
                    "id": placement["id"],
                    "copy_fields": {
                        "headline": "不應覆蓋",
                        "body": "查看商品資訊",
                        "description": "不應覆蓋",
                    },
                    "purpose": "認識品牌",
                }
            ]
        }
        self.fake.response = providers.ProviderResponse(
            output_text=json.dumps(reply, ensure_ascii=False),
            structured=reply,
            usage=providers.Usage(input_tokens=100, output_tokens=100),
            stop_reason="end_turn",
        )
        request = {
            "placements": [{"id": placement["id"], "revision": 1}],
            "idempotency_key": "flow-once",
            "summary": "",
        }
        batch = self.ok("POST", path + "/asset-suggestions", json=request)["batch"]
        asset_suggestions.run(self.org, self.brand, campaign, batch["id"])
        done = self.ok("GET", path + f"/asset-suggestions/{batch['id']}")["batch"]
        self.assertEqual(done["status"], "succeeded", done.get("error"))
        self.assertEqual(
            self.ok("POST", path + "/asset-suggestions", json=request)["batch"]["id"], batch["id"]
        )
        confirmed = self.ok(
            "POST", ppath + "/confirm", json={"expected_revision": 1, "batch_id": batch["id"]}
        )["placement"]
        self.assertEqual(confirmed["status"], "manual_ready", confirmed)
        self.assertTrue(confirmed["required"])
        self.assertEqual(confirmed["copy_fields"], original)
        self.assertEqual(confirmed["suggested_copy"], {"body": "查看商品資訊"})
        self.assertEqual(len(self.fake.calls), 1)
        report = self.ok("POST", ppath + "/self-report", json={"expected_revision": 1})["binding"]
        self.assertEqual(report["existence_status"], "self_reported")
        self.assertIsNone(report["last_verified_at"])
        candidates = self.ok(
            "GET", ppath + "/binding-candidates?revision=1&platform=meta&account_id=101"
        )["candidates"]
        bound = self.ok(
            "POST",
            ppath + "/verify-binding",
            json={
                "expected_revision": 1,
                "entity_id": candidates[0]["entity_id"],
                "user_verified": True,
            },
        )["binding"]
        self.assertEqual(bound["evidence_level"], "user_verified")
        metrics = self.ok(
            "GET", ppath + f"/version-metrics?revision=1&start={self.day}&end={self.day}"
        )
        self.assertEqual(len(metrics["observations"]), 1)
        self.assertFalse(metrics["observations"][0]["attributed"])
        saved = self.ok("GET", ppath + "/handoff?revision=1")
        self.assertEqual(saved["original_copy"], original)
        self.assertFalse(saved["platform_written"])
        snapshot = copy.deepcopy(bound["creative_snapshot"])
        self.reader.creative_id = "creative-two"
        self.refresh()
        stale = next(
            b
            for b in self.ok("GET", ppath + "/handoff?revision=1")["bindings"]
            if b["id"] == bound["id"]
        )
        self.assertTrue(stale["stale_reason"])
        self.assertEqual(stale["creative_snapshot"], snapshot)
        revised = self.ok("PATCH", ppath, json={"expected_revision": 1, "purpose": "另一用途"})[
            "placement"
        ]
        self.assertEqual(revised["revision"], 2)
        self.assertIsNone(revised["confirmed_at"])
        history = self.ok("GET", path + "/placements?history=true")["placements"]
        self.assertEqual(len(history), 2)
        self.assertTrue(next(p for p in history if p["revision"] == 1)["confirmed_at"])
        self.assertEqual(
            self.client.post(
                ppath + "/confirm", json={"expected_revision": 1, "batch_id": batch["id"]}
            ).status_code,
            409,
        )
        reopened = self.client.get(self.base + f"/user-assets/{upload['asset_id']}/download")
        self.assertEqual(reopened.content, content)
        self.assertEqual(
            self.client.get(
                f"/api/ads/brands/{self.other}/user-assets/{upload['asset_id']}/download"
            ).status_code,
            404,
        )
        self.assertTrue(all(call[0] == "GET" for call in self.reader.calls))
