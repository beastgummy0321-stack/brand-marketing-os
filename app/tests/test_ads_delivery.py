# -*- coding: utf-8 -*-
"""T3 交付確認的未完成與人工確認防線。"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import creative, delivery, handoff, repository as ads_repo
from app.ads import repository_channel_plan as channel_repo
from app.brand_intelligence import repository as bi
from app.core import db
from app.core.db import new_id, now_iso


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self.tmpdir.name) / "test.db")
        self.previous_web_conn = web.conn
        web.conn = self.conn
        self.client = TestClient(main.app)
        self.brand = bi.create_brand(self.conn, name="交付測試", client_name=None, actor="tester")
        product = bi.create_product(self.conn, self.brand["id"], name="商品", actor="tester")
        self.product_id = product["id"]
        self.cycle = ads_repo.create_cycle(self.conn, self.brand["id"], product_ids=[self.product_id],
                                             pain_value=5, objective="sales", actor="tester")

    def tearDown(self):
        web.conn = self.previous_web_conn
        self.conn.close()
        self.tmpdir.cleanup()

    def _add_complete_item(self, angle="晨間第一杯"):
        cell_id = new_id("exc")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, product_id, creative_angle, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cell_id, self.cycle["id"], self.brand["id"], self.product_id, angle, now_iso()),
        )
        brief_id = creative._brief_for_cell(
            self.conn, self.brand["id"], self.cycle["id"],
            {"id": cell_id, "creative_angle": angle}, now_iso())
        for kind, content in (("hook", f"{angle}主打句"), ("copy", f"{angle}文案"),
                              ("image_prompt", f"{angle}圖片描述")):
            self.conn.execute(
                "INSERT INTO creative_variant (id, variant_type, creative_brief_id, campaign_cycle_id, "
                "experiment_cell_id, brand_id, attributes_json, fingerprint_json, rationale, "
                "recommendation_rank, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '', 1, 'DRAFT', ?)",
                (new_id("cvr"), kind, brief_id, self.cycle["id"], cell_id, self.brand["id"],
                 json.dumps({"content": content}, ensure_ascii=False), now_iso()),
            )
        self.conn.commit()
        return cell_id

    def test_assembling_hides_two_confirmation_steps(self):
        result = delivery.view(self.conn, self.brand["id"], self.cycle["id"])
        self.assertEqual(result["status"], "assembling")
        self.assertEqual(result["items"], [])
        self.assertFalse(result["checks"]["budget_confirmed"])

    def test_confirm_requires_all_material_and_budget(self):
        with self.assertRaises(ValueError):
            delivery.confirm(self.conn, self.brand["id"], self.cycle["id"], facts=[], budget=False,
                             actor="tester")

    def test_ready_defaults_to_all_facts_and_confirm_returns_handoff_cards(self):
        item_id = self._add_complete_item()
        ready = delivery.view(self.conn, self.brand["id"], self.cycle["id"])
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["checks"]["facts_confirmed"], [True])

        result = delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                                  facts=[item_id], budget=True, actor="tester")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["action_cards"]), 1)
        self.assertIn("campaign_name", result["action_cards"][0])

    def test_reject_keeps_other_items_ready_and_replacement_returns_only_its_card(self):
        first = self._add_complete_item("第一則")
        second = self._add_complete_item("第二則")
        delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                         facts=[first, second], budget=True, actor="tester")
        delivery.reject_item(self.conn, self.brand["id"], self.cycle["id"], first, actor="tester")
        after_reject = delivery.view(self.conn, self.brand["id"], self.cycle["id"])
        self.assertEqual(after_reject["status"], "ready")
        self.assertIn("補件中", after_reject["reason"])
        self.assertEqual([item["id"] for item in after_reject["items"]], [second])

        # 把補件直接落回原切角，模擬工作檯補齊該素材。
        group = next(g for g in creative.group_by_cell(self.conn, self.brand["id"], self.cycle["id"])
                     if g["cell"]["id"] == first)
        brief_id = group["variants"][0]["creative_brief_id"]
        for kind, content in (("copy", "第一則補件文案"), ("image_prompt", "第一則補件圖片")):
            self.conn.execute(
                "INSERT INTO creative_variant (id, variant_type, creative_brief_id, campaign_cycle_id, "
                "experiment_cell_id, brand_id, attributes_json, fingerprint_json, rationale, "
                "recommendation_rank, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '', 1, 'DRAFT', ?)",
                (new_id("cvr"), kind, brief_id, self.cycle["id"], first, self.brand["id"],
                 json.dumps({"content": content}, ensure_ascii=False), now_iso()),
            )
        self.conn.commit()
        result = delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                                  facts=[first, second], budget=False, actor="tester")
        self.assertEqual([card["experiment_cell_id"] for card in result["action_cards"]], [first])

    def test_reject_before_confirm_keeps_remaining_items_default_checked(self):
        first = self._add_complete_item("第一則")
        second = self._add_complete_item("第二則")
        delivery.reject_item(self.conn, self.brand["id"], self.cycle["id"], first, actor="tester")

        result = delivery.view(self.conn, self.brand["id"], self.cycle["id"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual([item["id"] for item in result["items"]], [second])
        self.assertEqual(result["checks"]["facts_confirmed"], [True])

    def test_replacement_response_hides_mapped_old_package_but_keeps_evidence(self):
        first = self._add_complete_item("第一則")
        second = self._add_complete_item("第二則")
        initial = delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                                   facts=[first, second], budget=True, actor="tester")
        old_package = next(card for card in initial["action_cards"] if card["experiment_cell_id"] == first)
        handoff.authorize_and_map(
            self.conn, self.brand["id"], self.cycle["id"], old_package["id"],
            meta_ids={"meta_campaign_id": "12345"}, actor="tester")
        delivery.reject_item(self.conn, self.brand["id"], self.cycle["id"], first, actor="tester")

        group = next(g for g in creative.group_by_cell(self.conn, self.brand["id"], self.cycle["id"])
                     if g["cell"]["id"] == first)
        brief_id = group["variants"][0]["creative_brief_id"]
        for kind, content in (("copy", "第一則補件文案"), ("image_prompt", "第一則補件圖片")):
            self.conn.execute(
                "INSERT INTO creative_variant (id, variant_type, creative_brief_id, campaign_cycle_id, "
                "experiment_cell_id, brand_id, attributes_json, fingerprint_json, rationale, "
                "recommendation_rank, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '', 1, 'DRAFT', ?)",
                (new_id("cvr"), kind, brief_id, self.cycle["id"], first, self.brand["id"],
                 json.dumps({"content": content}, ensure_ascii=False), now_iso()),
            )
        self.conn.commit()
        replacement = delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                                       facts=[first, second], budget=False, actor="tester")

        self.assertEqual(len(replacement["action_cards"]), 1)
        self.assertEqual(replacement["action_cards"][0]["experiment_cell_id"], first)
        self.assertNotEqual(replacement["action_cards"][0]["id"], old_package["id"])
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM publishing_package WHERE id = ?", (old_package["id"],)).fetchone())

    def test_failed_build_keeps_confirmations_and_uses_plain_language(self):
        item_id = self._add_complete_item()
        original = handoff.build_packages
        handoff.build_packages = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("technical secret"))
        try:
            result = delivery.confirm(self.conn, self.brand["id"], self.cycle["id"],
                                      facts=[item_id], budget=True, actor="tester")
        finally:
            handoff.build_packages = original
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("technical secret", result["reason"])
        failed = delivery.view(self.conn, self.brand["id"], self.cycle["id"])
        self.assertTrue(failed["checks"]["facts_confirmed"][0])
        self.assertTrue(failed["checks"]["budget_confirmed"])

    def test_http_routes_cover_confirmation_rejection_and_plain_language(self):
        item_id = self._add_complete_item()
        root = f"/api/campaigns/{self.brand['id']}/{self.cycle['id']}/delivery"
        self.assertEqual(self.client.get(root).status_code, 200)
        missing = self.client.post(f"{root}/confirm", json={"facts": [], "budget": False})
        self.assertEqual(missing.status_code, 400)
        self.assertIn("請完成", missing.json()["error"])
        confirmed = self.client.post(f"{root}/confirm", json={"facts": [item_id], "budget": True})
        self.assertEqual(confirmed.status_code, 200)
        rejected = self.client.post(f"{root}/items/{item_id}/reject")
        self.assertEqual(rejected.status_code, 200)
        forbidden = ("受眾", "漏斗", "CPA", "CTR", "CPC", "ROAS", "KPI")
        payload = json.dumps(confirmed.json(), ensure_ascii=False)
        self.assertFalse(any(word in payload for word in forbidden))

    def test_channel_plan_put_persists_partial_enabled_changes_and_rejects_unknown_channel(self):
        social = channel_repo.create_channel_plan(
            self.conn, self.brand["id"], self.cycle["id"], channel="social", job="社群安排",
            pct=100, expected="讓更多人看見", enabled=True, depth="full")
        search = channel_repo.create_channel_plan(
            self.conn, self.brand["id"], self.cycle["id"], channel="google_search", job="搜尋安排",
            pct=0, expected="準備搜尋內容", enabled=True, depth="task_card")
        url = f"/api/campaigns/brands/{self.brand['id']}/cycles/{self.cycle['id']}/channel-plan"

        response = self.client.put(url, json={"channels": [{"channel": "social", "enabled": False}]})
        self.assertEqual(response.status_code, 200, response.text)
        returned = {plan["channel"]: plan for plan in response.json()["channels"]}
        self.assertFalse(returned["social"]["enabled"])
        self.assertTrue(returned["google_search"]["enabled"])
        self.assertFalse(channel_repo.get_channel_plan(self.conn, self.brand["id"], social["id"])["enabled"])
        self.assertTrue(channel_repo.get_channel_plan(self.conn, self.brand["id"], search["id"])["enabled"])

        unknown = self.client.put(url, json={"channels": [{"channel": "missing", "enabled": False}]})
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("沒有這個管道", unknown.json()["error"])
