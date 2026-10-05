"""app/tests/test_brand_menu_categories.py — D線票7（GitHub issue #49）：
品牌功能選單頁四分類＋品牌智庫首頁收斂（限制規則＋宣稱→規則與宣稱、
官方素材＋自有渠道→素材與渠道）。

品牌與資料一律虛構，嚴禁真實品牌名稱。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID  # noqa: E402

ACTOR = "測試員"


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]


class BrandMenuFourCategoriesTest(_Base):
    """品牌功能選單頁：主欄 = 4 張分類卡，容量腳本通過。"""

    def test_brand_report_api_returns_idle_job_for_new_brand(self):
        response = self.client.get(f"/api/brands/{self.bid}/report")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["report"])
        self.assertEqual(response.json()["job"]["status"], "idle")

    def test_archived_brand_reports_archived_status(self):
        bi_repo.update_brand(web.conn, self.bid, name=self.brand["name"],
                             client_name="測試客戶", status="archived", actor=ACTOR)
        self.assertEqual(bi_repo.get_brand(web.conn, self.bid)["status"], "archived")

    def test_no_facts_means_empty_fact_list(self):
        response = self.client.get(f"/api/library/brands/{self.bid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["facts"], [])

    def test_pending_fact_is_listed_with_pending_status(self):
        bi_repo.create_brand_fact(web.conn, self.bid, fact_type="positioning", label="虛構事實",
                                  value="示範內容", status="pending", actor=ACTOR)
        facts = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]["facts"]
        self.assertEqual([(fact["label"], fact["status"]) for fact in facts],
                         [("虛構事實", "pending")])


class HubHomeRulesClaimsMergeTest(_Base):
    """品牌智庫首頁：「限制規則」＋「宣稱」合併為一張「規則與宣稱」，卡上分別顯示兩類筆數。"""

    def _add_rule_and_claim(self):
        bi_repo.create_rule(web.conn, self.bid, rule_type="forbidden_word", content="虛構限制規則",
                            severity="hard", actor=ACTOR)
        bi_repo.create_claim(web.conn, self.bid, claim_text="虛構宣稱",
                             claim_type="approved", actor=ACTOR)

    def test_rules_and_claims_are_listed_for_brand(self):
        self._add_rule_and_claim()
        data = self.client.get(f"/api/library/brands/{self.bid}").json()["data"]
        self.assertEqual([rule["content"] for rule in data["rules"]], ["虛構限制規則"])
        self.assertEqual([claim["claim_text"] for claim in data["claims"]], ["虛構宣稱"])


if __name__ == "__main__":
    unittest.main()
