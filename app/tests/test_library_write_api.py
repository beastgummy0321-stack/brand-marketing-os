"""app/tests/test_library_write_api.py — 品牌智庫六分頁寫入動作的 /api 版本
（`app/brand_web/routes_library_write.py`）。

驗證規則與錯誤訊息照抄 `app/brand_web/routes.py` 舊版表單 handler（見該檔逐支
handler），這裡只守路由層：happy path 有沒有真的寫進 DB、驗證擋不擋得住壞輸入、
查無此 id 是不是回 404。比照 `test_brand_delete_routes.py` 的慣例。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
import app.storage as storage
from app.brand_intelligence import repository as repo
from app.core.db import DEV_ORG_ID  # noqa: E402

_SEQ = [0]
ACTOR = "本人"


class LibraryWriteApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def _new_brand(self, prefix: str) -> str:
        _SEQ[0] += 1
        name = f"{prefix}{_SEQ[0]}"
        return repo.create_brand(web.conn, name=name, client_name=None, actor=ACTOR, org_id=DEV_ORG_ID)["id"]

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

    def test_fact_create_refuses_policy_type(self):
        """F42-I01: 「全店政策」 is written only by brand onboarding -- the library's free-form
        fact route refuses it with a field error (400), never a 500 from the DB CHECK."""
        brand_id = self._new_brand("事實品牌")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts",
            json={"fact_type": "policy", "fact_key": "ship_threshold", "label": "滿額免運",
                  "value": "滿 NT$999 免運", "status": "confirmed"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("fact_type", resp.json()["errors"])
        self.assertEqual(repo.list_brand_facts(web.conn, brand_id), [])

    def test_fact_edit_refuses_policy_both_ways(self):
        """F42-I01: a fact cannot be turned into a policy, and a policy fact cannot be edited
        through the library (its sentence is composed from the registry params)."""
        brand_id = self._new_brand("事實品牌")
        fact = repo.create_brand_fact(web.conn, brand_id, actor=ACTOR, fact_type="tone",
                                       label="語調", value="活潑", status="pending")
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts/{fact['id']}/edit",
            json={"fact_type": "policy", "label": "x", "value": "y"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("fact_type", resp.json()["errors"])

        [policy] = repo.save_brand_policies(
            web.conn, brand_id, [{"key": "ship_threshold", "params": {"threshold": 999}}], actor=ACTOR)
        resp = self.client.post(
            f"/api/library/brands/{brand_id}/facts/{policy['id']}/edit",
            json={"fact_type": "positioning", "label": "x", "value": "y"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(repo.get_brand_fact(web.conn, brand_id, policy["id"])["value"], "滿 NT$999 免運")

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
        key = f"{DEV_ORG_ID}/brands/{brand_id}/assets/oas_test/logo.png"
        storage.put(org_id=DEV_ORG_ID, key=key, filename="logo.png", content=b"fake image bytes",
                    content_type="image/png")
        self.addCleanup(storage.delete, org_id=DEV_ORG_ID, key=key)
        asset = repo.create_official_asset(web.conn, brand_id, actor=ACTOR, asset_kind="logo",
                                            storage_key=key)
        resp = self.client.post(f"/api/library/brands/{brand_id}/assets/{asset['id']}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(repo.get_official_asset(web.conn, brand_id, asset["id"]))
        with self.assertRaises(storage.NotFound):
            storage.get(org_id=DEV_ORG_ID, key=key)

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
                  "market_region": "TW", "conversion_goal": "purchase"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["name"], "新名稱")
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

    # ---- F34-I01（Contract R）：適用法規 ----

    def test_regulatory_regime_put_sets_and_clears(self):
        brand_id = self._new_brand("法規品牌")
        resp = self.client.put(
            f"/api/library/brands/{brand_id}/regulatory-regime", json={"value": "food_tw"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], {"regulatory_regime": "food_tw"})
        self.assertEqual(repo.get_brand(web.conn, brand_id)["regulatory_regime"], "food_tw")

        resp = self.client.put(
            f"/api/library/brands/{brand_id}/regulatory-regime", json={"value": None},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], {"regulatory_regime": None})
        self.assertIsNone(repo.get_brand(web.conn, brand_id)["regulatory_regime"])

    def test_regulatory_regime_put_rejects_unknown_value(self):
        brand_id = self._new_brand("法規品牌")
        resp = self.client.put(
            f"/api/library/brands/{brand_id}/regulatory-regime", json={"value": "drug"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("value", resp.json()["errors"])
        self.assertIsNone(repo.get_brand(web.conn, brand_id)["regulatory_regime"])


class AssetKindLabelTest(unittest.TestCase):
    """F07-I13 item 14: `product_photo` 的人話標籤要在後端與前端一致（app/core/vocab.py:74，
    frontend/src/lib/libraryApi.ts:157）——沒有既有測試讀過任一邊，改回 `產品照` 仍全綠。"""

    def test_backend_label_is_reference_photo(self):
        from app.core import vocab
        self.assertEqual(dict(vocab.ASSET_KINDS)["product_photo"], "商品參考照")

    def test_frontend_label_is_reference_photo(self):
        import pathlib
        text = (
            pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "lib" / "libraryApi.ts"
        ).read_text(encoding="utf-8")
        self.assertEqual(text.count('["product_photo", "商品參考照"]'), 1)

    def test_brand_photo_kinds_match_frontend(self):
        """F42-I01: the three brand-photo kinds and the 「全店政策」 fact type carry the same
        label on both sides."""
        import pathlib

        from app.core import vocab
        text = (
            pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "lib" / "libraryApi.ts"
        ).read_text(encoding="utf-8")
        for key in ("store", "team", "brand_image"):
            self.assertIn(f'["{key}", "{dict(vocab.ASSET_KINDS)[key]}"]', text)
        self.assertIn(f'["policy", "{dict(vocab.BRAND_FACT_TYPES)["policy"]}"]', text)


if __name__ == "__main__":
    unittest.main()
