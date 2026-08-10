# -*- coding: utf-8 -*-
"""app/tests/test_settings_hub.py — 設定中心分品牌路由（設定中心票 01）。

`/brands/{brand_id}/settings`（入口頁）與 `/brands/{brand_id}/settings/ads`（廣告層面詳細頁）。
沿用 app/tests/test_rule_cards_page.py 已退休前的暫存 DB／TestClient 慣例：真實 SQLite，
不 mock，直接打路由驗證行為；只測外部行為（頁面渲染出的文字/數字），不測資料表內部欄位順序。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_settings_hub_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import calendar_dismiss  # noqa: E402
from app.core import rule_cards  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


class SettingsHubEntryPageTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構設定茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_entry_page_shows_both_category_cards(self):
        resp = self.client.get(f"/brands/{self.bid}/settings")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn("廣告層面", text)
        self.assertIn("系統設定", text)

    def test_empty_state_shows_system_default_and_no_modified_time(self):
        """G14.8 空態：品牌從沒自訂過，入口頁摘要顯示系統預設值，不假裝有修改時間。"""
        resp = self.client.get(f"/brands/{self.bid}/settings")
        text = resp.text
        self.assertIn("尚未自訂過", text)
        self.assertIn("300", text)  # min_daily_per_group 系統預設 300

    def test_after_override_entry_page_shows_new_value_and_modified_time(self):
        rule_cards.set_value(main.conn, self.bid, "budget_structure", "min_daily_per_group",
                             450.0, actor=ACTOR)
        resp = self.client.get(f"/brands/{self.bid}/settings")
        text = resp.text
        self.assertIn("450", text)
        self.assertIn("上次修改", text)

    def test_unknown_brand_404s(self):
        resp = self.client.get("/brands/brand_沒這個品牌/settings")
        self.assertEqual(resp.status_code, 404)


class SettingsAdsPageTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構設定茶行二號", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_page_renders_all_four_cards_with_seed_values(self):
        resp = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        for title in ("帳戶結構與預算配置門檻", "樣本數門檻（統計等級 vs 方向性判讀）",
                      "素材疲勞頻率門檻", "檔期預算步調門檻"):
            self.assertIn(title, text)
        self.assertIn('value="2.5"', text)  # ad_creative_fatigue.cold_warning 系統預設值

    def test_no_customized_badge_when_untouched(self):
        """頁面說明句本身會提到「已自訂」這個詞，所以斷言比對帶分隔符的完整標籤，
        不是裸字串——確認沒有任何欄位真的被標成已自訂，不是巧合命中說明句。"""
        resp = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertNotIn("・ 已自訂", resp.text)

    def test_page_subtitle_mentions_customized_label_but_no_field_has_it(self):
        """反向證明前一個測試的斷言真的在測東西：頁面確實含「已自訂」這個詞
        （出現在說明句），但沒有任何欄位標籤帶著它。"""
        resp = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertIn("已自訂", resp.text)  # 說明句本身提到這個詞
        self.assertNotIn("・ 已自訂", resp.text)  # 但沒有欄位真的掛這個標籤

    def test_edit_saves_and_marks_customized(self):
        resp = self.client.post(
            f"/brands/{self.bid}/settings/ads/ad_creative_fatigue/edit",
            data={"cold_warning": "3", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_warning"), 3.0)
        page = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertIn("已自訂", page.text)

    def test_edit_works_without_operator_cookie(self):
        """ADR 0004：編輯不再要求先設定操作人。"""
        resp = self.client.post(
            f"/brands/{self.bid}/settings/ads/pacing/edit",
            data={"deviation_threshold_ratio": "0.2"}, follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        row = main.conn.execute(
            "SELECT actor FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id = ?"
            " ORDER BY created_at DESC LIMIT 1", (self.bid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], OPERATOR)

    def test_edit_persists_after_restart(self):
        self.client.post(f"/brands/{self.bid}/settings/ads/pacing/edit",
                         data={"deviation_threshold_ratio": "0.25"})
        main.reopen_connection()
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "pacing", "deviation_threshold_ratio"), 0.25)

    def test_edit_invalid_number_shows_error_and_keeps_other_fields_unchanged(self):
        before = rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_danger")
        resp = self.client.post(
            f"/brands/{self.bid}/settings/ads/ad_creative_fatigue/edit",
            data={"cold_warning": "不是數字", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請填一個大於 0 的數字", resp.text)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_danger"), before)

    def test_reset_restores_default_after_edit(self):
        rule_cards.set_value(main.conn, self.bid, "ad_creative_fatigue", "cold_warning", 9.9,
                             actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/settings/ads/ad_creative_fatigue/reset",
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(main.conn, self.bid, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertIn("已將「素材疲勞頻率門檻」重設為系統預設值", resp.text)

    def test_unknown_card_key_404s(self):
        resp = self.client.post(f"/brands/{self.bid}/settings/ads/沒這張卡/reset")
        self.assertEqual(resp.status_code, 404)

    def test_unknown_brand_404s(self):
        resp = self.client.get("/brands/brand_沒這個品牌/settings/ads")
        self.assertEqual(resp.status_code, 404)


class SettingsHubBrandIsolationTest(unittest.TestCase):
    """設定中心票 01 User Story 5：A 品牌的參數調整不影響 B 品牌。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_a = bi_repo.create_brand(main.conn, name="虛構隔離茶行 A", client_name=None,
                                            actor=ACTOR)
        self.brand_b = bi_repo.create_brand(main.conn, name="虛構隔離茶行 B", client_name=None,
                                            actor=ACTOR)

    def test_brand_a_edit_does_not_leak_into_brand_b_page(self):
        self.client.post(
            f"/brands/{self.brand_a['id']}/settings/ads/budget_structure/edit",
            data={"min_daily_per_group": "999", "medium_tier_floor": "600",
                  "large_tier_floor": "1200", "medium_validation_ratio": "0.7",
                  "large_scaling_ratio": "0.8"},
        )
        page_b = self.client.get(f"/brands/{self.brand_b['id']}/settings/ads")
        self.assertNotIn("999", page_b.text)
        self.assertIn('value="300"', page_b.text)  # B 品牌仍是系統預設值


class SettingsCalendarDismissTest(unittest.TestCase):
    """票 02-permanent-dismiss-category（ADR 0014 第三節，G14.9／G14.10）：「廣告層面」頁
    「節日提醒」小節，逐節日類別開關。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構節日提醒茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_empty_state_all_categories_show_reminding(self):
        """G14.10：空狀態下節日開關全部預設「提醒中」。"""
        resp = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn("節日提醒", text)
        self.assertIn("農曆新年", text)
        self.assertIn("提醒中", text)
        self.assertNotIn("已關閉", text)

    def test_toggle_off_marks_category_closed_and_persists(self):
        resp = self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny",
                                data={"enabled": "0"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(calendar_dismiss.list_dismissed(main.conn, self.bid), {"cny"})
        page = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertIn("已關閉", page.text)

    def test_toggle_off_does_not_affect_other_categories(self):
        self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny", data={"enabled": "0"})
        page = self.client.get(f"/brands/{self.bid}/settings/ads")
        # 情人節那一列仍是「提醒中」——用 claim-block-approved 這個只有開啟才會掛的 class
        # 當斷言依據，不是裸字串「提醒中」（頁面上每一列的說明句都可能提到這個詞）。
        self.assertIn("claim-block claim-block-approved", page.text)

    def test_toggle_on_after_off_restores_reminding(self):
        self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny", data={"enabled": "0"})
        resp = self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny",
                                data={"enabled": "1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(calendar_dismiss.list_dismissed(main.conn, self.bid), set())
        page = self.client.get(f"/brands/{self.bid}/settings/ads")
        self.assertNotIn("已關閉", page.text)

    def test_persists_after_restart(self):
        self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny", data={"enabled": "0"})
        main.reopen_connection()
        self.assertEqual(calendar_dismiss.list_dismissed(main.conn, self.bid), {"cny"})

    def test_unknown_category_404s(self):
        resp = self.client.post(f"/brands/{self.bid}/settings/ads/calendar/沒這個類別",
                                data={"enabled": "0"})
        self.assertEqual(resp.status_code, 404)

    def test_toggle_does_not_leak_across_brands(self):
        other = bi_repo.create_brand(main.conn, name="虛構節日提醒茶行二號", client_name=None,
                                     actor=ACTOR)
        self.client.post(f"/brands/{self.bid}/settings/ads/calendar/cny", data={"enabled": "0"})
        self.assertEqual(calendar_dismiss.list_dismissed(main.conn, other["id"]), set())


if __name__ == "__main__":
    unittest.main()
