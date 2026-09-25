"""app/tests/test_meta_credentials.py — 票 04：連接 Meta 廣告帳戶。票 T4（ADR 0056 §4）
加了第五件：channel_credential 取代原本一人一列的組織層憑證表之後，account_scope 真的
是唯一鍵的一部分，不是裝飾用的欄位。

五件事，只寫這五件（全域 CLAUDE.md 測試四類：金額、租戶隔離、API 契約、資料
正確性；畫面行為不寫單元測試，見 04-design-approved.md「Tests」節）：

1. 貼上的權杖經過 Vault 存好；`app_setting` 完全沒被動到，`channel_credential` 沒有任何
   欄位出現過權杖原文。
2. 一個組織連接並綁定的帳號，另一個組織在 GET /api/meta/accounts、bind、unbind 三條
   路由上都看不到／碰不到。
3. 綁定、解除各寫一筆 audit_log。
4. Graph 客戶端解析真的成功／錯誤形狀，把錯誤形狀轉成人話——換掉 `graph.fetch_page`
   （同 app/core/net.py fetch_url 在 test_intake.py 的替換慣例），測試不打真正的網路。
5. `channel_credential` 的唯一鍵是 (org_id, channel_id, account_scope)，不是舊表那個
   單一 org_id：同一個組織、同一個通路，兩個不同的 account_scope 要能並存；同一個
   account_scope 第二次寫入要撞唯一鍵（票 T4 done-check 3，資料正確性）。
"""

import json
import unittest
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.identity import repository as identity_repo
from app.meta import graph
from app.meta import repository as meta_repo

from .identity_test_helpers import mint_hs256

TOKEN = "EAAtest-fake-meta-token-abcd1234"

SUCCESS_PAGE = {
    "data": [
        {"account_id": "1000000000001", "name": "測試帳號一", "currency": "TWD",
         "id": "act_1000000000001"},
    ],
    "paging": {},
}
ERROR_BODY = {
    "error": {
        "message": "Invalid OAuth access token.",
        "type": "OAuthException",
        "code": 190,
        "fbtrace_id": "Axxxxxxxxxxxxxxxx",
    }
}


def _fake_success(url, *, params, headers):
    return SUCCESS_PAGE


def _fake_error(url, *, params, headers):
    return ERROR_BODY


class _MetaHttpTestBase(unittest.TestCase):
    """共用：換掉 graph.fetch_page（不打真正網路）＋建第二個組織的小工具。"""

    def setUp(self):
        self._orig_fetch_page = graph.fetch_page
        graph.fetch_page = _fake_success
        self.client = TestClient(main.app)

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def _make_org(self, suffix: str) -> tuple:
        """建一個新組織 + 一個屬於它的使用者 + owner membership，回傳 (org_id, bearer_token)。"""
        org_id = f"org_meta_test_{suffix}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        user_id = uuid4()
        email = f"meta-test-{suffix}-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, org_id, user_id, "owner")
        web.conn.commit()
        token = mint_hs256(sub=str(user_id), email=email)
        return org_id, token

    @staticmethod
    def _headers(token: str, org_id: str) -> dict:
        return {"Authorization": f"Bearer {token}", "X-Org-Id": org_id}


# -- 1. Vault 落地；app_setting 不動、channel_credential 不存權杖原文 -----------------

class TokenVaultRoundTripTest(_MetaHttpTestBase):
    def test_token_goes_to_vault_not_app_setting(self):
        before = web.conn.execute("SELECT count(*) AS n FROM app_setting").fetchone()["n"]

        resp = self.client.post("/api/meta/token", json={"token": TOKEN})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["accounts"]), 1)
        self.assertEqual(body["accounts"][0]["name"], "測試帳號一")
        self.assertEqual(body["token_tail"], TOKEN[-4:])

        after = web.conn.execute("SELECT count(*) AS n FROM app_setting").fetchone()["n"]
        self.assertEqual(before, after, "app_setting 不該被這條路由動到")

        row = web.conn.execute(
            "SELECT * FROM channel_credential WHERE org_id = %s", (coredb.DEV_ORG_ID,)
        ).fetchone()
        self.assertIsNotNone(row)
        for value in row.values():
            self.assertNotIn(TOKEN, str(value), "channel_credential 任何欄位都不該出現權杖原文")

        # 真正的權杖確實躺在 Vault 裡，不是憑空消失。
        credential = meta_repo.get_credential(web.conn, coredb.DEV_ORG_ID)
        stored = web.conn.execute(
            "SELECT decrypted_secret FROM vault.decrypted_secrets WHERE id = %s",
            (credential["secret_id"],),
        ).fetchone()
        self.assertEqual(stored["decrypted_secret"], TOKEN)

    def test_rejected_token_stores_nothing(self):
        graph.fetch_page = _fake_error
        resp = self.client.post("/api/meta/token", json={"token": TOKEN})
        self.assertEqual(resp.status_code, 400)
        error = resp.json()["error"]
        # F31-I03 (Contract N): Graph's own text never reaches the user; the code does.
        self.assertEqual(error["code"], "meta_token_rejected")
        self.assertEqual(
            error["message"],
            "Meta 拒絕了這個權杖（代碼 190）。請確認權杖沒有過期、是從正確的帳號產生的。",
        )
        self.assertNotIn("OAuth", error["message"])
        self.assertIsNone(meta_repo.get_credential(web.conn, coredb.DEV_ORG_ID))

    def test_code_100_names_the_missing_ads_read_scope(self):
        """F31-I03: a valid token without `ads_read` gets "(#100) Unsupported get request" on
        `me/adaccounts` (measured 2026-09-07). Graph's sentence reads like a wrong URL, so the
        route names the missing permission instead."""
        graph.fetch_page = lambda url, *, params, headers: {"error": {
            "message": "(#100) Unsupported get request. Please read the Graph API documentation"
                       " at https://developers.facebook.com/docs/graph-api",
            "type": "GraphMethodException", "code": 100,
        }}
        resp = self.client.post("/api/meta/token", json={"token": TOKEN})
        self.assertEqual(resp.status_code, 400)
        error = resp.json()["error"]
        self.assertEqual(error["code"], "meta_token_missing_scope")
        self.assertEqual(
            error["message"],
            "這把權杖看不到廣告帳戶，通常是產生權杖時沒有勾 ads_read 權限。"
            "請重新產生一把有勾 ads_read 的權杖再貼上。",
        )
        self.assertNotIn("Unsupported", error["message"])
        self.assertIsNone(meta_repo.get_credential(web.conn, coredb.DEV_ORG_ID))

    def test_permission_error_names_the_missing_scope(self):
        graph.fetch_page = lambda url, *, params, headers: {"error": {
            "message": "(#200) Requires ads_read permission", "code": 200,
        }}
        resp = self.client.post("/api/meta/token", json={"token": TOKEN})
        self.assertEqual(resp.json()["error"]["code"], "meta_token_missing_scope")


# -- 2. 租戶隔離：org B 看不到、綁不到、解不掉 org A 的帳號 --------------------------

class OrgIsolationTest(_MetaHttpTestBase):
    def setUp(self):
        super().setUp()
        self.org_a, self.token_a = self._make_org("a")
        self.org_b, self.token_b = self._make_org("b")
        self.brand_a = bi_repo.create_brand(
            web.conn, org_id=self.org_a, name="A 的品牌", client_name=None, actor="test")["id"]
        connect = self.client.post(
            "/api/meta/token", json={"token": TOKEN},
            headers=self._headers(self.token_a, self.org_a),
        )
        self.account_id = connect.json()["accounts"][0]["id"]

    def test_org_b_cannot_see_org_a_accounts(self):
        resp = self.client.get(
            "/api/meta/accounts", headers=self._headers(self.token_b, self.org_b))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["accounts"], [])

    def test_org_b_cannot_bind_org_a_account(self):
        brand_b = bi_repo.create_brand(
            web.conn, org_id=self.org_b, name="B 的品牌", client_name=None, actor="test")["id"]
        resp = self.client.post(
            f"/api/meta/brands/{brand_b}/accounts/{self.account_id}",
            headers=self._headers(self.token_b, self.org_b),
        )
        self.assertEqual(resp.status_code, 404)

    def test_org_b_cannot_unbind_org_a_binding(self):
        self.client.post(
            f"/api/meta/brands/{self.brand_a}/accounts/{self.account_id}",
            headers=self._headers(self.token_a, self.org_a),
        )
        brand_b = bi_repo.create_brand(
            web.conn, org_id=self.org_b, name="B 的品牌二", client_name=None, actor="test")["id"]
        resp = self.client.delete(
            f"/api/meta/brands/{brand_b}/accounts/{self.account_id}",
            headers=self._headers(self.token_b, self.org_b),
        )
        self.assertEqual(resp.status_code, 404)


# -- 3. 綁定／解除持久化＋各寫一筆 audit_log ------------------------------------------

class BindAuditTest(_MetaHttpTestBase):
    def setUp(self):
        super().setUp()
        self.client.post("/api/meta/token", json={"token": TOKEN})
        accounts = self.client.get("/api/meta/accounts").json()["accounts"]
        self.account_id = accounts[0]["id"]
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="稽核測試品牌", client_name=None, actor="test"
        )["id"]

    def _audit_row(self, action: str):
        return web.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'meta_ad_account' AND action = %s"
            " AND entity_id = %s AND brand_id = %s",
            (action, self.account_id, self.brand_id),
        ).fetchone()

    def test_bind_then_unbind_persists_and_audits(self):
        bind_resp = self.client.post(f"/api/meta/brands/{self.brand_id}/accounts/{self.account_id}")
        self.assertEqual(bind_resp.status_code, 200)
        accounts = self.client.get("/api/meta/accounts").json()["accounts"]
        bound = next(a for a in accounts if a["id"] == self.account_id)
        self.assertEqual(bound["bound_brand_ids"], [self.brand_id])
        self.assertIsNotNone(self._audit_row("bind"))

        unbind_resp = self.client.delete(
            f"/api/meta/brands/{self.brand_id}/accounts/{self.account_id}")
        self.assertEqual(unbind_resp.status_code, 200)
        accounts = self.client.get("/api/meta/accounts").json()["accounts"]
        bound = next(a for a in accounts if a["id"] == self.account_id)
        self.assertEqual(bound["bound_brand_ids"], [])
        self.assertIsNotNone(self._audit_row("unbind"))

    def test_unbind_never_bound_is_not_found(self):
        resp = self.client.delete(f"/api/meta/brands/{self.brand_id}/accounts/{self.account_id}")
        self.assertEqual(resp.status_code, 404)


# -- 4. Graph 客戶端：解析真的成功／錯誤形狀，換掉網路那一支 --------------------------

class GraphClientTest(unittest.TestCase):
    def setUp(self):
        self._orig_fetch_page = graph.fetch_page

    def tearDown(self):
        graph.fetch_page = self._orig_fetch_page

    def test_parses_real_success_shape(self):
        graph.fetch_page = _fake_success
        accounts = graph.list_ad_accounts(TOKEN)
        self.assertEqual(
            accounts, [{"account_id": "1000000000001", "name": "測試帳號一", "currency": "TWD"}]
        )

    def test_turns_real_error_shape_into_human_sentence(self):
        graph.fetch_page = _fake_error
        with self.assertRaises(graph.GraphError) as ctx:
            graph.list_ad_accounts(TOKEN)
        self.assertEqual(ctx.exception.message, "Invalid OAuth access token.")

    def test_non_json_body_becomes_human_sentence(self):
        def fake(url, *, params, headers):
            raise json.JSONDecodeError("Expecting value", "<html>500</html>", 0)

        graph.fetch_page = fake
        with self.assertRaises(graph.GraphError) as ctx:
            graph.list_ad_accounts(TOKEN)
        self.assertIn("看不懂", ctx.exception.message)

    def test_account_missing_fields_falls_back_instead_of_dropping_all(self):
        graph.fetch_page = lambda url, *, params, headers: {
            "data": [
                {"account_id": "1"},  # 缺 name／currency —— 補預設值，不是整包報廢
                {"name": "沒有 id 的帳號"},  # 缺 account_id —— 這筆不能用，跳過
            ],
            "paging": {},
        }
        accounts = graph.list_ad_accounts(TOKEN)
        self.assertEqual(accounts, [{"account_id": "1", "name": "1", "currency": ""}])

    def test_follows_paging(self):
        page1 = {
            "data": [{"account_id": "1", "name": "一", "currency": "TWD"}],
            "paging": {"next": "https://graph.facebook.com/v26.0/me/adaccounts?after=x"},
        }
        page2 = {"data": [{"account_id": "2", "name": "二", "currency": "TWD"}], "paging": {}}
        pages = [page1, page2]

        def fake(url, *, params, headers):
            return pages.pop(0)

        graph.fetch_page = fake
        accounts = graph.list_ad_accounts(TOKEN)
        self.assertEqual([a["account_id"] for a in accounts], ["1", "2"])


# -- 5. channel_credential 的唯一鍵真的是 (org_id, channel_id, account_scope) ----------

class AccountScopeUniquenessTest(_MetaHttpTestBase):
    """票 T4（ADR 0056 §4）：舊表的主鍵只有 `org_id`——一個組織永遠只有一個
    Meta 權杖。`channel_credential` 換成 `unique(org_id, channel_id, account_scope)`，v1
    只寫 `account_scope='*'`，但欄位跟唯一鍵今天就要撐得住兩個不同的 account_scope 共存
    ——這是憲法規則 3 要求的「開關」，不是這張票要用到的功能，只驗證欄位真的在那裡。"""

    def test_two_account_scopes_coexist_a_third_duplicate_violates_the_unique_key(self):
        meta_repo.save_token(web.conn, coredb.DEV_ORG_ID, TOKEN)
        web.conn.commit()
        channel_id = web.conn.execute(
            "SELECT channel_id FROM channel_credential WHERE org_id = %s", (coredb.DEV_ORG_ID,)
        ).fetchone()["channel_id"]

        def _insert(scope: str) -> None:
            # id 每次呼叫都不同（uuid4，不是從 scope 衍生）——要撞的是
            # unique(org_id, channel_id, account_scope)，不能讓 id 這個獨立的 PRIMARY KEY
            # 意外先擋下重複，那樣驗到的就是另一個約束，不是這支測試要證的那一個。
            web.conn.execute(
                "INSERT INTO channel_credential"
                " (id, org_id, channel_id, account_scope, secret_id, token_tail, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, now())",
                (f"chcr_{uuid4().hex[:12]}", coredb.DEV_ORG_ID, channel_id, scope, uuid4(),
                 "test"),
            )

        _insert("act_111")
        _insert("act_222")
        web.conn.commit()
        rows = web.conn.execute(
            "SELECT account_scope FROM channel_credential"
            " WHERE org_id = %s ORDER BY account_scope",
            (coredb.DEV_ORG_ID,),
        ).fetchall()
        self.assertEqual(
            [r["account_scope"] for r in rows], ["*", "act_111", "act_222"],
            "兩個不同 account_scope 的憑證必須都留著，不是互相覆蓋掉",
        )

        with self.assertRaises(psycopg.errors.UniqueViolation):
            _insert("act_111")
        web.conn.rollback()


if __name__ == "__main__":
    unittest.main()
