# -*- coding: utf-8 -*-
"""票 21：品牌層投放自動度規則卡與 JSON API。"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db, rule_cards


class AutonomyRuleCardTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _audit_rows(self):
        # entity_id 篩死 autonomy.mode，不只篩 entity_type='rule_card_value'：ADR 0027
        # 起這個模組（檔案）的兩個 TestCase 共用同一個 schema，
        # AutonomyRuleCardApiTest 也會寫 rule_card_value 的稽核（不同 brand_id、不同
        # card_key），只篩 entity_type 會把它們也算進來。
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'rule_card_value'"
            " AND entity_id = 'autonomy.mode' ORDER BY id"
        ).fetchall()]

    def test_default_is_conservative_and_card_has_single_mode_field(self):
        self.assertIn("autonomy", rule_cards.CARDS)
        self.assertEqual(rule_cards.CARDS["autonomy"]["fields"]["mode"]["default"], 1.0)
        self.assertEqual(rule_cards.get_value(self.conn, "brand_a", "autonomy", "mode"), 1.0)

    def test_set_and_reset_keep_brand_value_and_audit(self):
        rule_cards.set_value(self.conn, "brand_a", "autonomy", "mode", 2.0, actor="測試員")
        self.assertEqual(rule_cards.get_value(self.conn, "brand_a", "autonomy", "mode"), 2.0)
        self.assertEqual(rule_cards.get_value(self.conn, "brand_b", "autonomy", "mode"), 1.0)

        rule_cards.reset_card(self.conn, "brand_a", "autonomy", actor="測試員")
        self.assertEqual(rule_cards.get_value(self.conn, "brand_a", "autonomy", "mode"), 1.0)
        rows = self._audit_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["entity_id"], "autonomy.mode")
        # jsonb 欄位，psycopg 已自動解碼成 dict，不是 JSON 字串
        self.assertEqual(rows[-1]["after_json"], {"value": 1.0})


class AutonomyRuleCardApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(web.conn, name="自動度驗收品牌", client_name=None, actor="測試員")
        self.brand_id = brand["id"]

    def test_post_accepts_both_positive_mode_codes(self):
        for mode in (1.0, 2.0):
            response = self.client.post(
                f"/api/settings/rule-cards/brands/{self.brand_id}/autonomy",
                json={"mode": mode},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["fields"][0]["value"], mode)

    def test_zero_code_is_rejected_by_existing_positive_number_validation(self):
        response = self.client.post(
            f"/api/settings/rule-cards/brands/{self.brand_id}/autonomy",
            json={"mode": 0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("大於 0", response.json()["field_errors"]["mode"])

    def test_api_rejects_mode_outside_two_allowed_codes(self):
        response = self.client.post(
            f"/api/settings/rule-cards/brands/{self.brand_id}/autonomy",
            json={"mode": 3.7},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("保守檔（1）與放手檔（2）", response.text)


if __name__ == "__main__":
    unittest.main()
