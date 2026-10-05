"""app/tests/test_rules_claims_edit.py — 規則／宣稱編輯（issue #2）。

見 app/main.py 的 rule_edit_*／claim_edit_* 路由，比照品牌事實編輯（決策 0013）。
"""

import unittest

from app.brand_intelligence import repository as repo
from app.core import db


class RuleClaimEditTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    def test_update_rule_changes_content_and_severity(self):
        brand = repo.create_brand(self.conn, name="晨露茶飲", client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)
        rule = repo.create_rule(self.conn, brand["id"], rule_type="tone", content="舊內容",
                                 severity="soft", actor="測試員")
        after = repo.update_rule(self.conn, brand["id"], rule["id"], actor="測試員",
                                  rule_type="forbidden_word", content="新內容", severity="hard")
        self.assertEqual(after["content"], "新內容")
        self.assertEqual(after["severity"], "hard")
        self.assertEqual(after["rule_type"], "forbidden_word")
        # 落地確認：重新查一次也要是新值
        self.assertEqual(repo.get_rule(self.conn, brand["id"], rule["id"])["content"], "新內容")

    def test_update_claim_changes_text_and_type(self):
        brand = repo.create_brand(self.conn, name="山嵐選物", client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)
        claim = repo.create_claim(self.conn, brand["id"], claim_text="舊宣稱",
                                   claim_type="high_risk", actor="測試員")
        after = repo.update_claim(self.conn, brand["id"], claim["id"], actor="測試員",
                                   claim_text="新宣稱", claim_type="approved")
        self.assertEqual(after["claim_text"], "新宣稱")
        self.assertEqual(after["claim_type"], "approved")
        self.assertEqual(repo.get_claim(self.conn, brand["id"], claim["id"])["claim_text"], "新宣稱")

    def test_cross_brand_lookup_and_update_blocked(self):
        a = repo.create_brand(self.conn, name="晨露茶飲（跨品牌測試）", client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)
        b = repo.create_brand(self.conn, name="山嵐選物（跨品牌測試）", client_name=None, actor="測試員", org_id=db.DEV_ORG_ID)
        rule = repo.create_rule(self.conn, a["id"], rule_type="tone", content="A的規則",
                                 severity="soft", actor="測試員")
        claim = repo.create_claim(self.conn, a["id"], claim_text="A的宣稱",
                                   claim_type="approved", actor="測試員")

        # 用另一個品牌的 id 查不到（main.py 路由據此判斷回 404）
        self.assertIsNone(repo.get_rule(self.conn, b["id"], rule["id"]))
        self.assertIsNone(repo.get_claim(self.conn, b["id"], claim["id"]))

        with self.assertRaises(ValueError):
            repo.update_rule(self.conn, b["id"], rule["id"], actor="測試員",
                              rule_type="tone", content="改壞了", severity="soft")
        with self.assertRaises(ValueError):
            repo.update_claim(self.conn, b["id"], claim["id"], actor="測試員",
                               claim_text="改壞了", claim_type="approved")

        # 沒有被改到
        self.assertEqual(repo.get_rule(self.conn, a["id"], rule["id"])["content"], "A的規則")
        self.assertEqual(repo.get_claim(self.conn, a["id"], claim["id"])["claim_text"], "A的宣稱")

    def test_audit_log_has_before_and_after(self):
        brand = repo.create_brand(self.conn, name="晨露茶飲（稽核測試）", client_name=None, actor="小陳", org_id=db.DEV_ORG_ID)
        rule = repo.create_rule(self.conn, brand["id"], rule_type="tone", content="舊規則內容",
                                 severity="soft", actor="小陳")
        claim = repo.create_claim(self.conn, brand["id"], claim_text="舊宣稱內容",
                                   claim_type="high_risk", actor="小陳")

        repo.update_rule(self.conn, brand["id"], rule["id"], actor="小陳",
                          rule_type="tone", content="新規則內容", severity="hard")
        repo.update_claim(self.conn, brand["id"], claim["id"], actor="小陳",
                           claim_text="新宣稱內容", claim_type="approved")

        rows = self._audit_rows()
        rule_update = [r for r in rows if r["entity_type"] == "rule" and r["action"] == "update"]
        claim_update = [r for r in rows if r["entity_type"] == "claim" and r["action"] == "update"]
        self.assertEqual(len(rule_update), 1)
        self.assertEqual(len(claim_update), 1)

        # jsonb 欄位，psycopg 已自動解碼成 dict，不必 json.loads
        self.assertEqual(rule_update[0]["before_json"]["content"], "舊規則內容")
        self.assertEqual(rule_update[0]["after_json"]["content"], "新規則內容")
        self.assertEqual(rule_update[0]["actor"], "小陳")

        self.assertEqual(claim_update[0]["before_json"]["claim_text"], "舊宣稱內容")
        self.assertEqual(claim_update[0]["after_json"]["claim_text"], "新宣稱內容")
        self.assertEqual(claim_update[0]["actor"], "小陳")


if __name__ == "__main__":
    unittest.main()
