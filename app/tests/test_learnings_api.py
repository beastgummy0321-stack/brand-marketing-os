# -*- coding: utf-8 -*-
"""累積智慧 JSON API：七段資料、下架動作與舊頁並存。"""

import unittest
import uuid

from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.ads import repository as ads_repo

ACTOR = "測試員"


class LearningsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_id = bi_repo.create_brand(
            main.conn, name=f"累積智慧 API 測試{uuid.uuid4().hex[:8]}", client_name=None, actor=ACTOR,
        )["id"]
        self.learning = ads_repo.create_learning_ledger_entry(
            main.conn, self.brand_id, learning_text="真人分享更容易讓人理解", applicability_scope="brand",
            created_by=ACTOR, actor=ACTOR,
        )
        self.active_rule = bi_repo.create_rule(
            main.conn, self.brand_id, actor=ACTOR, rule_type="tone", content="不要用太急的語氣", severity="soft",
        )
        self._promote_as_active_ban(self.active_rule, "active")
        self.stale_rule = bi_repo.create_rule(
            main.conn, self.brand_id, actor=ACTOR, rule_type="tone", content="太久未確認的規則", severity="soft",
        )
        self._promote_as_active_ban(self.stale_rule, "stale")
        main.conn.execute(
            "UPDATE rule SET confirmed_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (self.stale_rule["id"],),
        )
        main.conn.commit()

    def _promote_as_active_ban(self, rule: dict, suffix: str) -> None:
        main.conn.execute(
            "INSERT INTO creative_rule_card (id, brand_id, fingerprint_axis, fingerprint_value, "
            "proposed_rule_text, evidence_json, reject_count, status, promoted_rule_id, created_at, updated_at) "
            "VALUES (?, ?, 'tone', 'urgent', ?, '{}', 3, 'accepted', ?, '2026-08-01T00:00:00', '2026-08-01T00:00:00')",
            (f"rcd_api_{suffix}_{uuid.uuid4().hex[:8]}", self.brand_id, rule["content"], rule["id"]),
        )

    def _get_sections(self) -> dict:
        response = self.client.get(f"/api/campaigns/brands/{self.brand_id}/learnings")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("generated_at", body)
        return body["data"]

    def test_get_has_seven_sections_and_sweeps_before_active_bans(self):
        data = self._get_sections()
        self.assertEqual(
            set(data),
            {
                "learnings", "active_bans", "pending_reconfirm_rules", "pending_cards",
                "observing_signals", "pending_hypotheses", "overflow_rules",
            },
        )
        self.assertEqual(data["learnings"][0]["id"], self.learning["id"])
        self.assertIn("meta_line", data["learnings"][0])
        self.assertEqual([ban["promoted_rule_id"] for ban in data["active_bans"]], [self.active_rule["id"]])
        self.assertEqual([rule["id"] for rule in data["pending_reconfirm_rules"]], [self.stale_rule["id"]])

    def test_deactivate_learning_removes_it_and_keeps_legacy_page_available(self):
        response = self.client.post(
            f"/api/campaigns/brands/{self.brand_id}/learnings/ledger/{self.learning['id']}/deactivate",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "已下架這條學習，之後生成內容不會再引用它。"})
        self.assertNotIn(self.learning["id"], [entry["id"] for entry in self._get_sections()["learnings"]])

    def test_deactivate_active_ban_removes_it(self):
        response = self.client.post(
            f"/api/campaigns/brands/{self.brand_id}/learnings/rules/{self.active_rule['id']}/deactivate",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "已下架這條禁令，之後生成內容不會再避開它。"})
        self.assertNotIn(self.active_rule["id"], [ban["promoted_rule_id"] for ban in self._get_sections()["active_bans"]])

    def test_reconfirm_pending_rule_restores_it(self):
        self._get_sections()
        response = self.client.post(
            f"/api/campaigns/brands/{self.brand_id}/learnings/rules/{self.stale_rule['id']}/reconfirm",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "已延續這條規則，重新進入生成內容的判斷依據。"})
        self.assertNotIn(self.stale_rule["id"], [rule["id"] for rule in self._get_sections()["pending_reconfirm_rules"]])


if __name__ == "__main__":
    unittest.main()
