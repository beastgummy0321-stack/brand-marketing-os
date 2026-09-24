"""Imported workspaces cannot enter the internal strategy/publish/close lifecycle."""

import unittest

from fastapi.testclient import TestClient

from app import main
from app.ads import assets, closeout, plan, repository, strategy
from app.ads import external_repository as external
from app.ads.adapters import manual, simulated
from app.ads.external_models import IMPORTED_REASON
from app.brand_intelligence import repository as brands
from app.core import db


class ExternalLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="既有生命週期", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="已暫停"
        )
        self.id = self.campaign["id"]
        self.conn.commit()
        self.client = TestClient(main.app)
        self.url = f"/api/ads/brands/{self.brand}/campaigns/{self.id}"

    def test_read_without_fake_goal_dates_budget_or_results(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        campaign = response.json()["campaign"]
        for key in (
            "goal_text",
            "objective",
            "start_date",
            "end_date",
            "budget_total",
        ):
            self.assertIsNone(campaign[key], key)
        self.assertFalse([key for key in campaign if key.startswith("success_")])
        self.assertIsNone(campaign["cap"]["value"])
        self.assertEqual(campaign["origin"], "imported")
        self.assertEqual(campaign["groups"], [])
        self.assertEqual(campaign["external_view"]["observations"], [])
        self.assertIsNone(campaign["outcome"]["purchases"])
        self.assertIn("add_assets", campaign["capabilities"]["allowed"])
        self.assertIn("close", campaign["capabilities"]["unavailable"])
        performance = self.client.get(self.url + "/performance").json()
        self.assertEqual(performance["origin"], "imported")
        self.assertNotIn("totals", performance)

    def test_direct_services_reject_before_llm_or_mutation(self):
        calls = [
            lambda: strategy.generate(self.conn, self.org, self.brand, self.id, actor="test"),
            lambda: plan.adopt_strategy(self.conn, self.org, self.brand, self.id, actor="test"),
            lambda: assets.dispatch_pack(self.conn, self.org, self.brand, self.id),
            lambda: manual.publish(self.conn, self.org, self.brand, self.id, actor="test"),
            lambda: simulated.publish(self.conn, self.org, self.brand, self.id, actor="test"),
            lambda: simulated.generate_outcomes(self.conn, self.org, self.brand, self.id),
            lambda: closeout.close(self.conn, self.org, self.brand, self.id, actor="test"),
        ]
        for call in calls:
            with self.assertRaisesRegex(ValueError, "既有活動"):
                call()
        self.assertEqual(
            repository.get_campaign(self.conn, self.org, self.brand, self.id)["status"], "draft"
        )

    def test_api_blocks_legacy_mutations_with_understandable_reason(self):
        for path in (
            "strategy",
            "strategy/scenario",
            "strategy/allocation",
            "plan",
            "pack",
            "publish",
            "bind",
            "ingest",
            "close",
            "comparison",
            "simulation/start",
        ):
            with self.subTest(path=path):
                response = self.client.post(self.url + "/" + path, json={})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn(IMPORTED_REASON, response.text)

    def test_other_brand_cannot_read_imported_campaign(self):
        other = brands.create_brand(
            self.conn, org_id=self.org, name="其他", actor="test", client_name=None
        )["id"]
        self.conn.commit()
        self.assertEqual(
            self.client.get(f"/api/ads/brands/{other}/campaigns/{self.id}").status_code, 404
        )

    def test_past_platform_dates_do_not_close_workspace(self):
        external.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.id,
            {
                "platform": "third",
                "source_account": "a",
                "native_kind": "portfolio",
                "native_id": "1",
                "end_date": "2000-01-01",
                "native_status": "PAUSED",
            },
        )
        self.conn.commit()
        campaign = self.client.get(self.url).json()["campaign"]
        self.assertEqual(campaign["status"], "draft")
        self.assertEqual(campaign["external_view"]["entities"][0]["native_status"], "PAUSED")
        self.assertNotIn("結案", campaign["judgment"]["detail"])

    def test_internal_contract_and_capabilities_remain(self):
        with self.assertRaisesRegex(ValueError, "goal_text_unknown"):
            repository.create_campaign(
                self.conn, self.org, self.brand, {"name": "internal", "origin": "imported"}
            )
        row = repository.create_campaign(
            self.conn,
            self.org,
            self.brand,
            {
                "name": "internal",
                "goal_text": "目標",
                "objective": "購買",
            },
        )
        detail = repository.campaign_detail(self.conn, self.org, self.brand, row["id"])
        self.assertEqual(detail["origin"], "internal")
        self.assertIsNone(detail["external_view"])
        self.assertIn("strategy", detail["capabilities"]["allowed"])

    def test_internal_goal_can_be_completed_but_source_budget_cannot_change(self):
        result = self.client.patch(
            self.url,
            json={
                "goal_text": "增加詢問",
                "objective": "詢問",
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        retired = self.client.patch(self.url, json={"success_target": 100})
        self.assertEqual(retired.status_code, 400, retired.text)
        self.assertEqual(retired.json()["error"]["code"], "goal_fields_retired")
        self.assertEqual(result.json()["campaign"]["objective"], "詢問")
        self.assertIsNone(result.json()["campaign"]["start_date"])
        result = self.client.patch(
            self.url, json={"objective": "覆寫", "constraints_json": {"budget": 1000}}
        )
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.client.get(self.url).json()["campaign"]["objective"], "詢問")
        self.assertEqual(self.client.patch(self.url, json={"status": "live"}).status_code, 422)
