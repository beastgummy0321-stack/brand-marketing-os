# -*- coding: utf-8 -*-
"""app/tests/test_ads_creative_theme.py — 主題資料模型存取層（票 02-theme-tables）。

驗 app/ads/theme_repository.py 的建立／讀取／依格查詢／狀態更新來回讀寫，
以及元件的型別／序號／指紋／超字標記／標黃旗標欄位。品牌與檔期一律虛構。
"""

import json
import unittest

from app.ads import fingerprint as fp
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡（主題票）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.product_id = bi_repo.create_product(self.conn, self.bid, name="虛構濾掛組",
                                                  actor=ACTOR)["id"]
        self.cycle_id = ads_repo.create_cycle(
            self.conn, self.bid, product_ids=[self.product_id],
            pain_value=5, objective="sales", actor=ACTOR,
        )["id"]
        self.cell_id = db.new_id("exc")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (self.cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, db.now_iso()),
        )
        self.conn.commit()

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
            " AND action = 'create' AND entity_id = %s", (created["id"],)
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
        other_cell_id = db.new_id("exc")
        self.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s)", (other_cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, db.now_iso()),
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
            " AND action = 'update_status' AND entity_id = %s", (created["id"],)
        ).fetchone()
        self.assertIsNotNone(row)
        before = row["before_json"]
        after = row["after_json"]
        self.assertEqual(before["status"], "draft")
        self.assertEqual(after["status"], "rejected")

    def test_update_status_missing_theme_raises(self):
        with self.assertRaises(ValueError):
            theme_repo.update_theme_status(
                self.conn, self.bid, "cth_does_not_exist", status="adopted", actor=ACTOR)


class AdoptThemeTest(_Base):
    """票 10-adopt-reject AC1：一鍵採用 → 主題狀態與全部元件標採用，一次動作一筆
    主題級決策紀錄；AC4：決策紀錄走既有稽核慣例（before/after）。"""

    def test_adopt_sets_theme_status_to_adopted(self):
        created = self._create(components=[
            {"component_type": "body", "content": "三分鐘沖一杯好咖啡"},
            {"component_type": "title", "content": "早晨從一杯開始"},
        ])
        adopted = theme_repo.adopt_theme(self.conn, self.bid, created["id"], actor=ACTOR)
        self.assertEqual(adopted["status"], "adopted")
        refetched = theme_repo.get_theme(self.conn, self.bid, created["id"])
        self.assertEqual(refetched["status"], "adopted")
        # AC1／AC3：沒有逐元件的「已採用」欄位——元件是否算數看主題本身的 status，
        # 全部元件（body／title 都在）跟著主題一起算採用，不需要逐欄位勾選。
        for component in refetched["components"]:
            self.assertFalse(component["rejected"])

    def test_adopt_writes_exactly_one_theme_level_decision(self):
        created = self._create()
        theme_repo.adopt_theme(self.conn, self.bid, created["id"], actor=ACTOR)
        rows = self.conn.execute(
            "SELECT * FROM adoption_decision WHERE brand_id = %s AND target_type = 'theme'"
            " AND target_id = %s", (self.bid, created["id"]),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "adopted")
        self.assertEqual(rows[0]["campaign_cycle_id"], self.cycle_id)
        self.assertEqual(rows[0]["decided_by"], ACTOR)

    def test_adopt_writes_audit_log_with_before_after(self):
        created = self._create()
        theme_repo.adopt_theme(self.conn, self.bid, created["id"], actor=ACTOR)
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'creative_theme'"
            " AND action = 'adopt' AND entity_id = %s", (created["id"],)
        ).fetchone()
        self.assertIsNotNone(row)
        before = row["before_json"]
        after = row["after_json"]
        self.assertEqual(before["status"], "draft")
        self.assertEqual(after["status"], "adopted")

    def test_adopt_missing_theme_raises(self):
        with self.assertRaises(ValueError):
            theme_repo.adopt_theme(self.conn, self.bid, "cth_does_not_exist", actor=ACTOR)

    def test_adopt_missing_actor_raises(self):
        created = self._create()
        with self.assertRaises(ValueError):
            theme_repo.adopt_theme(self.conn, self.bid, created["id"], actor="")


class RejectComponentTest(_Base):
    """票 10-adopt-reject AC2：單元件退件＋理由 → 該元件除名、理由碼與指紋進拒絕記憶；
    AC3：不提供逐欄位勾選採用、退件不影響同主題其他元件；AC4：稽核慣例（before/after）。"""

    def _theme_with_two_body_components(self):
        return self._create(components=[
            {"component_type": "body", "content": "三分鐘沖一杯好咖啡",
             "fingerprint_json": {"angle": "benefit", "tone": "warm",
                                  "format": "single_image", "selling_point": "quality"}},
            {"component_type": "body", "content": "辦公室也能沖一杯講究的咖啡",
             "fingerprint_json": {"angle": "scene", "tone": "professional",
                                  "format": "single_image", "selling_point": "convenience"}},
        ])

    def test_reject_marks_only_that_component_rejected(self):
        created = self._theme_with_two_body_components()
        target, other = created["components"]
        result = theme_repo.reject_component(
            self.conn, self.bid, target["id"], reason_code="off_brand", actor=ACTOR)
        self.assertTrue(result["rejected"])
        self.assertEqual(result["reject_reason_label"], fp.REJECT_REASON_LABELS["off_brand"])

        refetched = theme_repo.get_theme(self.conn, self.bid, created["id"])
        components_by_id = {c["id"]: c for c in refetched["components"]}
        self.assertTrue(components_by_id[target["id"]]["rejected"])
        # AC3：退件不影響同主題其他元件——另一則 body 仍然是未退件狀態。
        self.assertFalse(components_by_id[other["id"]]["rejected"])
        # 元件本身沒被砍掉（append-only 稽核慣例），內容還在。
        self.assertEqual(components_by_id[target["id"]]["content"], target["content"])

        # 主題狀態不因單一元件退件而改變。
        self.assertEqual(refetched["status"], "draft")

    def test_reject_writes_decision_with_reason_code_and_fingerprint_snapshot(self):
        created = self._theme_with_two_body_components()
        target = created["components"][0]
        theme_repo.reject_component(
            self.conn, self.bid, target["id"], reason_code="off_brand", actor=ACTOR)
        row = self.conn.execute(
            "SELECT * FROM adoption_decision WHERE brand_id = %s AND target_type = 'theme_component'"
            " AND target_id = %s", (self.bid, target["id"]),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["decision"], "rejected")
        self.assertEqual(row["reason_code"], "off_brand")
        self.assertEqual(row["fingerprint_json"], target["fingerprint_json"])
        self.assertEqual(row["campaign_cycle_id"], self.cycle_id)

    def test_reject_writes_audit_log_with_before_after(self):
        created = self._theme_with_two_body_components()
        target = created["components"][0]
        theme_repo.reject_component(
            self.conn, self.bid, target["id"], reason_code="hook_weak", actor=ACTOR)
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'creative_theme_component'"
            " AND action = 'reject' AND entity_id = %s", (target["id"],)
        ).fetchone()
        self.assertIsNotNone(row)
        before = row["before_json"]
        after = row["after_json"]
        self.assertFalse(before["rejected"])
        self.assertTrue(after["rejected"])
        self.assertEqual(after["reason_code"], "hook_weak")

    def test_reject_invalid_reason_code_raises(self):
        created = self._theme_with_two_body_components()
        target = created["components"][0]
        with self.assertRaises(ValueError):
            theme_repo.reject_component(
                self.conn, self.bid, target["id"], reason_code="not_a_real_reason", actor=ACTOR)

    def test_reject_missing_component_raises(self):
        with self.assertRaises(ValueError):
            theme_repo.reject_component(
                self.conn, self.bid, "cthc_does_not_exist", reason_code="off_brand", actor=ACTOR)

    def test_reject_component_with_no_fingerprint_does_not_crash(self):
        """image_prompt 這類型別本來就沒有四軸指紋——退件仍要能記錄，只是拒絕約束
        推不出具體的軸值文字（app/ads/creative.py _rejection_constraints() 既有行為）。"""
        created = self._create(components=[
            {"component_type": "image_prompt", "content": "暖金色茶席上的三入禮盒"},
        ])
        target = created["components"][0]
        result = theme_repo.reject_component(
            self.conn, self.bid, target["id"], reason_code="visual_weird", actor=ACTOR)
        self.assertTrue(result["rejected"])


if __name__ == "__main__":
    unittest.main()
