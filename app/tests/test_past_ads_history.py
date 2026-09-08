"""app/tests/test_past_ads_history.py — 票 past-ads/03（ADR 0067）：讀老廣告成效排名、
把要問的那批廣告的素材快取進 `imported_ad`、owner 自己標七維座標；brand 記「投放過／
沒投過」。

只寫全域 CLAUDE.md 測試四類允許的（金額、租戶隔離、API 契約、資料正確性）：

1. 排行：三張榜單（花費前 5／保守 ROAS 前 5／樂觀 ROAS 最後 5）union、按 entity_id 去重、
   最多 15 張、`why` 記錄命中哪幾張榜單（ticket done-check 1）。
2. 金額：卡片的花費／ROAS 全部借 `performance._bucket()`（票面「reuse, do not
   reimplement」），拿契約頁自己量出來的那組數字驗（ticket done-check 2）。
3. 兩個幣別各自一份 `currencies`，互不相加、互不越界（ticket done-check 3）。
4. GET 只在第一次幫要問的廣告抓素材（`fetch_ad_creatives` 只打一次、包含 Meta 答 None
   的那個 id），第二次 GET 零呼叫；`GraphError` 時 200、每張卡 `creative: null`、
   零列寫入（ticket done-check 4）。
5. 標籤驗證：跨品牌的座標、跨維度重用同一個 key 字串都要 400；有效值 200＋稽核列；
   全空＋一句話存 `pending`；沒被 GET 建過的 external_id 404（ticket done-check 5）。
6. 租戶界線：另一個組織的 actor 對這個品牌的 GET／PUT／PUT advertising-history 一律
   404；同一個組織兩個品牌互不看到對方的 `imported_ad`（ticket done-check 6）。
7. `advertising_history` 這欄的 PUT／讀回／非法值 400／稽核列（ticket done-check 7）。
8. 沒有 LLM、沒有寫 `rule`：原始碼不含 `gateway`／`create_rule`／`llm_task` 字樣，一整輪
   GET+PUT 前後 `rule` 表列數不變（ticket done-check 8）。

不重寫的：租戶隔離已經是 `test_org_isolation_all_tables.py`／`test_brand_isolation_all_tables.py`
的範圍（machine gate 另外單獨跑），這裡只驗 `imported_ad` 這張新表自己的查詢邊界。畫面行為
不寫單元測試，只留 `frontend/e2e/smoke.spec.ts`。
"""

import unittest
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import new_id
from app.identity import repository as identity_repo
from app.meta import graph
from app.meta import repository as meta_repo
from app.schedule import repository as schedule_repo

from .identity_test_helpers import mint_hs256

ACCOUNT_ID = "300100000009001"
OTHER_ACCOUNT_ID = "300100000009002"


def _generic_creative_page(url, *, params, headers):
    """預設替身：任何一則廣告都答得出素材，讓不是在測創意快取本身的測試（排行、金額、
    幣別、標籤、租戶）不用各自準備一份素材 fixture。"""
    return {
        "name": "廣告", "created_time": "2026-01-01T00:00:00+0000", "effective_status": "ACTIVE",
        "creative": {"body": "立即選購", "title": None, "image_url": "https://img.example/a.jpg"},
    }


class _HistoryTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_fetch_page = graph.fetch_page
        graph.fetch_page = _generic_creative_page
        self.client = TestClient(main.app)

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def _make_org(self, suffix: str) -> tuple:
        org_id = f"org_history_test_{suffix}_{uuid4().hex[:8]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"history-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        return org_id, mint_hs256(sub=str(user_id), email=email)

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}

    def _make_brand(self, org_id: str) -> str:
        return bi_repo.create_brand(
            web.conn, org_id=org_id, name=f"投放史測試品牌{uuid4().hex[:6]}",
            client_name=None, actor="測試員",
        )["id"]

    def _connect_and_bind_account(self, org_id: str, brand_id: str, account_id: str,
                                   *, currency: str = "TWD") -> str:
        meta_repo.save_token(web.conn, org_id, "tok")
        meta_repo.upsert_accounts(web.conn, org_id, [
            {"account_id": account_id, "name": account_id, "currency": currency},
        ])
        web.conn.commit()
        local_id = next(
            a["id"] for a in meta_repo.list_accounts(web.conn, org_id)
            if a["account_id"] == account_id
        )
        meta_repo.bind(web.conn, org_id, brand_id, local_id)
        web.conn.commit()
        return local_id

    def _seed_ad_spend(self, org_id: str, local_account_id: str, ad_id: str, day: date, *,
                        spend: float, roas: float | None = None,
                        impressions: int = 100, clicks: int = 10) -> None:
        meta_repo.upsert_entity_spend(web.conn, org_id, local_account_id, [{
            "level": "ad", "entity_id": ad_id, "entity_name": ad_id,
            "campaign_id": "camp-x", "adset_id": "as-x", "ad_id": ad_id,
            "spend_date": day, "spend": spend, "impressions": impressions, "clicks": clicks,
            "roas": roas, "actions": None, "action_values": None,
            "attribution_window": "7d_click,1d_view",
        }])
        web.conn.commit()

    def _get_history(self, brand_id: str, token: str, org_id: str):
        return self.client.get(
            f"/api/schedule/brands/{brand_id}/history", headers=self._headers(token, org_id),
        )

    def _put_tag(self, brand_id: str, external_id: str, token: str, org_id: str, body: dict):
        return self.client.put(
            f"/api/schedule/brands/{brand_id}/history/{external_id}",
            headers=self._headers(token, org_id), json=body,
        )

    @staticmethod
    def _empty_keys() -> dict:
        return {k: None for k in ("audience", "pain", "angle", "hook", "proof", "offer", "format")}


# -- 1. 排行：三張榜單 union、去重、上限 15 --------------------------------------------

class RankingTest(_HistoryTestBase):
    def test_three_lists_union_dedup_and_why(self):
        org_id, token = self._make_org("rank")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        day = date(2026, 6, 1)

        # top_spend 5（沒有追蹤到營收，也是「有花費、沒營收 → verdict unclear」的 fixture）
        top_spend_only = ["a1", "a2", "a3"]
        for i, ad in enumerate(top_spend_only):
            self._seed_ad_spend(org_id, account, ad, day, spend=1500 - i * 100, roas=None)
        # top_spend 剩下兩個，同時也擠進 top_roas（跟 top_spend 重疊的兩個 id）
        self._seed_ad_spend(org_id, account, "b1", day, spend=1200, roas=9.0)
        self._seed_ad_spend(org_id, account, "b2", day, spend=1100, roas=8.5)
        # 純 top_roas（花費很低，擠不進 top_spend）
        for i, (ad, roas) in enumerate([("c1", 8.0), ("c2", 7.5), ("c3", 7.0)]):
            self._seed_ad_spend(org_id, account, ad, day, spend=50 - i, roas=roas)
        # 純 bottom_roas（同樣花費很低）
        for i, (ad, roas) in enumerate([("d1", 0.05), ("d2", 0.10), ("d3", 0.15),
                                         ("d4", 0.20), ("d5", 0.25)]):
            self._seed_ad_spend(org_id, account, ad, day, spend=20 - i, roas=roas)

        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        currencies = resp.json()["currencies"]
        self.assertEqual(len(currencies), 1)
        cards = currencies[0]["cards"]
        ids = [c["external_id"] for c in cards]

        self.assertEqual(len(ids), len(set(ids)), "同一個 external_id 不准出現兩次")
        self.assertEqual(
            ids, ["a1", "a2", "a3", "b1", "b2", "c1", "c2", "c3", "d1", "d2", "d3", "d4", "d5"],
            "union 順序：top_spend → top_roas 新面孔 → bottom_roas 新面孔",
        )
        by_id = {c["external_id"]: c for c in cards}
        self.assertEqual(by_id["a1"]["why"], ["top_spend"])
        self.assertEqual(by_id["b1"]["why"], ["top_spend", "top_roas"])
        self.assertEqual(by_id["c1"]["why"], ["top_roas"])
        self.assertEqual(by_id["d1"]["why"], ["bottom_roas"])
        # 有花費、沒追蹤到營收的廣告：不進任一張榜單以外的判定，verdict 永遠 unclear。
        self.assertIsNone(by_id["a1"]["revenue"])
        self.assertEqual(by_id["a1"]["verdict"], "unclear")

    def test_disjoint_sets_cap_at_fifteen(self):
        org_id, token = self._make_org("rank20")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        day = date(2026, 6, 1)

        for i in range(5):
            self._seed_ad_spend(org_id, account, f"sp{i}", day, spend=5000 - i * 10, roas=None)
        for i in range(5):
            self._seed_ad_spend(org_id, account, f"hr{i}", day, spend=10 - i, roas=9.0 - i * 0.5)
        for i in range(5):
            self._seed_ad_spend(org_id, account, f"lr{i}", day, spend=9 - i, roas=0.05 + i * 0.02)
        for i in range(5):
            self._seed_ad_spend(org_id, account, f"filler{i}", day, spend=1 + i, roas=2.0)

        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        cards = resp.json()["currencies"][0]["cards"]
        self.assertEqual(len(cards), 15, "20 則廣告，三張互不重疊的榜單 union 剛好 15 張")
        ids = {c["external_id"] for c in cards}
        for i in range(5):
            self.assertNotIn(f"filler{i}", ids, "沒上任何一張榜單的廣告不該出現")


# -- 2. 金額：花費／ROAS 全部借 performance._bucket() -----------------------------------

class MoneyArithmeticTest(_HistoryTestBase):
    def test_matches_contract_pages_own_measured_numbers(self):
        """`docs/contracts/schedule.md`「One coordinate has two ROAS values」量到的那組
        數字：四天，3,570 花費、2,737.8 營收、3/4 天有追蹤 → 保守 0.767、樂觀 1.029、
        覆蓋率 0.75。"""
        org_id, token = self._make_org("money")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)

        self._seed_ad_spend(org_id, account, "ad-x", date(2026, 5, 1), spend=2000.00, roas=1.0000)
        self._seed_ad_spend(org_id, account, "ad-x", date(2026, 5, 2), spend=460.00, roas=1.0000)
        self._seed_ad_spend(org_id, account, "ad-x", date(2026, 5, 3), spend=200.00, roas=1.3890)
        self._seed_ad_spend(org_id, account, "ad-x", date(2026, 5, 4), spend=910.00, roas=None)

        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        card = resp.json()["currencies"][0]["cards"][0]
        self.assertAlmostEqual(card["spend"], 3570.0, places=2)
        self.assertAlmostEqual(card["revenue"], 2737.8, places=2)
        self.assertAlmostEqual(card["roas_conservative"], 0.767, places=3)
        self.assertAlmostEqual(card["roas"], 1.029, places=3)
        self.assertEqual(card["roas_coverage"], 0.75)
        self.assertEqual(card["first_seen_date"], "2026-05-01")
        self.assertEqual(card["last_seen_date"], "2026-05-04")


# -- 3. 兩個幣別各自一份，互不相加 -------------------------------------------------------

class CurrencySeparationTest(_HistoryTestBase):
    def test_two_currencies_never_mix(self):
        org_id, token = self._make_org("currency")
        brand_id = self._make_brand(org_id)
        twd_account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID, currency="TWD")
        usd_account = self._connect_and_bind_account(
            org_id, brand_id, OTHER_ACCOUNT_ID, currency="USD",
        )
        day = date(2026, 6, 1)
        self._seed_ad_spend(org_id, twd_account, "twd-ad", day, spend=1000.0, roas=2.0)
        self._seed_ad_spend(org_id, usd_account, "usd-ad", day, spend=50.0, roas=1.5)

        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        currencies = resp.json()["currencies"]
        self.assertEqual(len(currencies), 2)
        by_currency = {c["currency"]: c for c in currencies}
        self.assertEqual({c["external_id"] for c in by_currency["TWD"]["cards"]}, {"twd-ad"})
        self.assertEqual({c["external_id"] for c in by_currency["USD"]["cards"]}, {"usd-ad"})


# -- 4. GET 只在第一次抓素材，快取進 imported_ad ------------------------------------------

class CreativeCacheTest(_HistoryTestBase):
    def test_first_get_seeds_cache_including_meta_answering_none(self):
        org_id, token = self._make_org("creative")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        day = date(2026, 6, 1)
        self._seed_ad_spend(org_id, account, "ok-ad", day, spend=1000.0, roas=2.0)
        self._seed_ad_spend(org_id, account, "gone-ad", day, spend=500.0, roas=1.0)

        calls = []

        def fake(url, *, params, headers):
            calls.append(url)
            if url.endswith("/ok-ad"):
                return {"name": "廣告", "created_time": "2026-01-01T00:00:00+0000",
                        "effective_status": "ACTIVE",
                        "creative": {"body": "文案", "title": None, "image_url": "https://img.example/a.jpg"}}
            if url.endswith("/gone-ad"):
                return {"error": {"message": "Unsupported get request."}}
            raise AssertionError(f"沒有對應的 fixture：{url}")

        graph.fetch_page = fake
        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(calls), 2, "第一次 GET：兩張卡各打一次")
        cards_by_id = {c["external_id"]: c for c in resp.json()["currencies"][0]["cards"]}
        self.assertIsNotNone(cards_by_id["ok-ad"]["creative"])
        self.assertIsNone(cards_by_id["ok-ad"]["creative_error"])
        self.assertIsNone(cards_by_id["gone-ad"]["creative"], "Meta 答不出來 → creative null")
        self.assertIsNone(cards_by_id["gone-ad"]["creative_error"], "不是失敗，是一個狀態")

        rows = schedule_repo.imported_ads_for_brand(web.conn, org_id, brand_id)
        self.assertEqual(set(rows), {"ok-ad", "gone-ad"})
        self.assertIsNotNone(rows["gone-ad"]["creative_fetched_at"])
        self.assertIsNone(rows["gone-ad"]["creative_body"])

        # 第二次 GET：兩則都已經有快取，零呼叫。
        calls.clear()
        resp2 = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(calls, [], "第二次 GET 不該再打 Meta")

    def test_graph_error_returns_null_creative_and_writes_nothing(self):
        import httpx

        org_id, token = self._make_org("creative_err")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        self._seed_ad_spend(org_id, account, "ad-1", date(2026, 6, 1), spend=1000.0, roas=2.0)

        def fake(url, *, params, headers):
            raise httpx.ConnectError("boom")

        graph.fetch_page = fake
        resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(resp.status_code, 200)
        for card in resp.json()["currencies"][0]["cards"]:
            self.assertIsNone(card["creative"])
            self.assertIsNotNone(card["creative_error"])
        self.assertEqual(schedule_repo.imported_ads_for_brand(web.conn, org_id, brand_id), {})


# -- 5. 標籤驗證：跨品牌／跨維度重用 key、有效值、全空、未知 external_id ------------------

class TagValidationTest(_HistoryTestBase):
    def test_tagging_lifecycle_and_validation(self):
        org_id, token = self._make_org("tag")
        brand_id = self._make_brand(org_id)
        other_brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        self._seed_ad_spend(org_id, account, "ad-1", date(2026, 6, 1), spend=1000.0, roas=2.0)

        # GET 先把列建起來（PUT 只改既有列，ADR 0067 §1.2）。
        get_resp = self._get_history(brand_id, token, org_id)
        self.assertEqual(get_resp.status_code, 200)

        # 另一個品牌的座標——跨品牌不通用。
        foreign_coordinate = schedule_repo.create_coordinate(
            web.conn, org_id, other_brand_id, "angle", "別的品牌的角度", None,
        )
        body = {**self._empty_keys(), "angle": foreign_coordinate["key"]}
        resp = self._put_tag(
            brand_id, "ad-1", token, org_id, {"coordinates": body, "owner_note": None},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "coordinate_unknown")

        # 同一個字串在這個品牌底下，用在兩個不同維度——跨維度重用同一個 key 不能通用。
        shared_key = "shared_key_x"
        web.conn.execute(
            "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label)"
            " VALUES (%s, %s, %s, 'audience', %s, '受眾版')",
            (new_id("crd"), org_id, brand_id, shared_key),
        )
        web.conn.execute(
            "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label)"
            " VALUES (%s, %s, %s, 'pain', %s, '痛點版')",
            (new_id("crd"), org_id, brand_id, shared_key),
        )
        web.conn.commit()
        wrong_dimension_body = {**self._empty_keys(), "angle": shared_key}
        resp = self._put_tag(
            brand_id, "ad-1", token, org_id,
            {"coordinates": wrong_dimension_body, "owner_note": None},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "coordinate_unknown")

        # 有效值：同一個 key 用在它真正對得上的維度 → 200，tagged，稽核列存在。
        valid_body = {**self._empty_keys(), "pain": shared_key}
        resp = self._put_tag(
            brand_id, "ad-1", token, org_id,
            {"coordinates": valid_body, "owner_note": "媽媽群組轉貼最多"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["coordinates_status"], "tagged")
        self.assertEqual(payload["coordinates"]["pain"], shared_key)
        self.assertEqual(payload["owner_note"], "媽媽群組轉貼最多")
        audit_count = web.conn.execute(
            "SELECT count(*) AS n FROM audit_log"
            " WHERE entity_type = 'imported_ad' AND action = 'tag' AND brand_id = %s",
            (brand_id,),
        ).fetchone()["n"]
        self.assertEqual(audit_count, 1)

        # 再 PUT 一次不同的值——還是同一列（唯一鍵撐住），新值蓋掉舊值。
        another_coordinate = schedule_repo.create_coordinate(
            web.conn, org_id, brand_id, "offer", "自家的優惠", None,
        )
        second_body = {**self._empty_keys(), "offer": another_coordinate["key"]}
        resp = self._put_tag(
            brand_id, "ad-1", token, org_id, {"coordinates": second_body, "owner_note": None},
        )
        self.assertEqual(resp.status_code, 200)
        row_count = web.conn.execute(
            "SELECT count(*) AS n FROM imported_ad"
            " WHERE org_id = %s AND brand_id = %s AND external_id = %s",
            (org_id, brand_id, "ad-1"),
        ).fetchone()["n"]
        self.assertEqual(row_count, 1)
        self.assertEqual(resp.json()["coordinates"]["offer"], another_coordinate["key"])
        self.assertIsNone(resp.json()["coordinates"]["pain"], "新的 PUT 蓋掉舊值，不是合併")

        # 全部七個 None + 一句話 → pending，note 照存。
        resp = self._put_tag(
            brand_id, "ad-1", token, org_id,
            {"coordinates": self._empty_keys(), "owner_note": "先觀察一陣子"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["coordinates_status"], "pending")
        self.assertEqual(resp.json()["owner_note"], "先觀察一陣子")

        # 沒被 GET 建過的 external_id → 404。
        resp = self._put_tag(
            brand_id, "never-seeded", token, org_id,
            {"coordinates": self._empty_keys(), "owner_note": None},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "imported_ad_unknown")


# -- 6. 租戶界線 ------------------------------------------------------------------------

class TenantBoundaryTest(_HistoryTestBase):
    def test_other_org_gets_404_on_every_route(self):
        org_a, token_a = self._make_org("tenant_a")
        org_b, token_b = self._make_org("tenant_b")
        brand_a = self._make_brand(org_a)
        account = self._connect_and_bind_account(org_a, brand_a, ACCOUNT_ID)
        self._seed_ad_spend(org_a, account, "ad-1", date(2026, 6, 1), spend=1000.0, roas=2.0)
        self._get_history(brand_a, token_a, org_a)  # 種一列給 org B 嘗試 PUT 用

        resp = self._get_history(brand_a, token_b, org_b)
        self.assertEqual(resp.status_code, 404)

        resp = self._put_tag(
            brand_a, "ad-1", token_b, org_b,
            {"coordinates": self._empty_keys(), "owner_note": None},
        )
        self.assertEqual(resp.status_code, 404)

        resp = self.client.put(
            f"/api/library/brands/{brand_a}/advertising-history",
            headers=self._headers(token_b, org_b), json={"value": "has_history"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_imported_ads_for_brand_never_leaks_sibling_brand(self):
        org_id, token = self._make_org("tenant_sibling")
        brand_a = self._make_brand(org_id)
        brand_b = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_a, ACCOUNT_ID)
        self._seed_ad_spend(org_id, account, "ad-a", date(2026, 6, 1), spend=1000.0, roas=2.0)
        self._get_history(brand_a, token, org_id)

        rows_a = schedule_repo.imported_ads_for_brand(web.conn, org_id, brand_a)
        rows_b = schedule_repo.imported_ads_for_brand(web.conn, org_id, brand_b)
        self.assertEqual(set(rows_a), {"ad-a"})
        self.assertEqual(rows_b, {})
        # 複合 FK：寫進去的 ad_channel_id 是這個組織的 meta 通路。
        channel_id = schedule_repo.ensure_meta_channel(web.conn, org_id)
        self.assertEqual(rows_a["ad-a"]["ad_channel_id"], channel_id)


# -- 7. brand.advertising_history 這一欄的 PUT ------------------------------------------

class AdvertisingHistoryPutTest(_HistoryTestBase):
    def test_stores_reads_back_and_rejects_invalid_value(self):
        org_id, token = self._make_org("adv_history")
        brand_id = self._make_brand(org_id)
        headers = self._headers(token, org_id)

        resp = self.client.put(
            f"/api/library/brands/{brand_id}/advertising-history",
            headers=headers, json={"value": "has_history"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["advertising_history"], "has_history")

        profile = self.client.get(f"/api/library/brands/{brand_id}", headers=headers)
        self.assertEqual(profile.json()["data"]["brand"]["advertising_history"], "has_history")

        resp = self.client.put(
            f"/api/library/brands/{brand_id}/advertising-history",
            headers=headers, json={"value": "none"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["advertising_history"], "none")

        resp = self.client.put(
            f"/api/library/brands/{brand_id}/advertising-history",
            headers=headers, json={"value": "maybe"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("value", resp.json()["errors"])

        audit_count = web.conn.execute(
            "SELECT count(*) AS n FROM audit_log"
            " WHERE entity_type = 'brand' AND action = 'advertising_history' AND brand_id = %s",
            (brand_id,),
        ).fetchone()["n"]
        self.assertEqual(audit_count, 2, "兩次成功的 PUT 各留一筆稽核，第三次 400 不留")


# -- 8. 沒有 LLM、沒有寫 rule -------------------------------------------------------------

class NoLlmNoRuleTest(_HistoryTestBase):
    def test_history_module_calls_no_gateway_or_rule_writer(self):
        source = Path("app/schedule/history.py").read_text(encoding="utf-8")
        for needle in ("gateway", "create_rule", "llm_task"):
            self.assertNotIn(needle, source, f"history.py 不該出現 {needle!r}")

    def test_full_get_and_put_sequence_leaves_rule_table_untouched(self):
        org_id, token = self._make_org("no_rule")
        brand_id = self._make_brand(org_id)
        account = self._connect_and_bind_account(org_id, brand_id, ACCOUNT_ID)
        self._seed_ad_spend(org_id, account, "ad-1", date(2026, 6, 1), spend=1000.0, roas=2.0)

        def _rule_count() -> int:
            return web.conn.execute("SELECT count(*) AS n FROM rule").fetchone()["n"]

        before = _rule_count()
        self._get_history(brand_id, token, org_id)
        self._put_tag(
            brand_id, "ad-1", token, org_id,
            {"coordinates": self._empty_keys(), "owner_note": "測試"},
        )
        self._get_history(brand_id, token, org_id)
        self.assertEqual(_rule_count(), before)
