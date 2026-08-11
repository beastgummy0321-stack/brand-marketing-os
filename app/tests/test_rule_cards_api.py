# -*- coding: utf-8 -*-
"""app/tests/test_rule_cards_api.py — 規則卡 JSON API（票 B1-settings，契約
`.scratch/grill/GRILL-B1-settings.md` S15.29–S15.33）。

`GET/POST /api/settings/rule-cards/brands/{brand_id}[/{card_key}[/reset]]`：沿用
app/tests/test_settings_hub.py 的暫存 DB／TestClient 慣例，另外比對 JSON 契約 RuleCard
型別（含 `customized` 旗標）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_rule_cards_api_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import rule_cards  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class RuleCardsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構北風羊毛", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def test_get_shape_matches_contract_type(self):
        resp = self.client.get(f"/api/settings/rule-cards/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body["data"].keys()), {"brand_id", "cards"})
        self.assertEqual(body["data"]["brand_id"], self.bid)
        cards = body["data"]["cards"]
        self.assertEqual(len(cards), 6)
        card = next(c for c in cards if c["key"] == "pacing")
        self.assertEqual(set(card.keys()), {"key", "title", "description", "fields"})
        field = card["fields"][0]
        self.assertEqual(set(field.keys()), {"key", "label", "unit", "help", "value", "customized"})
        self.assertFalse(field["customized"])  # 從沒改過，非自訂
        self.assertEqual(field["value"], 0.15)

    def test_get_unknown_brand_404s(self):
        resp = self.client.get("/api/settings/rule-cards/brands/brand_沒這個品牌")
        self.assertEqual(resp.status_code, 404)

    def test_save_writes_db_and_marks_customized(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/ad_creative_fatigue",
            json={"cold_warning": 3, "cold_danger": 5, "retargeting_warning": 4,
                  "retargeting_danger": 6, "niche_warning": 5, "niche_danger": 8},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_warning"), 3.0)
        card = resp.json()["data"]
        field = next(f for f in card["fields"] if f["key"] == "cold_warning")
        self.assertTrue(field["customized"])
        self.assertEqual(field["value"], 3.0)

    def test_save_missing_field_gives_human_error_and_keeps_others_unchanged(self):
        before = rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_danger")
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/ad_creative_fatigue",
            json={"cold_warning": 3},  # 缺其餘 5 個欄位：整卡一起送出，缺一個就整卡擋下
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("field_errors", resp.json())
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_danger"), before)

    def test_save_non_positive_number_rejected(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/pacing",
            json={"deviation_threshold_ratio": 0},
        )
        self.assertEqual(resp.status_code, 400)

    def test_save_unknown_card_key_404s(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/沒這張卡", json={"x": 1})
        self.assertEqual(resp.status_code, 404)

    def test_reset_restores_default(self):
        rule_cards.set_value(main.conn, self.bid, "pacing", "deviation_threshold_ratio", 0.5, actor=ACTOR)
        resp = self.client.post(f"/api/settings/rule-cards/brands/{self.bid}/pacing/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "pacing", "deviation_threshold_ratio"), 0.15)
        field = resp.json()["data"]["fields"][0]
        self.assertFalse(field["customized"])
        self.assertEqual(field["value"], 0.15)

    def test_brand_isolation(self):
        """A 品牌改的值不影響 B 品牌透過 API 讀到的現值（沿用 rule_cards 既有分品牌行為）。"""
        brand_b = bi_repo.create_brand(main.conn, name="虛構深夜廚房", client_name=None, actor=ACTOR)
        self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/pacing",
            json={"deviation_threshold_ratio": 0.9},
        )
        body_b = self.client.get(f"/api/settings/rule-cards/brands/{brand_b['id']}").json()
        card = next(c for c in body_b["data"]["cards"] if c["key"] == "pacing")
        self.assertEqual(card["fields"][0]["value"], 0.15)  # 系統預設，未被 A 品牌污染

    def test_old_html_route_still_works_after_extraction(self):
        """驗證 _validate_card_fields() 的抽函式重構沒有改變 HTML 表單路由行為（純搬家）。"""
        resp = self.client.post(
            f"/brands/{self.bid}/settings/ads/pacing/edit",
            data={"deviation_threshold_ratio": "0.3"}, follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "pacing", "deviation_threshold_ratio"), 0.3)


if __name__ == "__main__":
    unittest.main()
