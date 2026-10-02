"""app/tests/test_rule_cards_api.py — 規則卡 JSON API（票 B1-settings，契約
`.scratch/grill/GRILL-B1-settings.md` S15.29–S15.33）。

`GET/POST /api/settings/rule-cards/brands/{brand_id}[/{card_key}[/reset]]`：沿用
app/tests/test_settings_hub.py 的暫存 DB／TestClient 慣例，另外比對 JSON 契約 RuleCard
型別（含 `customized` 旗標）。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.brand_web import routes_brand_settings
from app.core import rule_cards
from app.core.db import DEV_ORG_ID  # noqa: E402

ACTOR = "測試員"


class RuleCardsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構北風羊毛", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_get_shape_matches_contract_type(self):
        resp = self.client.get(f"/api/settings/rule-cards/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body["data"].keys()), {"brand_id", "cards"})
        self.assertEqual(body["data"]["brand_id"], self.bid)
        cards = body["data"]["cards"]
        # 2026-08-29 刪掉六張沒有消費端的卡剩四張；dead-code-sweep 票 04（2026-08-30）
        # 再刪 rule_expiry（規則不再過期），剩三張。票 01（T6c 成效判讀）加回第四張
        # `gross_margin`（打平線用的毛利率，決定 1b）。F03-I17（使用者裁決 4：預算搬進
        # 投放中心）把 `schedule_budget` 從設定頁清單藏起來，回到 3 張。
        self.assertEqual(len(cards), 3)
        self.assertNotIn("schedule_budget", {c["key"] for c in cards})
        card = next(c for c in cards if c["key"] == "rule_prompt_cap")
        self.assertEqual(set(card.keys()), {"key", "title", "description", "fields"})
        field = card["fields"][0]
        self.assertEqual(set(field.keys()), {"key", "label", "unit", "help", "value", "customized"})
        self.assertFalse(field["customized"])  # 從沒改過，非自訂
        self.assertEqual(field["value"], 20.0)

    def test_card_text_speaks_to_the_user_only(self):
        """F31-I10: the settings page renders description/help verbatim; no ticket numbers
        or internal role words (代理／外殼) may reach it."""
        cards = self.client.get(f"/api/settings/rule-cards/brands/{self.bid}").json()["data"]["cards"]
        for card in cards:
            for text in [card["description"], *(f["help"] for f in card["fields"])]:
                for word in ("票", "代理", "外殼"):
                    self.assertNotIn(word, text, f"{card['key']}: {text}")

    def test_get_unknown_brand_404s(self):
        resp = self.client.get("/api/settings/rule-cards/brands/brand_沒這個品牌")
        self.assertEqual(resp.status_code, 404)

    def test_save_writes_db_and_marks_customized(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count",
            json={"plan_count_min": 2, "plan_count_max": 8},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_min"), 2.0)
        card = resp.json()["data"]
        field = next(f for f in card["fields"] if f["key"] == "plan_count_min")
        self.assertTrue(field["customized"])
        self.assertEqual(field["value"], 2.0)

    def test_save_missing_field_gives_human_error_and_keeps_others_unchanged(self):
        before = rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max")
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count",
            json={"plan_count_min": 2},  # 缺另一個欄位：整卡一起送出，缺一個就整卡擋下
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("field_errors", resp.json())
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max"), before)

    def test_save_non_positive_number_rejected(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/rule_prompt_cap",
            json={"max_active_rules": 0},
        )
        self.assertEqual(resp.status_code, 400)

    def test_each_field_keeps_its_declared_bounds(self):
        """F47 Contract A (drill-10 V4): margin 7 (700%) and plan count min 6 > max 3 are refused
        with one sentence naming the field(s); nothing is stored."""
        before = rule_cards.get_value(web.conn, self.bid, "gross_margin", "gross_margin_rate")
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/gross_margin", json={"gross_margin_rate": 7})
        self.assertEqual(resp.status_code, 400)
        sentence = "毛利率要大於 0、小於 1（例如 0.7 代表毛利 70%）。"
        self.assertEqual(resp.json(), {"error": sentence, "field_errors": {"gross_margin_rate": sentence}})
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "gross_margin", "gross_margin_rate"), before)
        ok = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/gross_margin", json={"gross_margin_rate": 0.45})
        self.assertEqual(ok.status_code, 200)

        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count",
            json={"plan_count_min": 6, "plan_count_max": 3})
        self.assertEqual(resp.status_code, 400)
        both = "方案數量下限（6）不能大於方案數量上限（3）。"
        self.assertEqual(resp.json()["field_errors"], {"plan_count_min": both, "plan_count_max": both})
        self.assertNotEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_min"), 6.0)

    def test_every_card_field_declares_bounds(self):
        for card in rule_cards.CARDS.values():
            for meta in card["fields"].values():
                self.assertIn("bounds", meta)
                self.assertTrue(meta["bounds"].contains(meta["default"]) or meta["default"] == 0.0)

    def test_save_unknown_card_key_404s(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/沒這張卡", json={"x": 1})
        self.assertEqual(resp.status_code, 404)

    def test_reset_restores_default(self):
        rule_cards.set_value(web.conn, self.bid, "rule_prompt_cap", "max_active_rules", 45.0, actor=ACTOR, org_id=DEV_ORG_ID)
        resp = self.client.post(f"/api/settings/rule-cards/brands/{self.bid}/rule_prompt_cap/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "rule_prompt_cap", "max_active_rules"), 20.0)
        field = resp.json()["data"]["fields"][0]
        self.assertFalse(field["customized"])
        self.assertEqual(field["value"], 20.0)

    def test_brand_isolation(self):
        """A 品牌改的值不影響 B 品牌透過 API 讀到的現值（沿用 rule_cards 既有分品牌行為）。"""
        brand_b = bi_repo.create_brand(web.conn, name="虛構深夜廚房", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)
        self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/rule_prompt_cap",
            json={"max_active_rules": 30},
        )
        body_b = self.client.get(f"/api/settings/rule-cards/brands/{brand_b['id']}").json()
        card = next(c for c in body_b["data"]["cards"] if c["key"] == "rule_prompt_cap")
        self.assertEqual(card["fields"][0]["value"], 20.0)  # 系統預設，未被 A 品牌污染

    def test_old_html_route_still_works_after_extraction(self):
        """驗證 _validate_card_fields() 的抽函式重構沒有改變 HTML 表單路由行為（純搬家）。"""
        # HTML 表單路由送進來的是字串，驗證與寫入都走抽出來的共用函式（純搬家的那一份）
        parsed, field_errors = routes_brand_settings._validate_card_fields(
            "rule_prompt_cap", {"max_active_rules": "30"})
        self.assertEqual(field_errors, {})
        for field_key, value in parsed.items():
            rule_cards.set_value(web.conn, self.bid, "rule_prompt_cap", field_key, value, ACTOR, org_id=DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "rule_prompt_cap", "max_active_rules"), 30.0)


if __name__ == "__main__":
    unittest.main()
