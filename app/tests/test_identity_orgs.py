"""app/tests/test_identity_orgs.py — 票 03-1：組織改名、邀請、移除成員。"""

import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.identity import repository as identity_repo

from .identity_test_helpers import mint_hs256


class OrgManagementTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)  # 預設帶 dev token（org_dev, owner）

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _new_owner(self) -> tuple[str, str]:
        """建一個全新使用者（首登自動建個人組織、owner），回傳 (token, org_id)。"""
        user_id = uuid4()
        token = mint_hs256(sub=str(user_id), email=f"owner-{user_id.hex[:8]}@example.com")
        me = self.client.get("/api/identity/me", headers=self._auth(token))
        return token, me.json()["org"]["id"]

    def test_rename_current_org_turns_personal_into_company(self):
        token, org_id = self._new_owner()
        response = self.client.post(
            "/api/identity/orgs/current/rename",
            json={"name": "測試公司"},
            headers=self._auth(token),
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["kind"], "company")
        self.assertEqual(body["name"], "測試公司")
        # 確認真的寫進資料庫，不是只有回應好看
        org = identity_repo.get_organisation(web.conn, org_id)
        self.assertEqual(org["kind"], "company")
        self.assertEqual(org["name"], "測試公司")

    def test_rename_does_not_lock_owner_out(self):
        """票 03-3 §1：改名把 kind 從 personal 變成 company 後，沒帶 X-Org-Id 的請求
        仍要能解析回同一個組織（不能 403 forbidden_org）。"""
        token, org_id = self._new_owner()
        rename_resp = self.client.post(
            "/api/identity/orgs/current/rename",
            json={"name": "測試公司"},
            headers=self._auth(token),
        )
        self.assertEqual(rename_resp.status_code, 200, rename_resp.text)
        me = self.client.get("/api/identity/me", headers=self._auth(token))
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["org"]["id"], org_id)

    def test_default_org_is_earliest_membership_deterministic(self):
        """票 03-3 done-check 6：兩個組織成員時，沒帶 X-Org-Id 一律拿最早加入的那個
        （不論 kind），連續問兩次答案要一樣。第一個組織改名成 company 之後才建第二個
        組織，確保「最早」跟「kind='personal'」給的答案不一樣——這樣才是真的在測
        「最早」而不是巧合過關。"""
        token, first_org_id = self._new_owner()
        me = self.client.get("/api/identity/me", headers=self._auth(token))
        user_id = UUID(me.json()["user"]["id"])

        rename_resp = self.client.post(
            "/api/identity/orgs/current/rename",
            json={"name": "第一組織改名"},
            headers=self._auth(token),
        )
        self.assertEqual(rename_resp.status_code, 200, rename_resp.text)

        second_org_id = identity_repo.create_personal_organisation(web.conn, "第二組織")
        identity_repo.create_membership(web.conn, second_org_id, user_id, "owner")
        web.conn.commit()

        first_call = self.client.get("/api/identity/me", headers=self._auth(token))
        second_call = self.client.get("/api/identity/me", headers=self._auth(token))
        self.assertEqual(first_call.status_code, 200, first_call.text)
        self.assertEqual(first_call.json()["org"]["id"], first_org_id)
        self.assertEqual(second_call.json()["org"]["id"], first_org_id)

    def test_rename_requires_owner(self):
        owner_token, org_id = self._new_owner()
        member_id = uuid4()
        member_token = mint_hs256(
            sub=str(member_id), email=f"member-{member_id.hex[:8]}@example.com"
        )
        identity_repo.create_user(web.conn, member_id, f"member-{member_id.hex[:8]}@example.com")
        identity_repo.create_membership(web.conn, org_id, member_id, "member")
        web.conn.commit()
        response = self.client.post(
            "/api/identity/orgs/current/rename",
            json={"name": "不該成功"},
            headers={**self._auth(member_token), "X-Org-Id": org_id},
        )
        self.assertEqual(response.status_code, 403)

    def test_invite_create_and_accept_local_returns_accept_url(self):
        owner_token, org_id = self._new_owner()
        create_resp = self.client.post(
            "/api/identity/invites",
            json={"email": "invitee@example.com", "role": "member"},
            headers=self._auth(owner_token),
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        body = create_resp.json()
        self.assertIsNotNone(body["accept_url"], "SUPABASE_URL 是本機時應該直接回傳連結")
        # 票 03-3 §2：SPA 只掛在 /app，accept_url 沒有這個前綴的話，連結點下去只會
        # 打到 FastAPI 的通用 404 頁，邀請連結完全不能用。
        self.assertTrue(
            body["accept_url"].startswith("/app/accept-invite?token="),
            f"accept_url 要有 /app 前綴（SPA 掛載點），實際是 {body['accept_url']!r}",
        )
        token_str = body["accept_url"].split("token=")[1]

        invitee_id = uuid4()
        invitee_token = mint_hs256(
            sub=str(invitee_id), email=f"invitee-{invitee_id.hex[:8]}@example.com"
        )
        accept_resp = self.client.post(
            f"/api/identity/invites/{token_str}/accept", headers=self._auth(invitee_token)
        )
        self.assertEqual(accept_resp.status_code, 200, accept_resp.text)
        self.assertEqual(accept_resp.json()["org"]["id"], org_id)

        membership = identity_repo.get_membership(web.conn, org_id, invitee_id)
        self.assertIsNotNone(membership)
        self.assertEqual(membership["role"], "member")

    def test_invite_accept_twice_is_410(self):
        owner_token, org_id = self._new_owner()
        create_resp = self.client.post(
            "/api/identity/invites",
            json={"email": "twice@example.com", "role": "member"},
            headers=self._auth(owner_token),
        )
        token_str = create_resp.json()["accept_url"].split("token=")[1]
        invitee_id = uuid4()
        invitee_token = mint_hs256(
            sub=str(invitee_id), email=f"twice-{invitee_id.hex[:8]}@example.com"
        )
        first = self.client.post(
            f"/api/identity/invites/{token_str}/accept", headers=self._auth(invitee_token)
        )
        self.assertEqual(first.status_code, 200)

        second_id = uuid4()
        second_token = mint_hs256(
            sub=str(second_id), email=f"twice2-{second_id.hex[:8]}@example.com"
        )
        second = self.client.post(
            f"/api/identity/invites/{token_str}/accept", headers=self._auth(second_token)
        )
        self.assertEqual(second.status_code, 410)

    def test_expired_invite_is_410(self):
        owner_token, org_id = self._new_owner()
        owner_me = self.client.get("/api/identity/me", headers=self._auth(owner_token))
        owner_id = owner_me.json()["user"]["id"]
        from datetime import timedelta
        from uuid import UUID

        from app.core.db import new_id, now_utc

        invite_id = new_id("inv")
        web.conn.execute(
            "INSERT INTO org_invite"
            " (id, org_id, email, role, token, expires_at, created_by, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (invite_id, org_id, "expired@example.com", "member", "expired-token-xyz",
             now_utc() - timedelta(days=1), UUID(owner_id), now_utc()),
        )
        web.conn.commit()
        user_id = uuid4()
        token = mint_hs256(sub=str(user_id), email=f"exp-{user_id.hex[:8]}@example.com")
        response = self.client.post(
            "/api/identity/invites/expired-token-xyz/accept", headers=self._auth(token)
        )
        self.assertEqual(response.status_code, 410)

    def test_remove_member_last_owner_is_409(self):
        owner_token, org_id = self._new_owner()
        me = self.client.get("/api/identity/me", headers=self._auth(owner_token))
        owner_id = me.json()["user"]["id"]
        response = self.client.delete(
            f"/api/identity/members/{owner_id}", headers=self._auth(owner_token)
        )
        self.assertEqual(response.status_code, 409)

    def test_remove_member_non_last_owner_succeeds(self):
        owner_token, org_id = self._new_owner()
        member_id = uuid4()
        identity_repo.create_user(web.conn, member_id, f"m-{member_id.hex[:8]}@example.com")
        identity_repo.create_membership(web.conn, org_id, member_id, "member")
        web.conn.commit()
        response = self.client.delete(
            f"/api/identity/members/{member_id}", headers=self._auth(owner_token)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(identity_repo.get_membership(web.conn, org_id, member_id))

    def test_remove_member_requires_owner(self):
        owner_token, org_id = self._new_owner()
        member_id = uuid4()
        member_token = mint_hs256(
            sub=str(member_id), email=f"mm-{member_id.hex[:8]}@example.com"
        )
        identity_repo.create_user(web.conn, member_id, f"mm-{member_id.hex[:8]}@example.com")
        identity_repo.create_membership(web.conn, org_id, member_id, "member")
        web.conn.commit()
        response = self.client.delete(
            f"/api/identity/members/{member_id}",
            headers={**self._auth(member_token), "X-Org-Id": org_id},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
