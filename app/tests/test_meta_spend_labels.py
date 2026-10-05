"""app/tests/test_meta_spend_labels.py — F31-I03 (Contract N): `/api/meta/brands/{b}/spend`
says how fresh its numbers are and which attribution window they use.

Drill wording items 3 and 5: the cockpit printed 「尚未成功拉取」 beside real numbers, because
`last_pull_at` is the oldest per-account success time and stays None while any bound account
never finished a pull (rows can exist anyway: another account, a backfill). `data_pulled_at` is
the newest `pulled_at` of the rows actually summed. The ROAS tile never named its attribution
window although every row stores it (`meta_entity_spend.attribution_window`).
"""

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.identity import repository as identity_repo
from app.meta import repository as meta_repo

from .identity_test_helpers import mint_hs256

TOKEN = "EAAtest-fake-meta-token-spend-labels"


class SpendFreshnessAndAttributionTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.org_id = f"org_spend_labels_{uuid4().hex[:10]}"
        web.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')",
            (self.org_id, self.org_id),
        )
        user_id = uuid4()
        email = f"spend-labels-{user_id.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, user_id, email)
        identity_repo.create_membership(web.conn, self.org_id, user_id, "owner")
        self.headers = {
            "Authorization": f"Bearer {mint_hs256(sub=str(user_id), email=email)}",
            "X-Org-Id": self.org_id,
        }
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="標籤測試品牌", client_name=None, actor="test",
        )["id"]
        meta_repo.save_token(web.conn, self.org_id, TOKEN)
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": f"act-{uuid4().hex[:8]}", "name": "帳號", "currency": "TWD"},
        ])
        self.account_id = meta_repo.list_accounts(web.conn, self.org_id)[0]["id"]
        meta_repo.bind(web.conn, self.org_id, self.brand_id, self.account_id)
        web.conn.commit()

    def _spend(self) -> dict:
        resp = self.client.get(f"/api/meta/brands/{self.brand_id}/spend", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _write_row(self, window: str = "7d_click,1d_view") -> None:
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        meta_repo.upsert_entity_spend(web.conn, self.org_id, self.account_id, [{
            "level": "campaign", "entity_id": "c-1", "entity_name": "活動一",
            "campaign_id": "c-1", "adset_id": None, "ad_id": None, "spend_date": today,
            "spend": 1200, "impressions": 3000, "clicks": 90, "roas": 2.2,
            "actions": None, "action_values": None, "attribution_window": window,
        }])
        web.conn.commit()

    def test_rows_without_a_finished_account_pull_still_say_when_they_were_read(self):
        self._write_row()
        body = self._spend()
        self.assertIsNone(body["last_pull_at"])  # the account never finished a pull
        self.assertEqual(body["totals"][0]["spend"], 1200)
        self.assertIsNotNone(body["data_pulled_at"])
        self.assertEqual(body["attribution_label"], "點擊後 7 天＋瀏覽後 1 天")

    def test_totals_never_sum_different_currencies(self):
        self._write_row()
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": "act-usd", "name": "USD account", "currency": "USD"},
        ])
        account = next(a for a in meta_repo.list_accounts(web.conn, self.org_id)
                       if a["currency"] == "USD")
        self.account_id = account["id"]
        meta_repo.bind(web.conn, self.org_id, self.brand_id, self.account_id)
        self._write_row()
        body = self._spend()
        self.assertNotIn("total", body)
        self.assertEqual([(t["currency"], t["spend"], t["roas_platform"])
                          for t in body["totals"]], [("TWD", 1200, 2.2), ("USD", 1200, 2.2)])
        self.assertEqual([c["currency"] for c in body["campaigns"]], ["TWD", "USD"])

    def test_no_rows_means_both_unknown(self):
        body = self._spend()
        self.assertIsNone(body["data_pulled_at"])
        self.assertIsNone(body["attribution_label"])

    def test_attribution_label_mapping(self):
        self.assertEqual(meta_repo.attribution_label("7d_click"), "點擊後 7 天")
        self.assertEqual(meta_repo.attribution_label("28d_click,1d_view"),
                         "點擊後 28 天＋瀏覽後 1 天")
        self.assertEqual(meta_repo.attribution_label("dda"), "dda")
        self.assertIsNone(meta_repo.attribution_label(None))


if __name__ == "__main__":
    unittest.main()
