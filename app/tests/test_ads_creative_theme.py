# -*- coding: utf-8 -*-
"""app/tests/test_ads_creative_theme.py — 主題資料模型存取層（票 02-theme-tables）。

驗 app/ads/theme_repository.py 的建立／讀取／依格查詢／狀態更新來回讀寫，
以及元件的型別／序號／指紋／超字標記／標黃旗標欄位。品牌與檔期一律虛構。
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡（主題票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(self.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self.cycle_id = ads_repo.create_cycle(
            self.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        self.cell_id = "exc_test_cell"
        self.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)",
            (self.cell_id, self.cycle_id, self.bid, db.now_iso()),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _create(self, **overrides):
        kwargs = dict(
            campaign_cycle_id=self.cycle_id, experiment_cell_id=self.cell_id,
            format_key="single_image", name="虛構主題：晨光第一杯", folder_code="A1B2",
            actor=ACTOR,
        )
        kwargs.update(overrides)
        return theme_repo.create_theme(self.conn, self.bid, **kwargs)


class CreateAndReadRoundTripTest(_Base):
    def test_create_then_get_round_trips_every_field(self):
        created = self._create()
        fetched = theme_repo.get_theme(self.conn, self.bid, created["id"])
        self.assertIsNotNone(fetched)
        for key in ("id", "brand_id", "campaign_cycle_id", "experiment_cell_id",
                    "format_key", "name", "folder_code", "status"):
            self.assertEqual(fetched[key], created[key])
        self.assertEqual(fetched["format_key"], "single_image")
        self.assertEqual(fetched["name"], "虛構主題：晨光第一杯")
        self.assertEqual(fetched["folder_code"], "A1B2")
        self.assertEqual(fetched["status"], "draft")
        self.assertEqual(fetched["components"], [])

    def test_get_missing_theme_returns_none(self):
        self.assertIsNone(theme_repo.get_theme(self.conn, self.bid, "cth_does_not_exist"))

    def test_wrong_brand_cannot_read_another_brands_theme(self):
        created = self._create()
        other_brand = bi_repo.create_brand(self.conn, name="虛構隔壁咖啡（主題票）",
                                           client_name="測試客戶", actor=ACTOR)["id"]
        self.assertIsNone(theme_repo.get_theme(self.conn, other_brand, created["id"]))

    def test_create_requires_name_and_folder_code_and_actor(self):
        with self.assertRaises(ValueError):
            self._create(name="")
        with self.assertRaises(ValueError):
            self._create(folder_code="")
        with self.assertRaises(ValueError):
            self._create(actor="")

    def test_create_writes_audit_log(self):
        created = self._create()
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'creative_theme'"
            " AND action = 'create' AND entity_id = ?", (created["id"],)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], ACTOR)


class ComponentFieldsTest(_Base):
    def test_component_carries_type_sequence_fingerprint_flags(self):
        created = self._create(components=[
            {"component_type": "card_image_prompt", "sequence": 1,
             "content": "第一張卡：倒咖啡的手部特寫",
             "fingerprint_json": {"angle": "convenience", "tone": "warm"},
             "over_budget": False, "similarity_flag": True},
            {"component_type": "card_title", "sequence": 1, "content": "早晨從一杯開始"},
        ])
        components = created["components"]
        self.assertEqual(len(components), 2)

        image = next(c for c in components if c["component_type"] == "card_image_prompt")
        self.assertEqual(image["sequence"], 1)
        self.assertEqual(image["fingerprint_json"], {"angle": "convenience", "tone": "warm"})
        self.assertEqual(image["over_budget"], 0)
        self.assertEqual(image["similarity_flag"], 1)

        title = next(c for c in components if c["component_type"] == "card_title")
        self.assertEqual(title["content"], "早晨從一杯開始")
        self.assertIsNone(title["fingerprint_json"])
        self.assertEqual(title["over_budget"], 0)

    def test_over_budget_flag_persists(self):
        created = self._create(components=[
            {"component_type": "body", "content": "超長文案" * 20, "over_budget": True},
        ])
        self.assertEqual(created["components"][0]["over_budget"], 1)

    def test_component_requires_type_and_content(self):
        with self.assertRaises(ValueError):
            self._create(components=[{"component_type": "", "content": "x"}])
        with self.assertRaises(ValueError):
            self._create(components=[{"component_type": "body", "content": ""}])

    def test_components_ordered_by_sequence(self):
        created = self._create(format_key="carousel", components=[
            {"component_type": "card_title", "sequence": 3, "content": "第三卡"},
            {"component_type": "card_title", "sequence": 1, "content": "第一卡"},
            {"component_type": "card_title", "sequence": 2, "content": "第二卡"},
        ])
        contents = [c["content"] for c in created["components"]]
        self.assertEqual(contents, ["第一卡", "第二卡", "第三卡"])


class ListByCellTest(_Base):
    def test_list_themes_for_cell_returns_only_that_cells_themes(self):
        theme_a = self._create(name="虛構主題 A")
        other_cell_id = "exc_other_cell"
        self.conn.execute(
            "INSERT INTO experiment_cell (id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (?, ?, ?, ?)", (other_cell_id, self.cycle_id, self.bid, db.now_iso()),
        )
        self.conn.commit()
        self._create(name="虛構主題 B（別格）", experiment_cell_id=other_cell_id)

        found = theme_repo.list_themes_for_cell(self.conn, self.bid, self.cell_id)
        self.assertEqual([t["id"] for t in found], [theme_a["id"]])
        self.assertEqual(found[0]["name"], "虛構主題 A")

    def test_list_for_cell_with_no_themes_returns_empty(self):
        self.assertEqual(theme_repo.list_themes_for_cell(self.conn, self.bid, self.cell_id), [])


class UpdateStatusTest(_Base):
    def test_update_status_round_trips_and_bumps_updated_at(self):
        created = self._create()
        updated = theme_repo.update_theme_status(
            self.conn, self.bid, created["id"], status="adopted", actor=ACTOR)
        self.assertEqual(updated["status"], "adopted")
        self.assertNotEqual(updated["updated_at"], created["updated_at"])

        refetched = theme_repo.get_theme(self.conn, self.bid, created["id"])
        self.assertEqual(refetched["status"], "adopted")

    def test_update_status_writes_audit_log_with_before_after(self):
        created = self._create()
        theme_repo.update_theme_status(
            self.conn, self.bid, created["id"], status="rejected", actor=ACTOR)
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'creative_theme'"
            " AND action = 'update_status' AND entity_id = ?", (created["id"],)
        ).fetchone()
        self.assertIsNotNone(row)
        before = json.loads(row["before_json"])
        after = json.loads(row["after_json"])
        self.assertEqual(before["status"], "draft")
        self.assertEqual(after["status"], "rejected")

    def test_update_status_missing_theme_raises(self):
        with self.assertRaises(ValueError):
            theme_repo.update_theme_status(
                self.conn, self.bid, "cth_does_not_exist", status="adopted", actor=ACTOR)


if __name__ == "__main__":
    unittest.main()
