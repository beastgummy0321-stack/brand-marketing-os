# -*- coding: utf-8 -*-
"""app/tests/test_rule_cards_page.py — 規則卡頁（/rule-cards）路由（issue #12）。

見 app/tests/test_settings_page.py 的暫存 DB／TestClient 慣例。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_rule_cards_page_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.core import rule_cards  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class RuleCardsPageTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM rule_card_value")
        main.conn.commit()
        main.conn.execute("DELETE FROM audit_log")
        main.conn.commit()
        self.client = TestClient(main.app)

    def test_page_renders_card_human_language_and_seed_values(self):
        resp = self.client.get("/rule-cards")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn("規則卡", text)
        self.assertIn("素材疲勞頻率門檻", text)
        self.assertIn("同一個人平均看過這支素材幾次", text)  # 「這個門檻管什麼」說明
        for label in ("冷受眾開發", "再行銷", "小眾／精準受眾"):
            self.assertIn(label, text)
        # 種子值原樣顯示（DELETE 過 rule_card_value，落回程式預設值也要跟 ads.md 一致）
        self.assertIn('value="2.5"', text)
        self.assertIn('value="4"', text)  # 4.0 顯示成 4（_num_str 慣例不強制，input number 原生即可）
        self.assertIn('value="6"', text)
        self.assertIn('value="5"', text)
        self.assertIn('value="8"', text)

    def test_page_renders_budget_structure_card(self):
        """票 5：帳戶結構與預算配置門檻也是這頁的規則卡之一，可看可改可重設。"""
        resp = self.client.get("/rule-cards")
        text = resp.text
        self.assertIn("帳戶結構與預算配置門檻", text)
        self.assertIn('value="300"', text)
        self.assertIn('value="600"', text)
        self.assertIn('value="1200"', text)
        self.assertIn('value="0.7"', text)
        self.assertIn('value="0.8"', text)

    def test_page_renders_sample_size_card(self):
        """票 8：樣本數門檻（統計等級 vs 方向性判讀）也是這頁的規則卡之一。"""
        resp = self.client.get("/rule-cards")
        text = resp.text
        self.assertIn("樣本數門檻（統計等級 vs 方向性判讀）", text)
        self.assertIn('value="97000"', text)
        self.assertIn('value="31000"', text)
        self.assertIn('value="18000"', text)
        self.assertIn('value="8700"', text)
        self.assertIn('value="4000"', text)

    def test_edit_without_operator_redirects_to_set_operator(self):
        resp = self.client.post(
            "/rule-cards/ad_creative_fatigue/edit",
            data={"cold_warning": "3", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].startswith("/settings/operator"))

    def test_edit_saves_and_persists_after_restart(self):
        self.client.post("/settings/operator", data={"name": "測試員", "next": "/"})
        resp = self.client.post(
            "/rule-cards/ad_creative_fatigue/edit",
            data={"cold_warning": "3", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(rule_cards.get_value(main.conn, "ad_creative_fatigue", "cold_warning"), 3.0)

        # 模擬重啟：重建連線後改過的值仍在（真的落地在 DB 檔案）
        main.reopen_connection()
        self.assertEqual(rule_cards.get_value(main.conn, "ad_creative_fatigue", "cold_warning"), 3.0)

    def test_edit_invalid_number_shows_error_and_keeps_other_fields_unchanged(self):
        self.client.post("/settings/operator", data={"name": "測試員", "next": "/"})
        before = rule_cards.get_value(main.conn, "ad_creative_fatigue", "cold_danger")
        resp = self.client.post(
            "/rule-cards/ad_creative_fatigue/edit",
            data={"cold_warning": "不是數字", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請填一個大於 0 的數字", resp.text)
        # 打錯字的欄位失敗，整張卡不落地——包含本來合法的其他欄位
        self.assertEqual(rule_cards.get_value(main.conn, "ad_creative_fatigue", "cold_danger"), before)

    def test_reset_restores_default_after_edit(self):
        self.client.post("/settings/operator", data={"name": "測試員", "next": "/"})
        rule_cards.set_value(main.conn, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員")
        resp = self.client.post("/rule-cards/ad_creative_fatigue/reset", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(rule_cards.get_value(main.conn, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertIn("已將「素材疲勞頻率門檻」重設為預設值", resp.text)

    def test_unknown_card_key_404s(self):
        self.client.post("/settings/operator", data={"name": "測試員", "next": "/"})
        resp = self.client.post("/rule-cards/沒這張卡/reset")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
