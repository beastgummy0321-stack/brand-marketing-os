"""app/tests/test_settings_hub.py — 設定中心分品牌路由（設定中心票 01）。

`/brands/{brand_id}/settings`（入口頁）與 `/brands/{brand_id}/settings/ads`（廣告層面詳細頁）。
沿用 app/tests/test_rule_cards_page.py 已退休前的暫存 DB／TestClient 慣例：真實 SQLite，
不 mock，直接打路由驗證行為；只測外部行為（頁面渲染出的文字/數字），不測資料表內部欄位順序。
"""

import unittest
from uuid import UUID

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.identity import ActorContext
from app.shared import web as shared_web

ACTOR = "測試員"
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"  # conftest.py 預設 dev token 對應的種子使用者
_DUMMY_ACTOR = ActorContext(
    user_id=UUID(DEV_USER_ID), org_id="org_dev", role="owner", email="dev@local"
)


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
                                          actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_empty_state_shows_system_default_and_no_modified_time(self):
        """G14.8 空態：品牌從沒自訂過，入口頁摘要顯示系統預設值，不假裝有修改時間。"""
        field = _field(_cards(self.client, self.bid), "rule_prompt_cap", "max_active_rules")
        self.assertFalse(field["customized"])  # 尚未自訂過
        self.assertEqual(field["value"], 20)  # max_active_rules 系統預設 20
        self.assertIsNone(_last_rule_card_audit(self.bid))  # 沒有修改時間可拿

    def test_after_override_entry_page_shows_new_value_and_modified_time(self):
        rule_cards.set_value(web.conn, self.bid, "rule_prompt_cap", "max_active_rules",
                             45.0, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        field = _field(_cards(self.client, self.bid), "rule_prompt_cap", "max_active_rules")
        self.assertEqual(field["value"], 45)
        self.assertIsNotNone(_last_rule_card_audit(self.bid))  # 有「上次修改」可顯示

    def test_unknown_brand_404s(self):
        # 入口頁的 404 來自 require_brand 這道守門（brand_web/routes_settings.py:65），
        # 這裡直接驗那道守門本身，不再靠舊頁網址。
        with self.assertRaises(shared_web.NotFoundKind) as caught:
            shared_web.require_brand("brand_沒這個品牌", _DUMMY_ACTOR)
        self.assertEqual(caught.exception.status_code, 404)


class SettingsAdsPageTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構設定茶行二號", client_name=None,
                                          actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.bid = self.brand["id"]

    def test_page_renders_all_three_cards_with_seed_values(self):
        # dead-code-sweep 票 04（2026-08-30）刪了「規則有效期」卡（規則不再過期），剩三張。
        # F03-I17：預算搬進投放中心（ruling 4），設定頁不再有「檔期日預算」這張卡——
        # 卡片定義沒刪（get_value 照常可用），只是從設定頁清單藏起來。
        cards = _cards(self.client, self.bid)
        titles = {card["title"] for card in cards.values()}
        for title in ("品牌智庫規則上限", "毛利率（打平線用）", "檔期方案數量上下限"):
            self.assertIn(title, titles)
        self.assertNotIn("規則有效期", titles)
        self.assertNotIn("檔期日預算", titles)
        self.assertEqual(_field(cards, "schedule_plan_count", "plan_count_max")["value"], 5.0)

    def test_no_customized_badge_when_untouched(self):
        """原本比對帶分隔符的完整標籤「・ 已自訂」以避開說明句的巧合命中；改走 API 之後
        直接看每個欄位的 customized 旗標（那個標籤就是照它掛的），連巧合的可能都沒有。"""
        cards = _cards(self.client, self.bid)
        self.assertFalse(any(f["customized"] for card in cards.values() for f in card["fields"]))

    def test_edit_saves_and_marks_customized(self):
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count",
            json={"plan_count_min": "2", "plan_count_max": "8"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_min"), 2.0)
        cards = _cards(self.client, self.bid)
        self.assertTrue(_field(cards, "schedule_plan_count", "plan_count_min")["customized"])

    def test_edit_records_the_authenticated_user_as_actor(self):
        """票 03-1：ADR 0004 的「不再要求先設定操作人」還是對的，但具名對象換成登入者
        （dev token 對應的種子使用者），不再是固定的 OPERATOR 常數。"""
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/rule_prompt_cap",
            json={"max_active_rules": "30"},
        )
        self.assertEqual(resp.status_code, 200)
        row = _last_rule_card_audit(self.bid)
        self.assertIsNotNone(row)
        self.assertEqual(row["actor"], DEV_USER_ID)

    def test_edit_persists_after_restart(self):
        """ADR 0027：不再有「重開連線」這回事了（連線池按 request 借連線）——改成從一條
        全新借來的連線讀回，證明真的落庫，不是只留在寫入那個 request 的連線快取裡。"""
        self.client.post(f"/api/settings/rule-cards/brands/{self.bid}/rule_prompt_cap",
                         json={"max_active_rules": "30"})
        with coredb.connection() as fresh:
            self.assertEqual(
                rule_cards.get_value(fresh, self.bid, "rule_prompt_cap", "max_active_rules"), 30.0)

    def test_edit_invalid_number_shows_error_and_keeps_other_fields_unchanged(self):
        before = rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max")
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count",
            json={"plan_count_min": "不是數字", "plan_count_max": "8"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請填一個大於 0 的數字", resp.json()["field_errors"]["plan_count_min"])
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max"), before)

    def test_reset_restores_default_after_edit(self):
        rule_cards.set_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max", 9.0,
                             actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        resp = self.client.post(
            f"/api/settings/rule-cards/brands/{self.bid}/schedule_plan_count/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            rule_cards.get_value(web.conn, self.bid, "schedule_plan_count", "plan_count_max"), 5.0)
        # 舊頁靠 flash 句「已將『檔期方案數量上下限』重設為系統預設值」證明重設的是這張卡、
        # 且回到系統預設；API 回的是同一件事的資料版：這張卡的欄位全部不再是「已自訂」。
        card = resp.json()["data"]
        self.assertEqual(card["title"], "檔期方案數量上下限")
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
                                            actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        self.brand_b = bi_repo.create_brand(web.conn, name="虛構隔離茶行 B", client_name=None,
                                            actor=ACTOR, org_id=coredb.DEV_ORG_ID)

    def test_brand_a_edit_does_not_leak_into_brand_b_page(self):
        self.client.post(
            f"/api/settings/rule-cards/brands/{self.brand_a['id']}/rule_prompt_cap",
            json={"max_active_rules": "999"},
        )
        field_b = _field(_cards(self.client, self.brand_b["id"]),
                         "rule_prompt_cap", "max_active_rules")
        self.assertNotEqual(field_b["value"], 999)
        self.assertEqual(field_b["value"], 20)  # B 品牌仍是系統預設值
