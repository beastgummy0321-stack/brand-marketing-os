"""app/tests/test_intake_onboarding_api.py — brand onboarding HTTP contract (F42-I04).

`/api/intake/brands/{b}/onboarding/*` (app/intake/routes_onboarding_api.py). Per step: the GET
shape with no prefill (`source="none"`), with a stored `intake_draft.prefill_json`
(`source="ai"` + note) and after the PUT (`source="saved"`); PUT validation (400 + a Chinese
message); re-entry on a completed brand and on a brand that never had a draft; cross-org
refusal; the connector list with and without a bound Meta account. No LLM call anywhere.
Brand names are fictional.
"""

import io
import os
import unittest
import uuid
from uuid import uuid4

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-onboarding-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.intake as intake_module  # noqa: E402
import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app import storage  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.identity import repository as identity_repo  # noqa: E402
from app.intake import repository as ir  # noqa: E402
from app.intake import state  # noqa: E402
from app.meta import repository as meta_repo  # noqa: E402

from .identity_test_helpers import mint_hs256  # noqa: E402

_SEQ = [0]

_PREFILL = {
    "positioning": {"value": "給忙到沒空吃飯的人的維他命軟糖", "note": "首頁"},
    "tone": {"values": ["親切", "直接"], "note": "從網站文字判斷"},
    "visual": {"value": "明亮、自然光、暖色系", "note": "品牌照片"},
    "proof": [{"fact_key": "founder_voice", "text": "創辦人是健身教練，吞不下藥丸才自己做軟糖",
               "note": "about 頁"}],
    "policies": [{"key": "ship_threshold", "params": {"threshold": 999}, "note": "運送說明頁"}],
    "products": [{"name": "綜合維他命軟糖", "url": None}],
    "not_found": ["媒體報導"],
}


# A JPEG frame header (1x1): photo uploads are checked by content and header (F47 Contract A).
_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffc0000b080001000101011100ffd9")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)

    # -- helpers ------------------------------------------------------------

    def _name(self) -> str:
        _SEQ[0] += 1
        return f"虛構品牌建檔測試{_SEQ[0]}"

    def _create(self, **data) -> str:
        resp = self.client.post("/api/intake/brands", data={"brand_name": self._name(), **data})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["brand_id"]

    def _url(self, bid: str, path: str = "") -> str:
        return f"/api/intake/brands/{bid}/onboarding{path}"

    def _get(self, bid: str, path: str = "", **kw) -> dict:
        resp = self.client.get(self._url(bid, path), **kw)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]

    def _put(self, bid: str, path: str, body: dict):
        return self.client.put(self._url(bid, path), json=body)

    def _store_prefill(self, bid: str, prefill: dict = _PREFILL) -> None:
        draft = ir.get_active_draft(web.conn, bid)
        assert draft is not None
        ir.update_draft(web.conn, bid, draft["id"], prefill_json=prefill)

    def _complete(self, bid: str) -> None:
        resp = self.client.post(self._url(bid, "/complete"))
        self.assertEqual(resp.status_code, 200, resp.text)

    def _upload(self, name: str = "t.jpg") -> str:
        resp = self.client.post("/api/intake/photos",
                                files={"photo": (name, io.BytesIO(_JPEG), "image/jpeg")})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json()["token"]
        key = state.get_pending_photos(token)[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=coredb.DEV_ORG_ID, key=key)
        return token

    def _other_org_headers(self) -> dict:
        org_id = "org_intake_onboarding_test_b"
        web.conn.execute("INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
                         " ON CONFLICT (id) DO NOTHING", (org_id, org_id))
        user_id = uuid4()
        email = f"intake-onboarding-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return {"Authorization": f"Bearer {mint_hs256(sub=str(user_id), email=email)}",
                "X-Org-Id": org_id}


# ---------------------------------------------------------------------------
# GET "" / POST /complete / step numbering
# ---------------------------------------------------------------------------

class StatusTest(_Base):
    def test_name_only_brand_skips_the_scan_step(self):
        bid = self._create()
        data = self._get(bid)
        self.assertEqual(data, {"step": 3, "completed": False, "skipped_scan": True,
                                "prefill_status": "none", "prefill_error": None})

    def test_brand_with_a_url_starts_at_the_scan_step(self):
        bid = self._create(urls="https://example.com")
        data = self._get(bid)
        self.assertEqual(data["step"], 2)
        self.assertFalse(data["skipped_scan"])
        self._store_prefill(bid)
        self.assertEqual(self._get(bid)["prefill_status"], "done")

    def test_description_alone_does_not_start_a_scan(self):
        bid = self._create(description="一句測試用的品牌描述文字。")
        self.assertEqual(self._get(bid)["step"], 3)

    def test_complete_is_idempotent_and_reads_as_completed(self):
        bid = self._create()
        for _ in range(2):
            resp = self.client.post(self._url(bid, "/complete"))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["data"]["step"], 7)
            self.assertTrue(resp.json()["data"]["completed"])
        self.assertIsNone(ir.get_active_draft(web.conn, bid))

    def test_brand_that_never_had_a_draft_reads_as_completed(self):
        brand = bi_repo.create_brand(web.conn, org_id=coredb.DEV_ORG_ID, name=self._name(),
                                     client_name=None, actor="test")
        data = self._get(brand["id"])
        self.assertEqual(data["step"], 7)
        self.assertTrue(data["completed"])
        self.assertTrue(data["skipped_scan"])
        for path in ("/basics", "/identity", "/evidence", "/media", "/tools"):
            self._get(brand["id"], path)

    def test_seven_wizard_steps(self):
        self.assertEqual([label for _, label in state.WIZARD_STEPS],
                         ["基本", "AI 讀網站", "品牌是誰", "證據與政策", "素材", "接工具", "完成"])


# ---------------------------------------------------------------------------
# Step 1 基本 (POST /api/intake/brands + GET/PUT /basics)
# ---------------------------------------------------------------------------

class BasicsTest(_Base):
    def test_create_with_kinds_region_regime_makes_brand_photo_assets(self):
        logo, store = self._upload("logo.jpg"), self._upload("store.jpg")
        other = self._upload("x.jpg")
        bid = self._create(photo_tokens=[logo, store, other], photo_kinds=["logo", "store"],
                           market_region="TW", regulatory_regime="food_tw",
                           urls=["https://example.com", "https://example.com/about"])
        brand = bi_repo.get_brand(web.conn, bid)
        self.assertEqual((brand["market_region"], brand["regulatory_regime"]), ("TW", "food_tw"))
        assets = bi_repo.list_official_assets(web.conn, bid)
        self.assertEqual(sorted(a["asset_kind"] for a in assets), ["logo", "other", "store"])
        self.assertTrue(all(a["product_id"] is None for a in assets))
        data = self._get(bid, "/basics")
        self.assertEqual(data["urls"], ["https://example.com", "https://example.com/about"])
        self.assertEqual(data["regulatory_regime"], "food_tw")
        self.assertEqual([p["kind"] for p in data["photos"]], ["logo", "store", "other"])
        self.assertTrue(data["photos"][0]["url"].startswith(f"/brands/{bid}/assets/file/"))
        self.assertEqual(self._get(bid)["step"], 2)

    def test_create_refuses_six_urls_and_an_unknown_photo_kind(self):
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._name(), "urls": [f"https://example.com/{i}" for i in range(6)]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("最多 5 個", resp.json()["error"])
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._name(), "photo_tokens": ["pht_x"],
            "photo_kinds": ["product_photo"]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("照片種類", resp.json()["error"])

    def test_reentry_put_edits_brand_draft_and_photos(self):
        token = self._upload()
        bid = self._create(photo_tokens=token, photo_kinds="logo")
        self._complete(bid)
        new_token = self._upload("team.jpg")
        resp = self._put(bid, "/basics", {
            "name": "改過名字的虛構品牌", "urls": ["https://example.com/new"],
            "client_name": "某客戶",
            "description": "新的描述", "market_region": "TW", "regulatory_regime": "food_tw",
            "advertising_history": "none", "photo_ids": [], "photo_tokens": [new_token],
            "photo_kinds": ["team"]})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual(data["name"], "改過名字的虛構品牌")
        self.assertEqual(data["urls"], ["https://example.com/new"])
        self.assertEqual(data["description"], "新的描述")
        self.assertEqual(data["advertising_history"], "none")
        self.assertEqual([p["kind"] for p in data["photos"]], ["team"])
        self.assertIsNone(ir.get_active_draft(web.conn, bid))  # re-entry never reopens a draft

    def test_put_validation(self):
        bid = self._create()
        base = {"name": "虛構", "urls": [], "market_region": None, "regulatory_regime": None,
                "client_name": "", "description": ""}
        for patch, needle in (({"name": ""}, "品牌名稱"), ({"urls": ["ftp://x"]}, "網址"),
                              ({"regulatory_regime": "drug_us"}, "法規"),
                              ({"photo_ids": ["oas_missing"]}, "照片")):
            resp = self._put(bid, "/basics", {**base, **patch})
            self.assertEqual(resp.status_code, 400, patch)
            self.assertIn(needle, resp.json()["error"])

    def test_put_on_open_draft_advances_but_never_rewinds(self):
        bid = self._create(urls="https://example.com")
        body = {"name": "虛構", "urls": ["https://example.com"], "client_name": "",
                "description": "", "market_region": None, "regulatory_regime": None}
        self.assertEqual(self._put(bid, "/basics", body).status_code, 200)
        self.assertEqual(self._get(bid)["step"], 2)
        self._put(bid, "/media", {"media": "photo"})
        self.assertEqual(self._put(bid, "/basics", body).status_code, 200)
        self.assertEqual(self._get(bid)["step"], 6)


# ---------------------------------------------------------------------------
# Step 3 品牌是誰
# ---------------------------------------------------------------------------

class IdentityTest(_Base):
    def test_no_prefill_reads_none(self):
        data = self._get(self._create(), "/identity")
        self.assertEqual(data["positioning"], {"value": "", "source": "none", "note": ""})
        self.assertEqual(data["tone"]["values"], [])
        self.assertEqual(data["tone"]["source"], "none")
        self.assertEqual(data["tone"]["options"], ["親切", "專業", "直接", "幽默", "溫柔", "熱血"])
        self.assertEqual(data["visual"]["source"], "none")
        self.assertEqual(data["visual"]["photo_urls"], [])

    def test_prefill_reads_ai_then_put_reads_saved(self):
        bid = self._create(urls="https://example.com")
        self._store_prefill(bid)
        data = self._get(bid, "/identity")
        self.assertEqual(data["positioning"], {"value": "給忙到沒空吃飯的人的維他命軟糖",
                                               "source": "ai", "note": "首頁"})
        self.assertEqual((data["tone"]["values"], data["tone"]["source"]), (["親切", "直接"], "ai"))
        self.assertEqual(data["visual"]["note"], "品牌照片")

        resp = self._put(bid, "/identity", {"positioning": "一顆軟糖補齊今天的維他命",
                                            "tone": ["親切", "像教練朋友"], "visual": "黑底霓虹"})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual(data["positioning"]["source"], "saved")
        self.assertEqual(data["positioning"]["value"], "一顆軟糖補齊今天的維他命")
        self.assertEqual(data["tone"]["values"], ["親切", "像教練朋友"])
        self.assertIn("像教練朋友", data["tone"]["options"])
        self.assertEqual(data["visual"]["value"], "黑底霓虹")
        self.assertEqual(self._get(bid)["step"], 4)

    def test_put_replaces_the_confirmed_row(self):
        bid = self._create()
        for text in ("第一版定位", "第二版定位"):
            self._put(bid, "/identity", {"positioning": text, "tone": ["專業"], "visual": ""})
        facts = [f for f in bi_repo.list_brand_facts(web.conn, bid, status="confirmed")
                 if f["fact_type"] == "positioning"]
        self.assertEqual([f["value"] for f in facts], ["第二版定位"])
        self.assertFalse([f for f in bi_repo.list_brand_facts(web.conn, bid)
                          if f["fact_type"] == "visual_base"])

    def test_tones_are_stored_in_params_and_old_rows_fall_back_to_the_value(self):
        bid = self._create()
        bi_repo.create_brand_fact(web.conn, bid, actor="test", fact_type="tone", label="語調",
                                  value="親切、像教練朋友", status="confirmed", confirmed_by="test")
        self.assertEqual(self._get(bid, "/identity")["tone"]["values"], ["親切", "像教練朋友"])
        self._put(bid, "/identity", {"positioning": "", "tone": ["專業", "直接"], "visual": ""})
        [tone] = [f for f in bi_repo.list_brand_facts(web.conn, bid, status="confirmed")
                  if f["fact_type"] == "tone"]
        self.assertEqual((tone["value"], tone["params_json"]),
                         ("專業、直接", {"tones": ["專業", "直接"]}))

    def test_tone_count_is_one_or_two(self):
        bid = self._create()
        for tones in ([], ["親切", "專業", "直接"], "親切"):
            resp = self._put(bid, "/identity", {"positioning": "", "tone": tones, "visual": ""})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("口氣", resp.json()["error"])


# ---------------------------------------------------------------------------
# Step 4 證據與政策
# ---------------------------------------------------------------------------

class EvidenceTest(_Base):
    def test_no_prefill_shape(self):
        data = self._get(self._create(), "/evidence")
        self.assertEqual(data["proof"], [])
        self.assertEqual(data["policies"], [])
        self.assertEqual(data["forbidden"], [])
        self.assertEqual(data["cooling_off"], {"applies": True, "disclosure": ""})
        self.assertEqual(data["regime_label"], "")
        self.assertEqual(len(data["policy_types"]), 26)
        self.assertEqual(sum(1 for p in data["policy_types"] if p["common"]), 8)
        self.assertTrue(all(p["offer_label"] for p in data["policy_types"]))
        self.assertEqual(len(data["proof_kinds"]), 6)

    def test_ai_policy_and_saved_proof(self):
        bid = self._create(urls="https://example.com", regulatory_regime="food_tw")
        bi_repo.create_brand_fact(web.conn, bid, actor="test", fact_type="proof", label="銷售數據",
                                  value="累積賣出 12,000 盒", status="confirmed",
                                  confirmed_by="test", fact_key="sales_numbers")
        self._store_prefill(bid, {"policies": _PREFILL["policies"]})
        data = self._get(bid, "/evidence")
        self.assertEqual([(p["fact_key"], p["source"]) for p in data["proof"]],
                         [("sales_numbers", "saved")])
        self.assertEqual(data["policies"], [{
            "key": "ship_threshold", "label": "滿額免運", "group": "運送",
            "params": {"threshold": 999}, "offer_key": "free_shipping", "offer_label": "免運",
            "sentence": "滿 NT$999 免運", "source": "ai", "note": "運送說明頁"}])
        self.assertEqual(data["regime_label"], "台灣食品（食安法）")

    def test_put_saves_every_list_then_reads_saved(self):
        bid = self._create(urls="https://example.com")
        self._store_prefill(bid)
        ai = self._get(bid, "/evidence")
        self.assertEqual([(p["id"], p["source"], p["note"]) for p in ai["proof"]],
                         [(None, "ai", "about 頁")])
        resp = self._put(bid, "/evidence", {
            "proof": [{"id": None, "fact_key": "founder_voice", "text": ai["proof"][0]["text"]},
                      {"fact_key": "media_coverage", "text": ""}],
            "policies": [{"key": "ship_threshold", "params": {"threshold": 999}},
                         {"key": "custom", "params": {"label": "回購禮", "offer_key": "bundle"},
                          "sentence": "連續訂三個月，第四個月送隨身包"}],
            "cooling_off": {"applies": True},
            "forbidden": ["不講「最」「第一」", "不講「最」「第一」", ""]})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual([(p["fact_key"], p["source"]) for p in data["proof"]],
                         [("founder_voice", "saved")])
        self.assertIsNotNone(data["proof"][0]["id"])
        self.assertEqual([(p["key"], p["source"], p["sentence"]) for p in data["policies"]],
                         [("ship_threshold", "saved", "滿 NT$999 免運"),
                          ("custom", "saved", "連續訂三個月，第四個月送隨身包")])
        self.assertEqual(data["policies"][1]["group"], "自訂")
        self.assertEqual([f["text"] for f in data["forbidden"]], ["不講「最」「第一」"])
        self.assertEqual(bi_repo.available_offer_keys(web.conn, bid), {"free_shipping", "bundle"})
        self.assertEqual(self._get(bid)["step"], 5)

        # Full-list semantics: editing the proof by id, emptying the other lists.
        proof_id = data["proof"][0]["id"]
        resp = self._put(bid, "/evidence", {
            "proof": [{"id": proof_id, "fact_key": "founder_voice", "text": "改寫過的創辦人故事"}],
            "policies": [], "cooling_off": {"applies": False,
                                            "disclosure": "本商品為易腐敗之食品，不適用七天猶豫期"},
            "forbidden": []})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual([(p["id"], p["text"]) for p in data["proof"]],
                         [(proof_id, "改寫過的創辦人故事")])
        self.assertEqual(data["policies"], [])
        self.assertEqual(data["forbidden"], [])
        self.assertEqual(data["cooling_off"],
                         {"applies": False, "disclosure": "本商品為易腐敗之食品，不適用七天猶豫期"})
        self.assertEqual(bi_repo.available_offer_keys(web.conn, bid), set())

    def test_empty_lists_are_valid(self):
        bid = self._create()
        resp = self._put(bid, "/evidence", {"proof": [], "policies": [],
                                            "cooling_off": {"applies": True}, "forbidden": []})
        self.assertEqual(resp.status_code, 200, resp.text)

    def test_validation_writes_nothing(self):
        bid = self._create()
        ok = {"proof": [{"fact_key": "founder_voice", "text": "創辦人故事"}], "policies": [],
              "cooling_off": {"applies": True}, "forbidden": ["不講第一"]}
        cases = (
            ({"policies": [{"key": "no_such_policy", "params": {}}]}, "未知的全店政策"),
            ({"policies": [{"key": "ship_threshold", "params": {}}]}, "門檻"),
            ({"cooling_off": {"applies": False, "disclosure": "太短"}}, "告知文字"),
            ({"proof": [{"fact_key": "rumour", "text": "聽說很好"}]}, "證據要選一種"),
            ({"proof": [{"id": "bft_missing", "fact_key": "founder_voice", "text": "x"}]},
             "找不到"),
        )
        for patch, needle in cases:
            resp = self._put(bid, "/evidence", {**ok, **patch})
            self.assertEqual(resp.status_code, 400, patch)
            self.assertIn(needle, resp.json()["error"])
        self.assertEqual(self._get(bid, "/evidence")["proof"], [])
        self.assertEqual(self._get(bid, "/evidence")["forbidden"], [])


# ---------------------------------------------------------------------------
# Step 5 素材 / step 6 接工具
# ---------------------------------------------------------------------------

class MediaAndToolsTest(_Base):
    def test_media_round_trip_and_validation(self):
        bid = self._create()
        self.assertEqual(self._get(bid, "/media"), {"media": None})
        resp = self._put(bid, "/media", {"media": "photo"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], {"media": "photo"})
        self.assertEqual(bi_repo.get_brand(web.conn, bid)["media_capability"], "photo")
        for bad in (None, "video"):
            resp = self._put(bid, "/media", {"media": bad})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("只有照片", resp.json()["error"])

    def test_tools_without_meta(self):
        bid = self._create()
        data = self._get(bid, "/tools")
        states = {c["key"]: c["state"] for c in data["connectors"]}
        self.assertEqual(states, {"meta": "available", "google": "seat", "tiktok": "seat",
                                  "ga4": "seat", "gsc": "seat", "shop": "seat", "csv": "available",
                                  "mcp": "seat", "api": "seat"})
        csv = next(c for c in data["connectors"] if c["key"] == "csv")
        self.assertEqual(csv["link"], f"/brands/{bid}/orders")
        self.assertTrue(all(c["reads"] for c in data["connectors"]))
        self.assertIsNone(data["conversion_goal"])
        self.assertEqual({o["key"] for o in data["conversion_goal_options"]},
                         {"purchase", "lead", "booking", "awareness"})

    def test_tools_with_a_bound_meta_account(self):
        bid = self._create()
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, coredb.DEV_ORG_ID, [
            {"account_id": external_id, "name": "虛構主帳戶", "currency": "TWD"}])
        row = next(a for a in meta_repo.list_accounts(web.conn, coredb.DEV_ORG_ID)
                   if a["account_id"] == external_id)
        meta_repo.bind(web.conn, coredb.DEV_ORG_ID, bid, row["id"])
        web.conn.commit()
        meta = next(c for c in self._get(bid, "/tools")["connectors"] if c["key"] == "meta")
        self.assertEqual((meta["state"], meta["note"]), ("connected", "已接上：虛構主帳戶"))


# ---------------------------------------------------------------------------
# Re-entry and tenancy
# ---------------------------------------------------------------------------

class ReentryAndTenancyTest(_Base):
    def test_completed_brand_reads_and_writes_the_stores(self):
        bid = self._create(urls="https://example.com")
        self._store_prefill(bid)
        self._complete(bid)
        identity = self._get(bid, "/identity")  # the prefill is not shown once completed
        self.assertEqual(identity["positioning"]["source"], "none")
        resp = self._put(bid, "/identity", {"positioning": "重新進來改的定位", "tone": ["溫柔"],
                                            "visual": ""})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["positioning"]["source"], "saved")
        self.assertEqual(self._get(bid)["step"], 7)
        self.assertIsNone(ir.get_active_draft(web.conn, bid))

    def test_other_org_gets_404_everywhere(self):
        bid = self._create()
        headers = self._other_org_headers()
        for path in ("", "/basics", "/identity", "/evidence", "/media", "/tools"):
            self.assertEqual(self.client.get(self._url(bid, path), headers=headers).status_code,
                             404, path)
        for path, body in (("/basics", {"name": "x"}), ("/identity", {"tone": ["親切"]}),
                           ("/evidence", {}), ("/media", {"media": "photo"})):
            resp = self.client.put(self._url(bid, path), json=body, headers=headers)
            self.assertEqual(resp.status_code, 404, path)
        self.assertEqual(
            self.client.post(self._url(bid, "/complete"), headers=headers).status_code, 404)
        self.assertIsNotNone(ir.get_active_draft(web.conn, bid))


if __name__ == "__main__":
    unittest.main()
