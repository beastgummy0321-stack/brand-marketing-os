# -*- coding: utf-8 -*-
"""T3 駕駛艙補充資料保留任務卡完成紀錄。"""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import cockpit_extras, repository as ads_repo
from app.ads import repository_channel_plan as plans
from app.brand_intelligence import repository as bi
from app.core import db


class CockpitExtrasTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self.tmpdir.name) / "test.db")
        self.previous_web_conn = web.conn
        web.conn = self.conn
        self.client = TestClient(main.app)
        self.brand = bi.create_brand(self.conn, name="駕駛艙", client_name=None, actor="tester")
        product = bi.create_product(self.conn, self.brand["id"], name="商品", actor="tester")
        self.cycle = ads_repo.create_cycle(self.conn, self.brand["id"], product_ids=[product["id"]],
                                             pain_value=5, objective="sales", actor="tester")
        self.card = plans.create_task_card(self.conn, self.brand["id"], self.cycle["id"],
                                           channel="social", title="完成素材")

    def tearDown(self):
        web.conn = self.previous_web_conn
        self.conn.close()
        self.tmpdir.cleanup()

    def test_shape_and_done_retention(self):
        result = cockpit_extras.get(self.conn, self.brand["id"], self.cycle["id"])
        self.assertEqual(len(result["legacy"]), 5)
        self.assertIsNone(result["todo3"]["reply_speed"])
        cockpit_extras.mark_done(self.conn, self.brand["id"], self.card["id"])
        self.assertEqual(cockpit_extras.get(self.conn, self.brand["id"], self.cycle["id"])["task_cards"][0]["done"], 1)

    def test_five_cards_and_todo_values_use_their_existing_sources(self):
        product = bi.list_products(self.conn, self.brand["id"])[0]
        bi.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="早晨素材有效", applicability_scope="品牌",
            created_by="tester", actor="tester", source_track="ads")
        hypothesis = bi.create_strategy_hypothesis(
            self.conn, self.brand["id"], actor="tester", hypothesis_type="angle",
            statement="早晨切角有效", created_by="tester")
        bi.update_hypothesis_status(self.conn, self.brand["id"], hypothesis["id"],
                                    status="supported", actor="tester")
        bi.create_rule(self.conn, self.brand["id"], actor="tester", rule_type="prohibition",
                       content="不可誇大", severity="hard")
        bi.create_official_asset(self.conn, self.brand["id"], actor="tester", asset_kind="image",
                                 file_path="/tmp/product.jpg")
        bi.create_customer_voice(self.conn, self.brand["id"], actor="tester", raw_text="我想要方便",
                                 source_channel="manual", source_type="manual", extraction=[])
        bi.create_product_fact(self.conn, self.brand["id"], product["id"], actor="tester",
                               fact_type="feature", label="特色", value="便利", status="confirmed",
                               confirmed_by="tester")
        bi.save_product_economics(self.conn, self.brand["id"], product["id"], actor="tester",
                                  selling_price=100, currency="TWD", confirmed_by="tester")

        result = cockpit_extras.get(self.conn, self.brand["id"], self.cycle["id"])
        values = {card["key"]: card["value"] for card in result["legacy"]}
        self.assertEqual(values, {"wisdom": 1, "effective_direction": 1, "prohibition": 1,
                                  "material_stock": 1, "customer_understanding": True})
        self.assertEqual(result["todo3"], {"product_completeness": 100,
                                           "good_customer_defined": True, "reply_speed": None})

    def test_http_endpoint_and_done_route_keep_task_in_current_cycle(self):
        extras = self.client.get(f"/api/campaigns/brands/{self.brand['id']}/cockpit-extras")
        self.assertEqual(extras.status_code, 200)
        done = self.client.post(
            f"/api/campaigns/brands/{self.brand['id']}/task-cards/{self.card['id']}/done")
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["done"], 1)
