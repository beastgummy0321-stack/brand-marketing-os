# -*- coding: utf-8 -*-
"""app/tests/test_library_write_api.py — 品牌智庫六分頁寫入動作的 /api 版本
（`app/brand_web/routes_library_write.py`）。

驗證規則與錯誤訊息照抄 `app/brand_web/routes.py` 舊版表單 handler（見該檔逐支
handler），這裡只守路由層：happy path 有沒有真的寫進 DB、驗證擋不擋得住壞輸入、
查無此 id 是不是回 404。比照 `test_brand_delete_routes.py` 的慣例。
"""

import tempfile
import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo

_SEQ = [0]
ACTOR = "本人"


class LibraryWriteApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, prefix: str) -> str:
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        return repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR)["id"]

    # ---- 品牌事實 ----

    def test_fact_create_happy_path(self):
        brand_id = self._new_brand("事實品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "positioning", "label": "定位", "value": "平價家用",
                  "status": "pending", "source_reference": ""},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["label"], "定位")
        self.assertEqual(data["status"], "pending")
        self.assertIsNotNone(repo.get_brand_fact(web.conn, brand_id, data["id"]))

    def test_fact_create_rejects_missing_label(self):
        brand_id = self._new_brand("事實品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "positioning", "label": "", "value": "平價家用", "status": "pending"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("label", resp.json()["errors"])

    def test_fact_update_unknown_id_404(self):
        brand_id = self._new_brand("事實品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts/does-not-exist/edit",
            json={"fact_type": "positioning", "label": "x", "value": "y"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_fact_confirm_requires_confirmed_by(self):
        brand_id = self._new_brand("事實品牌")
        fact = repo.create_brand_fact(web.conn, brand_id, actor=ACTOR, fact_type="tone",
                                       label="語調", value="活潑", status="pending")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts/{fact['id']}/confirm", json={"confirmed_by": ""},
        )
        self.assertEqual(resp.status_code, 400)
        resp2 = self.client.post(
            f"/api/library/brands/{brand_id}/facts/{fact['id']}/confirm",
            json={"confirmed_by": "小美"},
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["data"]["status"], "confirmed")

    def test_fact_delete_removes_row(self):
        brand_id = self._new_brand("事實品牌")
        fact = repo.create_brand_fact(web.conn, brand_id, actor=ACTOR, fact_type="tone",
                                       label="語調", value="活潑", status="pending")
        resp = self.client.post(f"/api/library/brands/{brand_id}/facts/{fact['id']}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(repo.get_brand_fact(web.conn, brand_id, fact["id"]))

    # ---- 限制規則 ----

    def test_rule_create_happy_path_and_delete(self):
        brand_id = self._new_brand("規則品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/rules",
            json={"rule_type": "tone", "content": "不能用驚嘆號", "severity": "hard"},
        )
        self.assertEqual(resp.status_code, 200)
        rule_id = resp.json()["data"]["id"]
        self.assertIsNotNone(repo.get_rule(web.conn, brand_id, rule_id))

        del_resp = self.client.post(f"/api/library/brands/{brand_id}/rules/{rule_id}/delete")
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(repo.get_rule(web.conn, brand_id, rule_id))

    def test_rule_create_rejects_bad_severity(self):
        brand_id = self._new_brand("規則品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/rules",
            json={"rule_type": "tone", "content": "內容", "severity": "極嚴重"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("severity", resp.json()["errors"])

    def test_rule_delete_unknown_id_404(self):
        brand_id = self._new_brand("規則品牌")
        resp = self.client.post(f"/api/library/brands/{brand_id}/rules/does-not-exist/delete")
        self.assertEqual(resp.status_code, 404)

    # ---- 宣稱 ----

    def test_claim_create_happy_path_and_edit(self):
        brand_id = self._new_brand("宣稱品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims",
            json={"claim_text": "有機認證", "claim_type": "approved"},
        )
        self.assertEqual(resp.status_code, 200)
        claim_id = resp.json()["data"]["id"]

        edit_resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims/{claim_id}/edit",
            json={"claim_text": "有機認證（更新）", "claim_type": "approved"},
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.json()["data"]["claim_text"], "有機認證（更新）")

    def test_claim_create_flags_statutory_wordlist_hit_but_still_saves(self):
        """票 03-claim-wordlist-todo（決議 2026-08-23）：存宣稱不擋，只標紅字警告——
        任何類別（這裡用「可用」，正是 012 audit 踩到的破口）命中內建法定詞庫都要在
        `wordlist_hits` 帶回來。"""
        brand_id = self._new_brand("違規詞品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims",
            json={"claim_text": "根治關節炎，七天見效不復發", "claim_type": "approved"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIsNotNone(repo.get_claim(web.conn, brand_id, data["id"]))
        terms = {hit["term"] for hit in data["wordlist_hits"]}
        self.assertIn("根治", terms)

    def test_claim_create_without_statutory_term_has_empty_hits(self):
        brand_id = self._new_brand("乾淨宣稱品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims",
            json={"claim_text": "使用天然原料", "claim_type": "approved"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["wordlist_hits"], [])

    def test_claim_create_rejects_bad_type(self):
        brand_id = self._new_brand("宣稱品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims",
            json={"claim_text": "文字", "claim_type": "亂填"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("claim_type", resp.json()["errors"])

    def test_claim_edit_unknown_id_404(self):
        brand_id = self._new_brand("宣稱品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/claims/does-not-exist/edit",
            json={"claim_text": "x", "claim_type": "approved"},
        )
        self.assertEqual(resp.status_code, 404)

    # ---- 官方素材 ----

    def test_asset_delete_happy_path_and_unknown_id(self):
        brand_id = self._new_brand("素材品牌")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake image bytes")
            file_path = f.name
        asset = repo.create_official_asset(web.conn, brand_id, actor=ACTOR, asset_kind="logo",
                                            file_path=file_path)
        resp = self.client.post(f"/api/library/brands/{brand_id}/assets/{asset['id']}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(repo.get_official_asset(web.conn, brand_id, asset["id"]))

        resp_404 = self.client.post(f"/api/library/brands/{brand_id}/assets/does-not-exist/delete")
        self.assertEqual(resp_404.status_code, 404)

    # ---- 自有渠道 ----

    def test_channel_create_edit_delete_round_trip(self):
        brand_id = self._new_brand("渠道品牌")
        create_resp = self.client.post(
            f"/api/library/brands/{brand_id}/channels",
            json={"channel_type": "website", "name": "官網", "identifier": "https://example.com",
                  "status": "active"},
        )
        self.assertEqual(create_resp.status_code, 200)
        channel_id = create_resp.json()["data"]["id"]

        edit_resp = self.client.post(
            f"/api/library/brands/{brand_id}/channels/{channel_id}/edit",
            json={"channel_type": "website", "name": "官網（新）", "identifier": "https://example.com",
                  "status": "inactive"},
        )
        self.assertEqual(edit_resp.status_code, 200)
        self.assertEqual(edit_resp.json()["data"]["name"], "官網（新）")

        del_resp = self.client.post(f"/api/library/brands/{brand_id}/channels/{channel_id}/delete")
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(repo.get_channel(web.conn, brand_id, channel_id))

    def test_channel_create_rejects_missing_identifier(self):
        brand_id = self._new_brand("渠道品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/channels",
            json={"channel_type": "website", "name": "官網", "identifier": ""},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("identifier", resp.json()["errors"])

    def test_channel_edit_unknown_id_404(self):
        brand_id = self._new_brand("渠道品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/channels/does-not-exist/edit",
            json={"channel_type": "website", "name": "x", "identifier": "y"},
        )
        self.assertEqual(resp.status_code, 404)

    # ---- 顧客原話封存／刪除 ----

    def _new_customer_voice(self, brand_id: str) -> dict:
        return repo.create_customer_voice(
            web.conn, brand_id, actor=ACTOR, raw_text="包裝很難拆", source_channel="shopee",
            source_type="manual", extraction=[],
        )

    def test_customer_voice_archive_toggle(self):
        brand_id = self._new_brand("原話品牌")
        cv = self._new_customer_voice(brand_id)
        resp = self.client.post(f"/api/library/brands/{brand_id}/customer-voice/{cv['id']}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["status"], "archived")

        resp2 = self.client.post(f"/api/library/brands/{brand_id}/customer-voice/{cv['id']}/archive")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["data"]["status"], "active")

    def test_customer_voice_delete_and_unknown_id(self):
        brand_id = self._new_brand("原話品牌")
        cv = self._new_customer_voice(brand_id)
        resp = self.client.post(f"/api/library/brands/{brand_id}/customer-voice/{cv['id']}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(repo.get_customer_voice(web.conn, brand_id, cv["id"]))

        resp_404 = self.client.post(
            f"/api/library/brands/{brand_id}/customer-voice/does-not-exist/delete",
        )
        self.assertEqual(resp_404.status_code, 404)

    # ---- 品牌資料側板 ----

    def test_brand_edit_happy_path(self):
        brand_id = self._new_brand("編輯品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/edit",
            json={"name": "新名稱", "client_name": "客戶", "status": "active", "persona": "kol",
                  "market_region": "TW", "conversion_goal": "purchase", "industry": "food_beverage"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["name"], "新名稱")
        self.assertEqual(data["industry"], "food_beverage")
        updated = repo.get_brand(web.conn, brand_id)
        self.assertEqual(updated["name"], "新名稱")
        self.assertEqual(updated["conversion_goal"], "purchase")

    def test_brand_edit_rejects_empty_name(self):
        brand_id = self._new_brand("編輯品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/edit",
            json={"name": "", "status": "active"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("name", resp.json()["errors"])

    def test_brand_edit_unknown_brand_404(self):
        resp = self.client.post(
            "/api/library/brands/does-not-exist/edit",
            json={"name": "x", "status": "active"},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
