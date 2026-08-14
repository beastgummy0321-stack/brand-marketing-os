# -*- coding: utf-8 -*-
"""票 21：品牌層投放自動度規則卡與 JSON API。"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_autonomy_api_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db, rule_cards  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class AutonomyRuleCardTest(unittest.TestCase):
    def setUp(self):
        self._db_dir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._db_dir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._db_dir.cleanup()

    def _audit_rows(self):
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'rule_card_value' ORDER BY id"
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
        self.assertEqual(rows[-1]["after_json"], '{"value": 1.0}')


class AutonomyRuleCardApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(main.conn, name="自動度驗收品牌", client_name=None, actor="測試員")
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

    def test_old_html_route_rejects_mode_outside_two_allowed_codes(self):
        response = self.client.post(
            f"/brands/{self.brand_id}/settings/ads/autonomy/edit",
            data={"mode": "1.5"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("保守檔（1）與放手檔（2）", response.text)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.brand_id, "autonomy", "mode"), 1.0)

    def test_old_html_settings_excludes_autonomy_card(self):
        response = self.client.get(f"/brands/{self.brand_id}/settings/ads")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("投放自動度", response.text)


if __name__ == "__main__":
    unittest.main()
