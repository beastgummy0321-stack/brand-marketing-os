"""app/tests/test_settings_hub.py — 設定中心分品牌路由（設定中心票 01）。

`/brands/{brand_id}/settings`（入口頁）與 `/brands/{brand_id}/settings/ads`（廣告層面詳細頁）。
沿用 app/tests/test_rule_cards_page.py 已退休前的暫存 DB／TestClient 慣例：真實 SQLite，
不 mock，直接打路由驗證行為；只測外部行為（頁面渲染出的文字/數字），不測資料表內部欄位順序。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import calendar_dismiss, rule_cards
from app.core import db as coredb
from app.shared import web as shared_web
from app.shared.web import OPERATOR

ACTOR = "測試員"


# 舊頁脫鉤（T4 前置）：規則卡的讀寫改走 `/api/settings/rule-cards/**`，斷言驗的東西不變
# ——同一份 `rule_cards` 資料、同一個 customized 判斷（routes_settings.py 的 `_rule_card_json`
# 與舊頁 `_ads_cards_ctx` 共用 `f["value"] != f["default"]` 這一行）。
def _cards(client, brand_id: str) -> dict:
    resp = client.get(f"/api/settings/rule-cards/brands/{brand_id}")
    assert resp.status_code == 200, resp.text
    return {card["key"]: card for card in resp.json()["data"]["cards"]}


def _field(cards: dict, card_key: str, field_key: str) -> dict:
    return next(f for f in cards[card_key]["fields"] if f["key"] == field_key)


def _last_rule_card_audit(brand_id: str):
    """入口頁「上次修改」的資料來源（brand_web/routes_settings.py `_ads_last_modified`
    的同一句查詢）：從沒改過就沒有這一列。"""
    return web.conn.execute(
        "SELECT created_at, actor FROM audit_log WHERE entity_type = 'rule_card_value'"
        " AND brand_id = %s ORDER BY created_at DESC LIMIT 1", (brand_id,)).fetchone()


class SettingsHubEntryPageTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構設定茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_empty_state_shows_system_default_and_no_modified_time(self):
        """G14.8 空態：品牌從沒自訂過，入口頁摘要顯示系統預設值，不假裝有修改時間。"""
        field = _field(_cards(self.client, self.bid), "budget_structure", "min_daily_per_group")
        self.assertFalse(field["customized"])  # 尚未自訂過
        self.assertEqual(field["value"], 300)  # min_daily_per_group 系統預設 300
        self.assertIsNone(_last_rule_card_audit(self.bid))  # 沒有修改時間可拿

    def test_after_override_entry_page_shows_new_value_and_modified_time(self):
        rule_cards.set_value(web.conn, self.bid, "budget_structure", "min_daily_per_group",
                             450.0, actor=ACTOR)
        field = _field(_cards(self.client, self.bid), "budget_structure", "min_daily_per_group")
        self.assertEqual(field["value"], 450)
        self.assertIsNotNone(_last_rule_card_audit(self.bid))  # 有「上次修改」可顯示

    def test_unknown_brand_404s(self):
        # 入口頁的 404 來自 require_brand 這道守門（brand_web/routes_settings.py:65），
        # 這裡直接驗那道守門本身，不再靠舊頁網址。
        with self.assertRaises(shared_web.NotFoundKind) as caught:
            shared_web.require_brand("brand_沒這個品牌")
        self.assertEqual(caught.exception.status_code, 404)


class SettingsAdsPageTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構設定茶行二號", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_page_renders_all_four_cards_with_seed_values(self):
        cards = _cards(self.client, self.bid)
        titles = {card["title"] for card in cards.values()}
        for title in ("帳戶結構與預算配置門檻", "樣本數門檻（統計等級 vs 方向性判讀）",
                      "素材疲勞頻率門檻", "檔期預算步調門檻"):
            self.assertIn(title, titles)
        # ad_creative_fatigue.cold_warning 系統預設值（舊頁是輸入框的 value="2.5"）
        self.assertEqual(_field(cards, "ad_creative_fatigue", "cold_warning")["value"], 2.5)

    def test_no_customized_badge_when_untouched(self):
        """原本比對帶分隔符的完整標籤「・ 已自訂」以避開說明句的巧合命中；改走 API 之後
        直接看每個欄位的 customized 旗標（那個標籤就是照它掛的），連巧合的可能都沒有。"""
        cards = _cards(self.client, self.bid)
        self.assertFalse(any(f["customized"] for card in cards.values() for f in card["fields"]))

    def test_edit_saves_and_marks_customized(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/ad_creative_fatigue",
            json={"cold_warning": "3", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "ad_creative_fatigue", "cold_warning"), 3.0)
        cards = _cards(self.client, self.bid)
        self.assertTrue(_field(cards, "ad_creative_fatigue", "cold_warning")["customized"])

    def test_edit_works_without_operator_cookie(self):
        """ADR 0004：編輯不再要求先設定操作人。"""
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/pacing",
            json={"deviation_threshold_ratio": "0.2"},
        )
        self.assertEqual(resp.status_code, 200)
        row = _last_rule_card_audit(self.bid)
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], OPERATOR)

    def test_edit_persists_after_restart(self):
        """ADR 0027：不再有「重開連線」這回事了（連線池按 request 借連線）——改成從一條
        全新借來的連線讀回，證明真的落庫，不是只留在寫入那個 request 的連線快取裡。"""
        self.client.post(f"/api/settings/rule-cards/brands/{self.bid}/pacing",
                         json={"deviation_threshold_ratio": "0.25"})
        with coredb.connection() as fresh:
            self.assertEqual(
                rule_cards.get_value(fresh, self.bid, "pacing", "deviation_threshold_ratio"), 0.25)

    def test_edit_invalid_number_shows_error_and_keeps_other_fields_unchanged(self):
        before = rule_cards.get_value(web.conn, self.bid, "ad_creative_fatigue", "cold_danger")
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/ad_creative_fatigue",
            json={"cold_warning": "不是數字", "cold_danger": "5", "retargeting_warning": "4",
                  "retargeting_danger": "6", "niche_warning": "5", "niche_danger": "8"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請填一個大於 0 的數字", resp.json()["field_errors"]["cold_warning"])
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "ad_creative_fatigue", "cold_danger"), before)

    def test_reset_restores_default_after_edit(self):
        rule_cards.set_value(web.conn, self.bid, "ad_creative_fatigue", "cold_warning", 9.9,
                             actor=ACTOR)
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/ad_creative_fatigue/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "ad_creative_fatigue", "cold_warning"), 2.5)
        # 舊頁靠 flash 句「已將『素材疲勞頻率門檻』重設為系統預設值」證明重設的是這張卡、
        # 且回到系統預設；API 回的是同一件事的資料版：這張卡的欄位全部不再是「已自訂」。
        card = resp.json()["data"]
        self.assertEqual(card["title"], "素材疲勞頻率門檻")
        self.assertFalse(any(f["customized"] for f in card["fields"]))

    def test_unknown_card_key_404s(self):
        resp = self.client.post(f"/api/settings/rule-cards/brands/{self.bid}/沒這張卡/reset")
        self.assertEqual(resp.status_code, 404)

    def test_unknown_brand_404s(self):
        resp = self.client.get("/api/settings/rule-cards/brands/brand_沒這個品牌")
        self.assertEqual(resp.status_code, 404)


class SettingsHubBrandIsolationTest(unittest.TestCase):
    """設定中心票 01 User Story 5：A 品牌的參數調整不影響 B 品牌。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand_a = bi_repo.create_brand(web.conn, name="虛構隔離茶行 A", client_name=None,
                                            actor=ACTOR)
        self.brand_b = bi_repo.create_brand(web.conn, name="虛構隔離茶行 B", client_name=None,
                                            actor=ACTOR)

    def test_brand_a_edit_does_not_leak_into_brand_b_page(self):
        self.client.post(
            f"/api/settings/rule-cards/brands/{self.brand_a['id']}/budget_structure",
            json={"min_daily_per_group": "999", "medium_tier_floor": "600",
                  "large_tier_floor": "1200", "medium_validation_ratio": "0.7",
                  "large_scaling_ratio": "0.8"},
        )
        field_b = _field(_cards(self.client, self.brand_b["id"]),
                         "budget_structure", "min_daily_per_group")
        self.assertNotEqual(field_b["value"], 999)
        self.assertEqual(field_b["value"], 300)  # B 品牌仍是系統預設值


class SettingsCalendarDismissTest(unittest.TestCase):
    """票 02-permanent-dismiss-category（ADR 0014 第三節，G14.9／G14.10）：「廣告層面」頁
    「節日提醒」小節，逐節日類別開關。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構節日提醒茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_empty_state_all_categories_show_reminding(self):
        """G14.10：空狀態下節日開關全部預設「提醒中」。

        舊頁每一列的「提醒中／已關閉」就是照 `list_dismissed()` 有沒有這個類別掛的
        （routes_settings.py `_calendar_categories_ctx`），這裡直接驗那份現況。"""
        categories = calendar_dismiss.list_categories()
        self.assertIn("農曆新年", {cat["label"] for cat in categories})
        # 一個都沒關掉＝每一列都是「提醒中」，沒有任何一列是「已關閉」
        self.assertEqual(calendar_dismiss.list_dismissed(web.conn, self.bid), set())

    def test_toggle_off_marks_category_closed_and_persists(self):
        calendar_dismiss.dismiss(web.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(web.conn, self.bid), {"cny"})

    def test_toggle_on_after_off_restores_reminding(self):
        calendar_dismiss.dismiss(web.conn, self.bid, "cny")
        calendar_dismiss.undismiss(web.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(web.conn, self.bid), set())

    def test_persists_after_restart(self):
        """ADR 0027：不再有「重開連線」這回事了——改成從一條全新借來的連線讀回。"""
        calendar_dismiss.dismiss(web.conn, self.bid, "cny")
        with coredb.connection() as fresh:
            self.assertEqual(calendar_dismiss.list_dismissed(fresh, self.bid), {"cny"})

    def test_toggle_does_not_leak_across_brands(self):
        other = bi_repo.create_brand(web.conn, name="虛構節日提醒茶行二號", client_name=None,
                                     actor=ACTOR)
        calendar_dismiss.dismiss(web.conn, self.bid, "cny")
        self.assertEqual(calendar_dismiss.list_dismissed(web.conn, other["id"]), set())


# 新殼 JSON API：/api/settings/calendar/brands/{brand_id}/**（節日提醒永久關閉開關搬進新殼，
# 舊頁邏輯照舊沿用 `_calendar_categories_ctx()`／`calendar_dismiss`，這裡只驗 HTTP 層行為）。
class SettingsCalendarApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構節日提醒新殼茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def _categories(self):
        resp = self.client.get(f"/api/settings/calendar/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200, resp.text)
        return {c["category"]: c for c in resp.json()["data"]["categories"]}

    def test_list_defaults_to_all_enabled(self):
        categories = self._categories()
        self.assertIn("cny", categories)
        self.assertTrue(all(c["enabled"] for c in categories.values()))

    def test_toggle_off_disables_and_is_reflected_in_list(self):
        resp = self.client.post(f"/api/settings/calendar/brands/{self.bid}/cny", json={"enabled": False})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["data"]["enabled"])
        self.assertFalse(self._categories()["cny"]["enabled"])

    def test_toggle_on_after_off_restores(self):
        self.client.post(f"/api/settings/calendar/brands/{self.bid}/cny", json={"enabled": False})
        resp = self.client.post(f"/api/settings/calendar/brands/{self.bid}/cny", json={"enabled": True})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["data"]["enabled"])
        self.assertTrue(self._categories()["cny"]["enabled"])

    def test_unknown_category_404s(self):
        resp = self.client.post(f"/api/settings/calendar/brands/{self.bid}/沒這個類別", json={"enabled": False})
        self.assertEqual(resp.status_code, 404)

    def test_unknown_brand_404s(self):
        resp = self.client.get("/api/settings/calendar/brands/沒這個品牌")
        self.assertEqual(resp.status_code, 404)

    def test_toggle_off_one_category_does_not_affect_others(self):
        self.client.post(f"/api/settings/calendar/brands/{self.bid}/cny", json={"enabled": False})
        categories = self._categories()
        self.assertFalse(categories["cny"]["enabled"])
        others = [c for key, c in categories.items() if key != "cny"]
        self.assertTrue(others)
        self.assertTrue(all(c["enabled"] for c in others))


if __name__ == "__main__":
    unittest.main()
