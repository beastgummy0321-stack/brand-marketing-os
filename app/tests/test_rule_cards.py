"""app/tests/test_rule_cards.py — 規則卡通用機制（issue #12；分品牌：設定中心票 01）。

驗：門檻值有預設種子、改值落庫後讀值立即用新值、重設回預設值、
分品牌覆寫互不干擾（A 品牌改值不影響 B 品牌、沒覆寫時繼續拿系統預設值）。
"""

import os
import unittest

import psycopg
from psycopg.rows import dict_row

from app.core import db, rule_cards

BID_A = "brand_a"
BID_B = "brand_b"


class RuleCardValueTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # ADR 0027：conftest.py 逐「模組」一個 schema，不是逐「測試」——BID_A／BID_B 是整檔
        # 共用的固定字面值，任何一個測試對它們的 set_value() 不清乾淨，就會滲漏進其他測試
        # 方法。每個測試開始前把這兩個品牌的規則卡覆寫值全部清空，回到「沒有任何覆寫，
        # 全部拿系統預設值」的乾淨起點。
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id IN (%s, %s)", (BID_A, BID_B))
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id IN (%s, %s)",
            (BID_A, BID_B),
        )
        self.conn.commit()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    # -- 種子與預設值 -------------------------------------------------------

    def test_get_value_falls_back_to_default_without_db(self):
        """conn=None 或表還沒建起來時（例如全新 schema 還沒跑 migrations），優雅回程式
        常數預設值，不噴錯（principles 16）。「表還沒建起來」在 Postgres 世界模擬成一個
        全新、沒跑過任何 migration 的 schema（跟 conftest.py 逐模組建的正常 schema不同）。"""
        self.assertEqual(rule_cards.get_value(None, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

        bare_schema = f"t_bare_rule_cards_{os.getpid()}"
        base_dsn = db.dsn().split("?", 1)[0]
        admin = psycopg.connect(base_dsn, autocommit=True, row_factory=dict_row)
        admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
        admin.execute(f'CREATE SCHEMA "{bare_schema}"')
        admin.execute(f'SET search_path TO "{bare_schema}"')
        bare = db.Conn(admin)
        try:
            self.assertEqual(
                rule_cards.get_value(bare, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)
        finally:
            admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
            admin.close()

    def test_unknown_card_or_field_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "沒這張卡", "x")
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "沒這個欄位")

    def test_list_cards_includes_human_readable_metadata(self):
        cards = rule_cards.list_cards(self.conn, BID_A)
        self.assertEqual(len(cards), 4)  # 2026-08-29 刪掉六張沒有消費端的卡，剩四張
        by_key = {c["key"]: c for c in cards}
        self.assertIn("規則", by_key["rule_prompt_cap"]["title"])
        for c in cards:
            self.assertTrue(c["description"])  # 「這個門檻管什麼」說明不可空
            for f in c["fields"]:
                self.assertTrue(f["label"])
                self.assertTrue(f["help"])

    def test_rule_prompt_cap_default_matches_adr_0012(self):
        """票 02-prompt-cap-and-overflow-list：進生成提示詞的規則上限，系統預設 20 條
        （ADR 0012 第二節），沒有種子 migration，靠 CARDS default 落地就夠。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

    def test_rule_expiry_default_matches_adr_0037(self):
        """票 10-feedback-entries：規則重新確認門檻，系統預設 90 天（ADR 0037，取代
        ADR 0012 第一節原本的「6 期」單位），沒有種子 migration，靠 CARDS default 落地就夠。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_expiry", "reconfirm_days"), 90.0)

    # -- 改值即時生效 ---------------------------------------------------------

    def test_set_value_persists_and_is_read_back_immediately(self):
        """改值落庫後，讀卡立即拿到新值——不用重開程式、不用清快取。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 35.0, actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 35.0)

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "rule_card_value")
        self.assertEqual(rows[0]["entity_id"], "rule_prompt_cap.max_active_rules")
        self.assertEqual(rows[0]["action"], "update")
        self.assertEqual(rows[0]["actor"], "測試員")
        self.assertEqual(rows[0]["brand_id"], BID_A)  # 分品牌後是真正的品牌事件（不再是 None）

    def test_set_value_upserts_without_duplicating_row(self):
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 30.0, actor="A", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 33.0, actor="B", org_id=db.DEV_ORG_ID)
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule_card_value WHERE brand_id = %s AND card_key = 'rule_prompt_cap'"
            " AND field_key = 'max_active_rules'", (BID_A,)
        ).fetchone()["n"]
        self.assertEqual(count, 1)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 33.0)

    # -- 分品牌隔離（設定中心票 01） -------------------------------------------

    def test_brand_override_does_not_leak_into_other_brand(self):
        """A 品牌改規則卡值，B 品牌完全不受影響——各自一份覆寫值。"""
        rule_cards.set_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules", 99.0, actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 99.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_B, "rule_prompt_cap", "max_active_rules"), 20.0)

    def test_brand_without_override_falls_back_to_system_default(self):
        """B 品牌從沒改過這個欄位——就算 A 品牌已經改過，B 品牌繼續拿系統預設值。"""
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 3.0,
                             actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_B, "schedule_plan_count", "plan_count_max"), 5.0)

    # -- 重設 -----------------------------------------------------------------

    def test_reset_card_restores_defaults(self):
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_min", 2.0, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 9.0, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.reset_card(self.conn, BID_A, "schedule_plan_count", actor="測試員", org_id=db.DEV_ORG_ID)

        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "schedule_plan_count", "plan_count_min"), 1.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max"), 5.0)

    def test_reset_skips_fields_already_at_default_no_noise_audit(self):
        rule_cards.set_value(self.conn, BID_A, "schedule_plan_count", "plan_count_max", 9.0, actor="測試員", org_id=db.DEV_ORG_ID)
        before = len(self._audit_rows())
        rule_cards.reset_card(self.conn, BID_A, "schedule_plan_count", actor="測試員", org_id=db.DEV_ORG_ID)
        after_rows = self._audit_rows()
        # 只有 plan_count_max 被測試改過；plan_count_min 本來就是 CARDS 現在的 default，
        # reset 不該產生額外稽核噪音。
        self.assertEqual(len(after_rows) - before, 1)
        touched = {r["entity_id"] for r in after_rows[-1:]}
        self.assertEqual(touched, {"schedule_plan_count.plan_count_max"})

    def test_reset_unknown_card_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.reset_card(self.conn, BID_A, "沒這張卡", actor="測試員", org_id=db.DEV_ORG_ID)


if __name__ == "__main__":
    unittest.main()
