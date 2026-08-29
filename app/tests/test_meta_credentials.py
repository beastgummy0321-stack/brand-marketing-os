"""app/tests/test_meta_credentials.py — 票 04：連接 Meta 廣告帳戶。

四件事，只寫這四件（docs/workflow-diet.md 第 4 條：金額、租戶隔離、API 契約、資料
正確性；畫面行為不寫單元測試，見 04-design-approved.md「Tests」節）：

1. 貼上的權杖經過 Vault 存好；`app_setting` 完全沒被動到，`meta_credential` 沒有任何
   欄位出現過權杖原文。
2. 一個組織連接並綁定的帳號，另一個組織在 GET /api/meta/accounts、bind、unbind 三條
   路由上都看不到／碰不到。
3. 綁定、解除各寫一筆 audit_log。
4. Graph 客戶端解析真的成功／錯誤形狀，把錯誤形狀轉成人話——換掉 `graph.fetch_page`
   （同 app/core/net.py fetch_url 在 test_intake.py 的替換慣例），測試不打真正的網路。
"""

import json
import unittest
from uuid import uuid4

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


# -- 1. Vault 落地；app_setting 不動、meta_credential 不存權杖原文 --------------------

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
            "SELECT * FROM meta_credential WHERE org_id = %s", (coredb.DEV_ORG_ID,)
        ).fetchone()
        self.assertIsNotNone(row)
        for value in row.values():
            self.assertNotIn(TOKEN, str(value), "meta_credential 任何欄位都不該出現權杖原文")

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
        self.assertIn("Invalid OAuth access token.", resp.json()["error"]["message"])
        self.assertIsNone(meta_repo.get_credential(web.conn, coredb.DEV_ORG_ID))


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


if __name__ == "__main__":
    unittest.main()
